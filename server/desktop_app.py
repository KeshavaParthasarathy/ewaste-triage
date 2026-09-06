"""Product-only Flask factory for the packaged desktop application."""

from __future__ import annotations

import base64
from copy import deepcopy
import io
from pathlib import Path
from collections.abc import Mapping
import math
import sqlite3
import threading
import time

import numpy as np
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from PIL import Image, UnidentifiedImageError
import qrcode

from desktop.server_thread import PhoneServerController
from server.explanations import ActiveSourceImageStore, occlusion_map
from server.imaging import ImageTooLarge, inference_crop, normalize_image
from server.lifecycle import AssessmentInputs, Condition, OperationalState, Range, Usage, assess_component
from server.history import AssessmentConflictError
from server.netinfo import preferred_lan_address
from server.phone_app import create_phone_app
from server.phone_sessions import PhoneSessionManager


MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_LIFECYCLE_YEARS = 100
MAX_LIFECYCLE_CYCLES = 1_000_000
USER_PROVIDED_EVIDENCE_GRADE = "user_provided_unverified"


class _PhoneResultInbox:
    """Keep at most one detached phone result until the desktop consumes it."""

    def __init__(self):
        self._lock = threading.Lock()
        self._result = None

    def put(self, result):
        with self._lock:
            self._result = deepcopy(dict(result))

    def pop(self):
        with self._lock:
            result = self._result
            self._result = None
        return deepcopy(result)

    def clear(self):
        with self._lock:
            self._result = None


def _phone_qr_data_url(url: str) -> str:
    """Encode a tokenized URL as an in-memory PNG data URL."""
    output = io.BytesIO()
    qrcode.make(url).save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def create_desktop_app(
    *,
    classifier,
    history_store=None,
    static_dir: Path | None = None,
    source_image_store=None,
    clock=None,
    reference_store=None,
    lifecycle_assessor=assess_component,
    phone_sessions=None,
    phone_server_factory=None,
    lan_address_provider=None,
    phone_clock=None,
    phone_monitor_interval=0.25,
):
    """Build the user product without collection or valuation dependencies."""
    static_dir = Path(static_dir or Path(__file__).parent / "static")
    phone_clock = phone_clock or time.monotonic
    phone_sessions = phone_sessions or PhoneSessionManager(now=phone_clock)
    phone_server_factory = phone_server_factory or PhoneServerController
    lan_address_provider = lan_address_provider or preferred_lan_address
    if (
        isinstance(phone_monitor_interval, bool)
        or not isinstance(phone_monitor_interval, (int, float))
        or not math.isfinite(phone_monitor_interval)
        or phone_monitor_interval <= 0
    ):
        raise ValueError("phone_monitor_interval must be a finite positive number")

    app = Flask(__name__, static_folder=None)
    app.config.update(
        CLASSIFIER=classifier,
        HISTORY_STORE=history_store,
        SOURCE_IMAGE_STORE=(
            source_image_store if source_image_store is not None
            else ActiveSourceImageStore(clock=clock) if clock is not None
            else ActiveSourceImageStore()
        ),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        REFERENCE_STORE=reference_store,
        LIFECYCLE_ASSESSOR=lifecycle_assessor,
        PHONE_SESSIONS=phone_sessions,
    )

    def assessment_error(message, status):
        return jsonify({"error": message}), status

    def reference():
        return app.config["REFERENCE_STORE"]

    def validate_range(value, name):
        if not isinstance(value, Mapping) or set(value) != {"minimum", "maximum"}:
            raise ValueError(f"{name} must contain minimum and maximum")
        minimum, maximum = value["minimum"], value["maximum"]
        if type(minimum) is not int or type(maximum) is not int:
            raise ValueError(f"{name} bounds must be integers")
        maximum_allowed = 1_200 if name == "age_months" else 10_000_000
        if minimum < 0 or maximum < minimum or maximum > maximum_allowed:
            raise OverflowError(f"{name} bounds are reversed or outside accepted bounds")
        return {"minimum": minimum, "maximum": maximum}

    def validate_enum(value, enum, name):
        if not isinstance(value, str):
            raise ValueError(f"invalid {name}")
        try:
            return enum(value).value
        except ValueError as exc:
            raise ValueError(f"invalid {name}") from exc

    def validate_lifecycle(lifecycle):
        allowed = {"metric", "minimum", "maximum", "capacity_percent"}
        required = {"metric", "minimum", "maximum"}
        if not isinstance(lifecycle, Mapping):
            raise ValueError("component lifecycle must be a supported mapping")
        fields = set(lifecycle)
        if fields - allowed or not required <= fields:
            raise ValueError("component lifecycle must be a supported mapping")
        metric = lifecycle["metric"]
        if not isinstance(metric, str) or metric not in {
            "years",
            "cycles",
            "cycles_to_capacity",
        }:
            raise ValueError("unsupported component lifecycle metric")
        minimum, maximum = lifecycle["minimum"], lifecycle["maximum"]
        for bound in (minimum, maximum):
            if isinstance(bound, float) and not math.isfinite(bound):
                raise OverflowError("component lifecycle bounds must be finite")
            if type(bound) is not int:
                raise ValueError("component lifecycle bounds must be integers")
        maximum_lifetime = (
            MAX_LIFECYCLE_YEARS
            if metric == "years"
            else MAX_LIFECYCLE_CYCLES
        )
        if minimum <= 0 or maximum < minimum or maximum > maximum_lifetime:
            raise OverflowError(
                "component lifecycle bounds are reversed or outside accepted bounds"
            )
        has_capacity = "capacity_percent" in lifecycle
        if metric == "cycles_to_capacity" and not has_capacity:
            raise ValueError("cycles_to_capacity requires capacity_percent")
        if metric != "cycles_to_capacity" and has_capacity:
            raise ValueError("capacity_percent is only valid for cycles_to_capacity")
        if has_capacity:
            capacity = lifecycle["capacity_percent"]
            if isinstance(capacity, float) and not math.isfinite(capacity):
                raise OverflowError("capacity_percent must be finite")
            if type(capacity) is not int:
                raise ValueError("capacity_percent must be an integer")
            if not 1 <= capacity <= 100:
                raise OverflowError("capacity_percent is outside accepted bounds")
        return dict(lifecycle)

    def validate_payload(payload):
        if not isinstance(payload, Mapping):
            raise ValueError("assessment payload must be an object")
        allowed = {"age_months", "cycle_count", "usage", "condition", "operational", "component_overrides"}
        if set(payload) - allowed:
            raise ValueError("assessment payload contains unsupported fields")
        result = {}
        for name, enum in (("usage", Usage), ("condition", Condition), ("operational", OperationalState)):
            value = payload.get(name, getattr(enum, "UNKNOWN").value)
            result[name] = validate_enum(value, enum, name)
        for name in ("age_months", "cycle_count"):
            if name in payload and payload[name] is not None:
                result[name] = validate_range(payload[name], name)
            else:
                result[name] = None
        overrides = payload.get("component_overrides", {})
        if not isinstance(overrides, Mapping):
            raise ValueError("component_overrides must be an object")
        clean_overrides = {}
        allowed_override = {"presence_label", "condition", "lifecycle"}
        for component_id, override in overrides.items():
            if not isinstance(component_id, str) or not component_id or not isinstance(override, Mapping):
                raise ValueError("component overrides must use component IDs and object values")
            if set(override) - allowed_override:
                raise ValueError("component override contains unsupported fields")
            clean = dict(override)
            if "presence_label" in clean:
                presence_label = clean["presence_label"]
                if not isinstance(presence_label, str) or presence_label not in {
                    "standard",
                    "common",
                    "optional",
                    "unknown",
                }:
                    raise ValueError("invalid component presence_label")
            for name, enum in (("condition", Condition),):
                if name in clean:
                    clean[name] = validate_enum(
                        clean[name], enum, f"component {name}"
                    )
            if "lifecycle" in clean:
                clean["lifecycle"] = validate_lifecycle(clean["lifecycle"])
            clean_overrides[component_id] = clean
        result["component_overrides"] = clean_overrides
        return result

    def result_json(result):
        return {
            "percent_used": None if result.percent_used is None else {"minimum": result.percent_used.minimum, "maximum": result.percent_used.maximum},
            "confidence": result.confidence.value,
            "recommendation": result.recommendation.value,
            "reasons": list(result.reasons),
            "evidence": [{"kind": item.kind, "detail": item.detail, "source_ids": list(item.source_ids)} for item in result.evidence],
        }

    def computed_components(template, payload):
        age = payload["age_months"]
        cycles = payload["cycle_count"]
        outputs = []
        for original in template["components"]:
            override = payload["component_overrides"].get(original["component_id"], {})
            component = dict(original)
            component.update({key: value for key, value in override.items() if key not in {"condition", "operational"}})
            if isinstance(component.get("lifecycle"), Mapping):
                lifecycle = dict(component["lifecycle"])
                if "lifecycle" in override:
                    lifecycle.update({
                        "source_ids": [],
                        "evidence_grade": USER_PROVIDED_EVIDENCE_GRADE,
                        "reviewed_on": None,
                    })
                else:
                    lifecycle["source_ids"] = lifecycle.get(
                        "source_ids", component.get("source_ids", [])
                    )
                component["lifecycle"] = lifecycle
            inputs = AssessmentInputs(
                age_months=Range(**age) if age else None,
                cycle_count=Range(**cycles) if cycles else None,
                usage=Usage(payload["usage"]),
                condition=Condition(override.get("condition", payload["condition"])),
                operational=OperationalState(override.get("operational", payload["operational"])),
            )
            outputs.append({**component, "result": result_json(app.config["LIFECYCLE_ASSESSOR"](component, inputs))})
        return outputs

    def assessment_for(scan_id):
        store = app.config["HISTORY_STORE"]
        if store is None or store.get_scan(scan_id) is None:
            return None, assessment_error("scan not found", 404)
        scan = store.get_scan(scan_id)
        confirmation = scan.get("confirmation")
        if confirmation is None:
            return None, assessment_error("confirm or correct the category before starting an assessment", 409)
        existing = store.get_assessment(scan_id)
        if existing is not None:
            return existing, None
        refs = reference()
        if refs is None:
            return None, assessment_error("component reference data is unavailable", 503)
        category_id = confirmation["accepted_class_name"]
        try:
            template = refs.snapshot(category_id)
        except KeyError:
            return None, assessment_error("no component template is available for the confirmed category", 404)
        except (sqlite3.Error, ValueError, RuntimeError):
            return None, assessment_error("component reference data is unavailable", 503)
        try:
            assessment = store.create_assessment(scan_id, template)
        except AssessmentConflictError:
            return None, assessment_error("confirmed category changed before assessment creation", 409)
        if not assessment["components"]:
            payload = validate_payload(assessment["inputs"])
            assessment = store.update_assessment(
                scan_id,
                {key: value for key, value in payload.items() if key != "component_overrides"},
                payload["component_overrides"],
                computed_components(assessment["template"], payload),
            )
        return assessment, None

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify({
            "error": "Photo is too large. Choose an image smaller than 8 MB and try again."
        }), 413

    def read_image():
        if "image" not in request.files:
            return None, (jsonify({"error": "no file field named 'image'"}), 400)
        try:
            return normalize_image(Image.open(request.files["image"].stream)), None
        except ImageTooLarge as exc:
            return None, (jsonify({"error": str(exc)}), 413)
        except Image.DecompressionBombError:
            return None, (jsonify({"error": "image exceeds 40,000,000 pixels"}), 413)
        except (UnidentifiedImageError, OSError):
            return None, (jsonify({"error": "uploaded file is not a decodable image"}), 400)

    def classify_normalized_image(image, *, retain_original=False):
        result = dict(app.config["CLASSIFIER"].classify(image))
        scan_id = None
        store = app.config["HISTORY_STORE"]
        if store is not None:
            try:
                scan_id = store.add_scan(
                    result,
                    image,
                    retain_original=retain_original,
                    original=image if retain_original else None,
                )
            except Exception:
                app.logger.exception(
                    "classification succeeded but history persistence failed"
                )
                result["history_error"] = (
                    "Classification complete, but this scan was not saved to history."
                )
        result["scan_id"] = scan_id
        if scan_id is not None:
            classes = getattr(app.config["CLASSIFIER"], "classes", None)
            class_index = (
                classes.index(result["class_name"])
                if classes is not None and result["class_name"] in classes
                else None
            )
            app.config["SOURCE_IMAGE_STORE"].put(
                scan_id,
                inference_crop(image),
                class_index=class_index,
            )
        return result

    phone_inbox = _PhoneResultInbox()
    phone_operation_lock = threading.Lock()

    def receive_phone_result(result):
        token = request.form.get("token")
        pairing_code = request.form.get("code")
        with phone_operation_lock:
            if phone_sessions.authorize(token, pairing_code):
                phone_inbox.put(result)

    phone_app = create_phone_app(
        phone_sessions,
        lambda image: classify_normalized_image(image, retain_original=False),
        receive_phone_result,
    )
    phone_app.config["PHONE_REQUIRE_PAIRING_CODE"] = True
    phone_controller = phone_server_factory(phone_app)
    phone_monitor_lock = threading.Lock()
    phone_monitor_stop = None
    phone_monitor_thread = None

    def detach_phone_monitor():
        nonlocal phone_monitor_stop, phone_monitor_thread
        with phone_monitor_lock:
            monitor_stop = phone_monitor_stop
            monitor_thread = phone_monitor_thread
            phone_monitor_stop = None
            phone_monitor_thread = None
        if monitor_stop is not None:
            monitor_stop.set()
        return monitor_thread

    def stop_phone_capture_locked(*, clear_result):
        monitor_thread = detach_phone_monitor()
        error = None
        try:
            phone_sessions.stop()
        except BaseException as exc:
            error = exc
        if clear_result:
            phone_inbox.clear()
        try:
            phone_controller.stop()
        except BaseException as exc:
            if error is None:
                error = exc
        return monitor_thread, error

    def join_phone_monitor(monitor_thread):
        if (
            monitor_thread is not None
            and monitor_thread is not threading.current_thread()
        ):
            monitor_thread.join()

    def stop_phone_capture(*, clear_result=True):
        monitor_thread = None
        error = None
        with phone_operation_lock:
            monitor_thread, error = stop_phone_capture_locked(
                clear_result=clear_result
            )
        join_phone_monitor(monitor_thread)
        if error is not None:
            raise error

    def start_phone_monitor():
        nonlocal phone_monitor_stop, phone_monitor_thread
        monitor_stop = threading.Event()

        def monitor():
            nonlocal phone_monitor_stop, phone_monitor_thread
            while not monitor_stop.wait(phone_monitor_interval):
                if phone_sessions.active() is not None:
                    continue
                with phone_operation_lock:
                    with phone_monitor_lock:
                        if phone_monitor_stop is not monitor_stop:
                            return
                        phone_monitor_stop = None
                        phone_monitor_thread = None
                    phone_inbox.clear()
                    try:
                        phone_controller.stop()
                    except Exception:
                        app.logger.exception(
                            "expired phone capture listener did not close cleanly"
                        )
                    return

        with phone_monitor_lock:
            phone_monitor_stop = monitor_stop
            phone_monitor_thread = threading.Thread(
                target=monitor,
                name="ewaste-phone-expiry-monitor",
                daemon=True,
            )
            phone_monitor_thread.start()

    def session_payload(*, result=None):
        session = phone_sessions.active()
        if session is None:
            return {"active": False, "result": result}
        return {
            "active": True,
            "upload_url": session.upload_url,
            "pairing_code": session.pairing_code,
            "expires_in_seconds": max(0.0, session.expires_at - phone_clock()),
            "result": result,
        }

    def start_phone_capture(host):
        monitor_threads = []
        payload = None
        error = None
        with phone_operation_lock:
            old_monitor, stop_error = stop_phone_capture_locked(
                clear_result=True
            )
            monitor_threads.append(old_monitor)
            if stop_error is not None:
                error = stop_error
            else:
                try:
                    bound = phone_controller.start(host, port=0)
                    session = phone_sessions.start(
                        host=bound.host,
                        port=bound.port,
                    )
                    payload = session_payload(result=None)
                    payload["qr_png"] = _phone_qr_data_url(
                        session.upload_url
                    )
                    start_phone_monitor()
                except BaseException as exc:
                    error = exc
                    cleanup_monitor, _ = (
                        stop_phone_capture_locked(clear_result=True)
                    )
                    monitor_threads.append(cleanup_monitor)
        for monitor_thread in dict.fromkeys(monitor_threads):
            join_phone_monitor(monitor_thread)
        if error is not None:
            raise error
        return payload

    app.extensions["phone_app"] = phone_app
    app.extensions["phone_server_controller"] = phone_controller
    app.extensions["close_phone_capture"] = stop_phone_capture

    @app.get("/")
    def home():
        return send_from_directory(static_dir, "index.html")

    @app.get("/static/<filename>")
    def product_static(filename):
        if filename not in {"app.css", "app.js"}:
            return "", 404
        return send_from_directory(static_dir, filename)

    @app.get("/health")
    def health():
        engine = app.config["CLASSIFIER"]
        return jsonify({"model_loaded": True, "arch": engine.arch, "n_classes": len(engine.classes), "classes": engine.classes})

    @app.post("/api/v1/classify")
    def classify():
        image, error = read_image()
        if error:
            return error
        try:
            retain_original = request.form.get("retain_original", "").lower() in {
                "1", "true", "yes", "on"
            }
            result = classify_normalized_image(
                image,
                retain_original=retain_original,
            )
        except ImageTooLarge as exc:
            return jsonify({"error": str(exc)}), 413
        return jsonify(result)

    @app.post("/api/phone-session")
    def start_phone_session():
        host = lan_address_provider()
        if host is None:
            return (
                jsonify({
                    "error": (
                        "No usable local network address is available. Connect this Mac "
                        "and your phone to the same Wi-Fi network, then try again."
                    )
                }),
                503,
            )

        try:
            payload = start_phone_capture(host)
        except (OSError, RuntimeError, ValueError):
            app.logger.exception("phone capture session could not start")
            try:
                stop_phone_capture(clear_result=True)
            except Exception:
                app.logger.exception(
                    "phone capture startup cleanup did not complete cleanly"
                )
            return (
                jsonify({
                    "error": (
                        "Phone capture could not start on this network. Keep desktop "
                        "scanning open and check your Wi-Fi connection."
                    )
                }),
                503,
            )
        response = jsonify(payload)
        response.status_code = 201
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/phone-session")
    def get_phone_session():
        result = phone_inbox.pop()
        payload = session_payload(result=result)
        if not payload["active"] and phone_controller.is_running:
            stop_phone_capture(clear_result=False)
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.delete("/api/phone-session")
    def delete_phone_session():
        stop_phone_capture(clear_result=True)
        response = jsonify({"active": False, "result": None})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/v1/explain/<scan_id>")
    def explain(scan_id):
        sources = app.config["SOURCE_IMAGE_STORE"]
        active = sources.get_for_explanation(scan_id)
        if active is None:
            return jsonify({"error": "scan not found or explanation image expired"}), 404
        if not sources.try_acquire():
            return jsonify({"error": "an explanation is already in progress", "prediction_available": True}), 429
        image, class_index = active
        try:
            if class_index is None:
                class_index = int(np.asarray(app.config["CLASSIFIER"].probabilities_preprocessed(image)).argmax())
            values = occlusion_map(app.config["CLASSIFIER"], image, class_index, inference_crop=True)
        except Exception:
            app.logger.exception("explanation failed after classification")
            return jsonify({"error": "explanation unavailable", "prediction_available": True}), 503
        finally:
            sources.release()
        return jsonify({"scan_id": scan_id, "grid_size": int(values.shape[0]), "values": values.tolist(), "copy": "These are regions that influenced this result. They describe model behavior, not a physical diagnosis or detected component."})

    @app.get("/api/v1/history")
    def list_history():
        store = app.config["HISTORY_STORE"]
        return jsonify(store.list_scans() if store is not None else [])

    @app.get("/api/v1/reference/categories")
    def list_reference_categories():
        refs = reference()
        if refs is None:
            return assessment_error("component reference data is unavailable", 503)
        return jsonify(refs.list_categories())

    @app.get("/api/v1/reference/categories/<category_id>")
    def get_reference_category(category_id):
        refs = reference()
        if refs is None:
            return assessment_error("component reference data is unavailable", 503)
        try:
            return jsonify(refs.snapshot(category_id))
        except KeyError:
            return assessment_error("reference category not found", 404)

    @app.get("/api/v1/scans/<scan_id>/assessment")
    def get_assessment(scan_id):
        assessment, error = assessment_for(scan_id)
        return error if error is not None else jsonify(assessment)

    @app.put("/api/v1/scans/<scan_id>/assessment")
    def update_assessment(scan_id):
        assessment, error = assessment_for(scan_id)
        if error is not None:
            return error
        try:
            payload = validate_payload(request.get_json(silent=True))
        except OverflowError as exc:
            return assessment_error(str(exc), 422)
        except ValueError as exc:
            return assessment_error(str(exc), 400)
        store = app.config["HISTORY_STORE"]
        known_components = {component["component_id"] for component in assessment["template"]["components"]}
        unknown_components = set(payload["component_overrides"]) - known_components
        if unknown_components:
            return assessment_error("component override does not belong to the stored template", 400)
        updated = store.update_assessment(
            scan_id,
            {key: value for key, value in payload.items() if key != "component_overrides"},
            payload["component_overrides"],
            computed_components(assessment["template"], payload),
        )
        return jsonify(updated)

    @app.get("/api/v1/history/<scan_id>")
    def get_history(scan_id):
        store = app.config["HISTORY_STORE"]
        record = store.get_scan(scan_id) if store is not None else None
        return jsonify(record) if record is not None else (jsonify({"error": "scan not found"}), 404)

    @app.put("/api/v1/history/<scan_id>/confirmation")
    def confirm_history(scan_id):
        payload = request.get_json(silent=True) or {}
        accepted = payload.get("accepted_class_name")
        store = app.config["HISTORY_STORE"]
        if not isinstance(accepted, str) or store is None:
            return jsonify({"error": "accepted category was not offered by the model"}), 400
        refs = reference()
        known_category_ids = None
        if refs is not None:
            try:
                known_category_ids = {
                    category["category_id"] for category in refs.list_categories()
                }
            except (sqlite3.Error, ValueError, RuntimeError, KeyError, TypeError):
                return assessment_error("component reference data is unavailable", 503)
        try:
            record = store.set_confirmation(
                scan_id,
                accepted,
                known_category_ids=known_category_ids,
            )
        except AssessmentConflictError:
            return jsonify({"error": "an existing assessment keeps its confirmed category"}), 409
        if record is None:
            return jsonify({"error": "scan not found"}), 404
        if record is False:
            message = (
                "accepted category is not available in component references"
                if known_category_ids is not None
                else "accepted category was not offered by the model"
            )
            return jsonify({"error": message}), 400
        return jsonify(record)

    @app.delete("/api/v1/history/<scan_id>")
    def delete_history(scan_id):
        store = app.config["HISTORY_STORE"]
        if store is None or not store.delete_scan(scan_id):
            return jsonify({"error": "scan not found"}), 404
        app.config["SOURCE_IMAGE_STORE"].remove(scan_id)
        return jsonify({"deleted": True})

    @app.delete("/api/v1/history")
    def clear_history():
        store = app.config["HISTORY_STORE"]
        deleted_count = store.clear() if store is not None else 0
        app.config["SOURCE_IMAGE_STORE"].clear()
        return jsonify({"deleted_count": deleted_count})

    return app
