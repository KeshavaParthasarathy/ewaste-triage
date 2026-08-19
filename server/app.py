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
from server.classifier import Classifier

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def create_app(ckpt_path=None, ingest_root=None):
    app = Flask(__name__, static_folder=str(ROOT / "server" / "static"))
    ckpt_path = pathlib.Path(ckpt_path or ROOT / "models" / "best.pt")
    ingest_root = pathlib.Path(ingest_root or ROOT / "data" / "photos" / "raw")

    # Fail loudly at boot, not on the first request in front of a judge.
    app.config["CLASSIFIER"] = Classifier(ckpt_path)
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
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def health():
        c = app.config["CLASSIFIER"]
        return jsonify({"model_loaded": True, "arch": c.arch, "n_classes": len(c.classes),
                        "classes": c.classes})

    @app.post("/classify")
    def classify():
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
        if not SAFE_NAME.match(class_name) or not SAFE_NAME.match(device_id):
            return jsonify({"error": "class_name and device_id must match [A-Za-z0-9_.-]+"}), 400

        img, err = _read_image()
        if err:
            return err

        out_dir = app.config["INGEST_ROOT"] / class_name
        out_dir.mkdir(parents=True, exist_ok=True)
        n = len(list(out_dir.glob(f"{device_id}_*.jpg")))
        # Always re-encode to JPEG: torchvision's ImageFolder silently drops .heic files.
        path = out_dir / f"{device_id}_{n:03d}.jpg"
        img.convert("RGB").save(path, format="JPEG", quality=92)
        return jsonify({"saved": str(path.relative_to(app.config["INGEST_ROOT"])),
                        "device_photo_count": n + 1})

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--ckpt", default=None)
    a = ap.parse_args()
    app = create_app(ckpt_path=a.ckpt)
    # Bind IPv6: an IPv6-only carrier gives no usable IPv4 hotspot address.
    # (Address discovery / QR printing lands here in a later task.)
    app.run(host="::", port=a.port, threaded=False)


if __name__ == "__main__":
    main()
