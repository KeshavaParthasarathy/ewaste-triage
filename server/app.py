"""
Laptop-hosted triage server. The phone reaches this over its own Personal Hotspot.

    .venv/bin/python -m server.app

Run it under `caffeinate -i` so the laptop does not sleep mid-demo.
"""
import argparse
import pathlib
import re

from flask import Flask, jsonify, request, send_from_directory
from PIL import Image, UnidentifiedImageError

from scripts import valuation
from scripts.photo_classes import PHOTO_CLASS_SPECS
from server.classifier import Classifier
from server.imaging import ImageTooLarge, normalize_image
from server.netinfo import print_access_urls

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Must start alphanumeric: a bare ".." matches "^[A-Za-z0-9_.-]+$" and escapes one level.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# The dataset splitter uses the first underscore as the boundary between the
# physical device ID and photo number, so an ID itself cannot contain one.
SAFE_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


def create_app(ckpt_path=None, ingest_root=None, demo_dir=None, collection_only=False,
               classifier=None, history_store=None):
    app = Flask(__name__, static_folder=str(ROOT / "server" / "static"))
    ckpt_path = pathlib.Path(ckpt_path or ROOT / "models" / "best.pt")
    ingest_root = pathlib.Path(ingest_root or ROOT / "data" / "photos" / "raw")

    # Collection must work before the first model has been trained. Normal demo mode
    # still fails loudly at boot if its checkpoint is missing.
    app.config["CLASSIFIER"] = (
        None if collection_only
        else classifier if classifier is not None
        else Classifier(ckpt_path)
    )
    app.config["HISTORY_STORE"] = history_store
    app.config["COLLECTION_ONLY"] = collection_only
    app.config["INGEST_ROOT"] = ingest_root

    def _read_image():
        if "image" not in request.files:
            return None, (jsonify({"error": "no file field named 'image'"}), 400)
        try:
            image = Image.open(request.files["image"].stream)
            return normalize_image(image), None
        except ImageTooLarge as exc:
            return None, (jsonify({"error": str(exc)}), 413)
        except Image.DecompressionBombError:
            return None, (jsonify({"error": "image exceeds 40,000,000 pixels"}), 413)
        except (UnidentifiedImageError, OSError):
            return None, (jsonify({"error": "uploaded file is not a decodable image"}), 400)

    def _classification_result(image):
        result = app.config["CLASSIFIER"].classify(image)
        mass_g = request.form.get("mass_g", type=float)

        if result["low_confidence"]:
            result["advice"] = "Low confidence — route this device to manual teardown."
            return result, image

        if result["unu_key"] is None:
            result["advice"] = "Class name has no 4-digit UNU-KEY prefix; cannot estimate value."
            return result, image

        try:
            result["valuation"] = valuation.estimate(result["unu_key"], mass_g=mass_g)
        except valuation.CompositionUnavailable:
            result["advice"] = "Composition table not filled in — class only, no value estimate."
        except valuation.UnknownKey as exc:
            result["advice"] = str(exc)
        return result, image

    @app.get("/")
    def home():
        page = "collect.html" if app.config["COLLECTION_ONLY"] else "index.html"
        return send_from_directory(app.static_folder, page)

    @app.get("/collect")
    def collect():
        return send_from_directory(app.static_folder, "collect.html")

    @app.get("/collection-classes")
    def collection_classes():
        return jsonify({"classes": [
            {"value": class_name, "label": spec["label"]}
            for class_name, spec in PHOTO_CLASS_SPECS.items()
        ]})

    @app.get("/health")
    def health():
        c = app.config["CLASSIFIER"]
        if c is None:
            return jsonify({"model_loaded": False, "classes": [], "collection_only": True})
        return jsonify({"model_loaded": True, "arch": c.arch, "n_classes": len(c.classes),
                        "classes": c.classes})

    @app.post("/classify")
    def classify():
        if app.config["CLASSIFIER"] is None:
            return jsonify({"error": "classification unavailable in collection mode"}), 503
        img, err = _read_image()
        if err:
            return err

        try:
            result, _ = _classification_result(img)
        except ImageTooLarge as exc:
            return jsonify({"error": str(exc)}), 413
        return jsonify(result)

    @app.post("/api/v1/classify")
    def desktop_classify():
        if app.config["CLASSIFIER"] is None:
            return jsonify({"error": "classification unavailable in collection mode"}), 503
        image, err = _read_image()
        if err:
            return err
        try:
            result, normalized = _classification_result(image)
        except ImageTooLarge as exc:
            return jsonify({"error": str(exc)}), 413

        scan_id = None
        store = app.config["HISTORY_STORE"]
        if store is not None:
            retain_original = request.form.get("retain_original", "").lower() in {
                "1", "true", "yes", "on"
            }
            try:
                scan_id = store.add_scan(
                    result,
                    normalized,
                    retain_original=retain_original,
                    original=normalized if retain_original else None,
                )
            except Exception:
                app.logger.exception("classification succeeded but history persistence failed")
                result["history_error"] = (
                    "Classification complete, but this scan was not saved to history."
                )
        result["scan_id"] = scan_id
        return jsonify(result)

    @app.get("/api/v1/history")
    def list_history():
        store = app.config["HISTORY_STORE"]
        return jsonify(store.list_scans() if store is not None else [])

    @app.get("/api/v1/history/<scan_id>")
    def get_history(scan_id):
        store = app.config["HISTORY_STORE"]
        record = store.get_scan(scan_id) if store is not None else None
        if record is None:
            return jsonify({"error": "scan not found"}), 404
        return jsonify(record)

    @app.delete("/api/v1/history/<scan_id>")
    def delete_history(scan_id):
        store = app.config["HISTORY_STORE"]
        deleted = store.delete_scan(scan_id) if store is not None else False
        if not deleted:
            return jsonify({"error": "scan not found"}), 404
        return jsonify({"deleted": True})

    @app.delete("/api/v1/history")
    def clear_history():
        store = app.config["HISTORY_STORE"]
        return jsonify({"deleted_count": store.clear() if store is not None else 0})

    @app.post("/ingest")
    def ingest():
        class_name = request.form.get("class_name", "")
        device_id = request.form.get("device_id", "")
        if class_name not in PHOTO_CLASS_SPECS:
            return jsonify({"error": "class_name is not one of the five approved classes"}), 400
        if not SAFE_NAME.match(class_name):
            return jsonify({"error": "class_name must start alphanumeric and contain only letters, numbers, _, ., or -"}), 400
        if not SAFE_DEVICE_ID.match(device_id):
            return jsonify({"error": "device_id must start alphanumeric and cannot contain an underscore"}), 400

        img, err = _read_image()
        if err:
            return err

        try:
            normalized = normalize_image(img)
        except ImageTooLarge as exc:
            return jsonify({"error": str(exc)}), 413

        root = app.config["INGEST_ROOT"].resolve()
        out_dir = (root / class_name).resolve()
        # Defence in depth: the regex should already prevent this, but this writes to
        # disk, so confirm the resolved path really is inside the ingest root.
        if not out_dir.is_relative_to(root):
            return jsonify({"error": "resolved path escapes the ingest root"}), 400
        out_dir.mkdir(parents=True, exist_ok=True)
        existing = list(out_dir.glob(f"{device_id}_*.jpg"))
        suffix = re.compile(rf"^{re.escape(device_id)}_(\d+)\.jpg$")
        numbers = [int(match.group(1)) for path in existing
                   if (match := suffix.fullmatch(path.name))]
        next_number = max(numbers, default=-1) + 1
        # Always re-encode to JPEG: torchvision's ImageFolder silently drops .heic files.
        path = out_dir / f"{device_id}_{next_number:03d}.jpg"
        normalized.save(path, format="JPEG", quality=92)
        return jsonify({"saved": str(path.relative_to(root)),
                        "device_photo_count": len(existing) + 1})

    @app.get("/demo")
    def demo():
        """Replay pre-shot photos through the real /classify path. Fair-day insurance."""
        d = pathlib.Path(demo_dir or ROOT / "data" / "demo_photos")
        shots = sorted(p.name for p in d.glob("*.jpg")) if d.exists() else []
        return jsonify({"demo_photos": shots, "count": len(shots),
                        "hint": "POST one of these back to /classify to rehearse without the phone."})

    return app


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--ingest-root", default=None,
                    help="collection output root (for example data/photos/holdout_own)")
    ap.add_argument("--collect", action="store_true",
                    help="collect labeled training photos without loading a model")
    ap.add_argument("--demo", action="store_true",
                    help="list the pre-shot fallback photos and exit")
    a = ap.parse_args(argv)
    if a.demo:
        d = ROOT / "data" / "demo_photos"
        shots = sorted(d.glob("*.jpg")) if d.exists() else []
        print(f"{len(shots)} demo photos in {d}")
        for s in shots:
            print(f"  {s.name}")
        if not shots:
            print("  none — shoot 10-15 before the fair, see data/demo_photos/README.md")
        return
    print_access_urls(a.port)
    app = create_app(ckpt_path=a.ckpt, ingest_root=a.ingest_root,
                     collection_only=a.collect)
    # Bind IPv6: an IPv6-only carrier gives no usable IPv4 hotspot address.
    app.run(host="::", port=a.port, threaded=False)


if __name__ == "__main__":
    main()
