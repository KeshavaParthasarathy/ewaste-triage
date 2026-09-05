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
from server.netinfo import print_access_urls

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Must start alphanumeric: a bare ".." matches "^[A-Za-z0-9_.-]+$" and escapes one level.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# The dataset splitter uses the first underscore as the boundary between the
# physical device ID and photo number, so an ID itself cannot contain one.
SAFE_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


def create_app(ckpt_path=None, ingest_root=None, demo_dir=None, collection_only=False):
    app = Flask(__name__, static_folder=str(ROOT / "server" / "static"))
    ckpt_path = pathlib.Path(ckpt_path or ROOT / "models" / "best.pt")
    ingest_root = pathlib.Path(ingest_root or ROOT / "data" / "photos" / "raw")

    # Collection must work before the first model has been trained. Normal demo mode
    # still fails loudly at boot if its checkpoint is missing.
    app.config["CLASSIFIER"] = None if collection_only else Classifier(ckpt_path)
    app.config["COLLECTION_ONLY"] = collection_only
    app.config["INGEST_ROOT"] = ingest_root

    def _read_image():
        if "image" not in request.files:
            return None, (jsonify({"error": "no file field named 'image'"}), 400)
        try:
            return Image.open(request.files["image"].stream), None
        except (UnidentifiedImageError, OSError):
            return None, (jsonify({"error": "uploaded file is not a decodable image"}), 400)

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

        result = app.config["CLASSIFIER"].classify(img)
        mass_g = request.form.get("mass_g", type=float)

        if result["low_confidence"]:
            result["advice"] = "Low confidence — route this device to manual teardown."
            return jsonify(result)

        if result["unu_key"] is None:
            result["advice"] = "Class name has no 4-digit UNU-KEY prefix; cannot estimate value."
            return jsonify(result)

        try:
            result["valuation"] = valuation.estimate(result["unu_key"], mass_g=mass_g)
        except valuation.CompositionUnavailable:
            result["advice"] = "Composition table not filled in — class only, no value estimate."
        except valuation.UnknownKey as e:
            result["advice"] = str(e)
        return jsonify(result)

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
        img.convert("RGB").save(path, format="JPEG", quality=92)
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
