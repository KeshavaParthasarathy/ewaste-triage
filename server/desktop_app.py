"""Product-only Flask factory for the packaged desktop application."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from PIL import Image, UnidentifiedImageError

from server.explanations import ActiveSourceImageStore, occlusion_map
from server.imaging import ImageTooLarge, inference_crop, normalize_image


MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def create_desktop_app(
    *,
    classifier,
    history_store=None,
    static_dir: Path | None = None,
    source_image_store=None,
    clock=None,
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
    )

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
