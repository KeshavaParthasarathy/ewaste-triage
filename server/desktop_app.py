"""Product-only Flask factory for the packaged desktop application."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping

import numpy as np
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from PIL import Image, UnidentifiedImageError

from server.explanations import ActiveSourceImageStore, occlusion_map
from server.imaging import ImageTooLarge, inference_crop, normalize_image
from server.lifecycle import AssessmentInputs, Condition, OperationalState, Range, Usage, assess_component


MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def create_desktop_app(
    *,
    classifier,
    history_store=None,
    static_dir: Path | None = None,
    source_image_store=None,
    clock=None,
    reference_store=None,
    lifecycle_assessor=assess_component,
):
    """Build the user product without collection or valuation dependencies."""
    static_dir = Path(static_dir or Path(__file__).parent / "static")
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
        if minimum < 0 or maximum < minimum or maximum > 1_000_000:
            raise OverflowError(f"{name} bounds are reversed or outside accepted bounds")
        return {"minimum": minimum, "maximum": maximum}

    def validate_payload(payload):
        if not isinstance(payload, Mapping):
            raise ValueError("assessment payload must be an object")
        allowed = {"age_months", "cycle_count", "usage", "condition", "operational", "component_overrides"}
        if set(payload) - allowed:
            raise ValueError("assessment payload contains unsupported fields")
        result = {}
        for name, enum in (("usage", Usage), ("condition", Condition), ("operational", OperationalState)):
            value = payload.get(name, getattr(enum, "UNKNOWN").value)
            try:
                result[name] = enum(value).value
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid {name}") from exc
        for name in ("age_months", "cycle_count"):
            if name in payload and payload[name] is not None:
                result[name] = validate_range(payload[name], name)
            else:
                result[name] = None
        overrides = payload.get("component_overrides", {})
        if not isinstance(overrides, Mapping):
            raise ValueError("component_overrides must be an object")
        clean_overrides = {}
        allowed_override = {"presence_label", "condition", "operational", "lifecycle", "safety_sensitive"}
        for component_id, override in overrides.items():
            if not isinstance(component_id, str) or not component_id or not isinstance(override, Mapping):
                raise ValueError("component overrides must use component IDs and object values")
            if set(override) - allowed_override:
                raise ValueError("component override contains unsupported fields")
            clean = dict(override)
            if "presence_label" in clean and clean["presence_label"] not in {"standard", "common", "optional", "unknown"}:
                raise ValueError("invalid component presence_label")
            for name, enum in (("condition", Condition), ("operational", OperationalState)):
                if name in clean:
                    try:
                        clean[name] = enum(clean[name]).value
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"invalid component {name}") from exc
            if "safety_sensitive" in clean and type(clean["safety_sensitive"]) is not bool:
                raise ValueError("component safety_sensitive must be boolean")
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
        refs = reference()
        if refs is None:
            return None, assessment_error("component reference data is unavailable", 503)
        category_id = confirmation["accepted_class_name"]
        try:
            template = refs.snapshot(category_id)
        except KeyError:
            return None, assessment_error("no component template is available for the confirmed category", 404)
        assessment = store.create_assessment(scan_id, template)
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
            result = app.config["CLASSIFIER"].classify(image)
        except ImageTooLarge as exc:
            return jsonify({"error": str(exc)}), 413
        scan_id = None
        store = app.config["HISTORY_STORE"]
        if store is not None:
            retain_original = request.form.get("retain_original", "").lower() in {"1", "true", "yes", "on"}
            try:
                scan_id = store.add_scan(result, image, retain_original=retain_original, original=image if retain_original else None)
            except Exception:
                app.logger.exception("classification succeeded but history persistence failed")
                result["history_error"] = "Classification complete, but this scan was not saved to history."
        result["scan_id"] = scan_id
        if scan_id is not None:
            classes = getattr(app.config["CLASSIFIER"], "classes", None)
            class_index = classes.index(result["class_name"]) if classes is not None else None
            app.config["SOURCE_IMAGE_STORE"].put(scan_id, inference_crop(image), class_index=class_index)
        return jsonify(result)

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
        record = store.set_confirmation(scan_id, accepted)
        if record is None:
            return jsonify({"error": "scan not found"}), 404
        if record is False:
            return jsonify({"error": "accepted category was not offered by the model"}), 400
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
