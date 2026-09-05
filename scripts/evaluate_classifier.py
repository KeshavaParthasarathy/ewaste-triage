"""Evaluate a frozen image classifier on labeled folders and explain predictions.

The parent directory of each image is its ground-truth class. The command writes a
browser-friendly report, per-photo CSV, JSON metrics, a confusion matrix, and Grad-CAM
overlays showing which parts of the model input most influenced each prediction.

    .venv/bin/python -m scripts.evaluate_classifier \
      --data-dir data/photos/holdout_own \
      --checkpoint models/best.pt \
      --out reports/holdout-evaluation
"""

import argparse
import csv
import hashlib
import html
import json
import pathlib
from datetime import datetime, timezone

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from server.classifier import _build
from server.imaging import preprocess_array, preprocess_image


ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def scan_labeled_images(data_dir, classes):
    """Return images whose parent folder supplies the known correct class."""
    data_dir = pathlib.Path(data_dir)
    if not data_dir.is_dir():
        raise ValueError(f"labeled data directory does not exist: {data_dir}")
    class_to_index = {name: index for index, name in enumerate(classes)}
    samples = []
    for class_dir in sorted(path for path in data_dir.iterdir() if path.is_dir()):
        files = sorted(
            path for path in class_dir.iterdir()
            if path.is_file() and not path.name.startswith(".")
        )
        if not files:
            continue
        if class_dir.name not in class_to_index:
            raise ValueError(
                f"labeled folder {class_dir.name!r} is not one of the model classes: {classes}"
            )
        unsupported = [path for path in files if path.suffix.lower() not in IMAGE_EXTENSIONS]
        if unsupported:
            names = ", ".join(path.name for path in unsupported)
            raise ValueError(
                f"unsupported files in labeled folder {class_dir.name!r}: {names}. "
                "Convert every test photo to JPEG, PNG, or WebP before evaluation."
            )
        for path in files:
            samples.append({
                "path": path,
                "true_class": class_dir.name,
                "true_index": class_to_index[class_dir.name],
            })
    if not samples:
        raise ValueError(f"no supported images found in labeled folders under {data_dir}")
    return samples


def compute_metrics(rows, classes):
    """Compute literal accuracy, per-class metrics, and a fixed-order matrix."""
    if not rows:
        raise ValueError("cannot compute evaluation metrics without predictions")
    labels = list(range(len(classes)))
    y_true = [int(row["true_index"]) for row in rows]
    y_pred = [int(row["predicted_index"]) for row in rows]
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )
    present = [index for index, count in enumerate(support) if count]
    per_class = {}
    for index, class_name in enumerate(classes):
        count = int(support[index])
        correct = int(matrix[index, index])
        per_class[class_name] = {
            "support": count,
            "correct": correct,
            "accuracy": correct / count if count else None,
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(f1[index]),
        }
    correct = sum(int(true == predicted) for true, predicted in zip(y_true, y_pred))
    return {
        "total": len(rows),
        "correct": correct,
        "overall_accuracy": correct / len(rows),
        "macro_f1_present": float(np.mean(f1[present])) if present else 0.0,
        "per_class": per_class,
        "confusion_matrix": matrix.astype(int).tolist(),
    }


def gradcam(model, target_layer, image_tensor, class_index):
    """Return a normalized Grad-CAM map for one image and one predicted class."""
    captured = {}

    def capture_activation(_module, _inputs, output):
        captured["activation"] = output
        output.retain_grad()

    handle = target_layer.register_forward_hook(capture_activation)
    try:
        model.zero_grad(set_to_none=True)
        logits = model(image_tensor)
        logits[0, class_index].backward()
        activation = captured.get("activation")
        if activation is None or activation.grad is None:
            raise RuntimeError("the selected model layer did not produce Grad-CAM gradients")
        weights = activation.grad.mean(dim=(2, 3), keepdim=True)
        cam = torch.relu((weights * activation).sum(dim=1))[0]
        cam = cam.detach().cpu().numpy().astype(np.float32)
        low, high = float(cam.min()), float(cam.max())
        if high > low:
            cam = (cam - low) / (high - low)
        else:
            cam = np.zeros_like(cam)
        return cam
    finally:
        handle.remove()


def overlay_cam(image, cam):
    """Overlay a red-to-yellow influence map on the exact crop seen by the model."""
    image = image.convert("RGB")
    resized = Image.fromarray(np.uint8(np.clip(cam, 0, 1) * 255), mode="L").resize(
        image.size, Image.Resampling.BILINEAR
    )
    strength = np.asarray(resized, dtype=np.float32) / 255.0
    base = np.asarray(image, dtype=np.float32)
    heat = np.zeros_like(base)
    heat[..., 0] = 255
    heat[..., 1] = np.clip((strength - 0.45) / 0.55, 0, 1) * 210
    alpha = (strength * 0.62)[..., None]
    blended = base * (1 - alpha) + heat * alpha
    return Image.fromarray(np.uint8(np.clip(blended, 0, 255)), mode="RGB")


def _target_layer(model, arch):
    if arch in {"resnet18", "resnet50"}:
        return model.layer4[-1]
    if arch in {"efficientnet_b0", "mobilenet_v3_small"}:
        return model.features[-1]
    raise ValueError(f"Grad-CAM is not configured for architecture {arch!r}")


def _friendly(class_name):
    parts = class_name.split("_", 1)
    return (parts[1] if len(parts) == 2 else parts[0]).replace("_", " ").title()


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _matrix_column_label(class_name):
    return "\n".join(_friendly(class_name).split())


def _write_confusion_matrix(path, classes, matrix):
    labels = [_friendly(name) for name in classes]
    cell = 140
    left = 190
    top = 120
    width = left + cell * len(classes) + 24
    height = top + cell * len(classes) + 40
    canvas = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(canvas)
    title_font, label_font, value_font = _font(24), _font(16), _font(24)
    draw.text((20, 18), "Confusion matrix", fill="white", font=title_font)
    draw.text((20, 58), "Rows: actual     Columns: predicted", fill="#9ca3af", font=label_font)
    max_value = max((max(row) for row in matrix), default=1) or 1
    for index, label in enumerate(labels):
        draw.multiline_text(
            (left + index * cell + cell / 2, top - 55),
            _matrix_column_label(classes[index]),
            fill="#d1d5db",
            font=label_font,
            anchor="ma",
            align="center",
            spacing=2,
        )
        draw.text((14, top + index * cell + 42), label[:18], fill="#d1d5db", font=label_font)
    for row_index, row in enumerate(matrix):
        for col_index, value in enumerate(row):
            ratio = value / max_value
            color = (
                int(31 + 28 * ratio),
                int(41 + 89 * ratio),
                int(55 + 191 * ratio),
            )
            x = left + col_index * cell
            y = top + row_index * cell
            draw.rounded_rectangle((x + 3, y + 3, x + cell - 3, y + cell - 3), 10, fill=color)
            text = str(value)
            box = draw.textbbox((0, 0), text, font=value_font)
            draw.text(
                (x + (cell - (box[2] - box[0])) / 2, y + (cell - (box[3] - box[1])) / 2),
                text,
                fill="white",
                font=value_font,
            )
    canvas.save(path)


def write_report(out_dir, rows, metrics, classes, model_info):
    """Write HTML, CSV, JSON, and confusion-matrix evaluation artifacts."""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_confusion_matrix(
        out_dir / "confusion_matrix.png", classes, metrics["confusion_matrix"]
    )

    csv_fields = [
        "filename", "actual", "predicted", "confidence", "correct", "top_three"
    ]
    with (out_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "filename": pathlib.Path(row["source_path"]).name,
                "actual": row["true_class"],
                "predicted": row["predicted_class"],
                "confidence": f'{row["confidence"]:.6f}',
                "correct": row["correct"],
                "top_three": "; ".join(
                    f'{item["class_name"]}:{item["confidence"]:.4f}'
                    for item in row["topk"]
                ),
            })

    public_rows = [
        {key: value for key, value in row.items() if key not in {"true_index", "predicted_index"}}
        for row in rows
    ]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model_info,
        "classes": classes,
        "metrics": metrics,
        "predictions": public_rows,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    class_rows = []
    for class_name in classes:
        result = metrics["per_class"][class_name]
        accuracy = "Not tested" if result["accuracy"] is None else f'{result["accuracy"]:.1%}'
        class_rows.append(
            "<tr>"
            f"<td>{html.escape(_friendly(class_name))}</td>"
            f'<td class="mono">{html.escape(class_name)}</td>'
            f'<td>{result["support"]}</td><td>{accuracy}</td>'
            f'<td>{result.get("precision", 0):.1%}</td>'
            f'<td>{result.get("recall", 0):.1%}</td>'
            f'<td>{result.get("f1", 0):.1%}</td>'
            "</tr>"
        )

    cards = []
    for row in rows:
        status = "Correct" if row["correct"] else "Incorrect"
        status_class = "correct" if row["correct"] else "incorrect"
        topk = "".join(
            f'<li><span>{html.escape(_friendly(item["class_name"]))}</span>'
            f'<strong>{item["confidence"]:.1%}</strong></li>'
            for item in row["topk"]
        )
        cards.append(f"""
        <article class="prediction {status_class}">
          <div class="images">
            <figure><img src="{html.escape(row['model_input'])}" alt="Model input"><figcaption>What the model saw</figcaption></figure>
            <figure><img src="{html.escape(row['heatmap'])}" alt="Grad-CAM influence map"><figcaption>Influential regions</figcaption></figure>
          </div>
          <div class="result">
            <div class="status">{status}</div>
            <h3>{html.escape(pathlib.Path(row['source_path']).name)}</h3>
            <p>Actual: <strong>{html.escape(_friendly(row['true_class']))}</strong></p>
            <p>Predicted: <strong>{html.escape(_friendly(row['predicted_class']))}</strong></p>
            <p class="confidence">Confidence {row['confidence']:.1%}</p>
            <ol>{topk}</ol>
          </div>
        </article>""")

    overall = metrics["overall_accuracy"]
    report_html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>E-Waste Model Evaluation</title>
<style>
:root{{--bg:#08111f;--panel:#111c2e;--panel2:#17253b;--text:#edf3fb;--muted:#9dafc4;--line:#263952;--green:#34d399;--red:#fb7185;--blue:#60a5fa}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(135deg,#08111f,#0d1727 45%,#08111f);color:var(--text);font:16px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}
main{{width:min(1180px,calc(100% - 32px));margin:auto;padding:42px 0 80px}} h1{{font-size:clamp(2rem,6vw,4.5rem);line-height:1;margin:.2em 0}} h2{{margin-top:48px}} .eyebrow{{color:var(--blue);font-weight:700;text-transform:uppercase;letter-spacing:.14em}} .sub{{color:var(--muted);max-width:780px}} .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:30px 0}} .metric,.panel,.prediction{{background:rgba(17,28,46,.88);border:1px solid var(--line);border-radius:18px;box-shadow:0 18px 60px #0004}} .metric{{padding:20px}} .metric strong{{display:block;font-size:2rem}} .metric span{{color:var(--muted)}} .panel{{padding:20px;overflow:auto}} table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:12px;border-bottom:1px solid var(--line)}} th{{color:var(--muted)}} .mono{{font:13px ui-monospace,SFMono-Regular,monospace;color:var(--muted)}} .matrix{{display:block;max-width:100%;height:auto;margin:auto;border-radius:12px}} .notice{{border-left:4px solid var(--blue);padding:14px 18px;background:#101f35;color:#c5d4e6;border-radius:0 12px 12px 0}} .gallery{{display:grid;gap:18px}} .prediction{{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(260px,.7fr);overflow:hidden}} .images{{display:grid;grid-template-columns:1fr 1fr;background:#050a12}} figure{{margin:0}} figure img{{display:block;width:100%;aspect-ratio:1;object-fit:cover}} figcaption{{padding:8px 12px;color:var(--muted);font-size:.85rem}} .result{{padding:22px}} .status{{display:inline-block;border-radius:999px;padding:5px 10px;font-weight:800;background:#263449}} .correct .status{{color:var(--green)}} .incorrect .status{{color:var(--red)}} .prediction.correct{{border-color:#185744}} .prediction.incorrect{{border-color:#743145}} h3{{margin:.8em 0 .4em;overflow-wrap:anywhere}} .result p{{margin:.3em 0}} .confidence{{color:var(--blue)}} ol{{list-style:none;padding:0;margin:18px 0 0}} li{{display:flex;justify-content:space-between;border-top:1px solid var(--line);padding:8px 0}} @media(max-width:760px){{.prediction{{grid-template-columns:1fr}}}}
</style></head><body><main>
<div class="eyebrow">Frozen-model test</div><h1>Model evaluation</h1>
<p class="sub">Predictions are compared with labels supplied by the parent folders. The checkpoint was not retrained on these holdout devices.</p>
<section class="metrics"><div class="metric"><strong>{overall:.1%}</strong><span>Overall accuracy</span></div><div class="metric"><strong>{metrics['correct']} / {metrics['total']}</strong><span>Correct predictions</span></div><div class="metric"><strong>{metrics['macro_f1_present']:.1%}</strong><span>Macro F1, tested classes</span></div><div class="metric"><strong>{html.escape(str(model_info.get('arch','unknown')))}</strong><span>Model architecture</span></div></section>
<div class="notice"><strong>How to read the heatmaps:</strong> warm areas contributed most to the predicted class. Grad-CAM shows model influence, not a human-readable proof or guarantee of why a decision was made.</div>
<h2>Category results</h2><div class="panel"><table><thead><tr><th>Category</th><th>Model label</th><th>Photos</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{''.join(class_rows)}</tbody></table></div>
<h2>Confusion matrix</h2><div class="panel"><img class="matrix" src="confusion_matrix.png" alt="Confusion matrix"></div>
<h2>Every prediction</h2><div class="gallery">{''.join(cards)}</div>
</main></body></html>"""
    (out_dir / "index.html").write_text(report_html, encoding="utf-8")


def evaluate_folder(data_dir, checkpoint, out_dir):
    """Run a frozen checkpoint against labeled folders and create its report."""
    data_dir = pathlib.Path(data_dir)
    checkpoint = pathlib.Path(checkpoint)
    out_dir = pathlib.Path(out_dir)
    if not checkpoint.is_file():
        raise FileNotFoundError(f"model checkpoint does not exist: {checkpoint}")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"refusing to mix results into non-empty output directory: {out_dir}")

    torch.set_num_threads(1)
    saved = torch.load(checkpoint, map_location="cpu")
    classes = list(saved["classes"])
    arch = saved.get("arch", "resnet18")
    model = _build(arch, len(classes))
    model.load_state_dict(saved["state_dict"])
    model.eval()
    target_layer = _target_layer(model, arch)
    samples = scan_labeled_images(data_dir, classes)

    images_dir = out_dir / "images"
    heatmaps_dir = out_dir / "heatmaps"
    images_dir.mkdir(parents=True, exist_ok=True)
    heatmaps_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for number, sample in enumerate(samples, start=1):
        with Image.open(sample["path"]) as opened:
            model_input = preprocess_image(opened)
            tensor = torch.from_numpy(preprocess_array(opened))
        with torch.no_grad():
            probabilities = torch.softmax(model(tensor), dim=1)[0]
        count = min(3, len(classes))
        top_confidence, top_indices = probabilities.topk(count)
        predicted_index = int(top_indices[0])
        confidence = float(top_confidence[0])
        cam = gradcam(model, target_layer, tensor, predicted_index)

        stem = f"{number:03d}_{sample['path'].stem}"
        model_input_relative = pathlib.Path("images") / f"{stem}.jpg"
        heatmap_relative = pathlib.Path("heatmaps") / f"{stem}.jpg"
        model_input.save(out_dir / model_input_relative, "JPEG", quality=90)
        overlay_cam(model_input, cam).save(out_dir / heatmap_relative, "JPEG", quality=90)
        row = {
            "source_path": str(sample["path"].resolve()),
            "true_class": sample["true_class"],
            "true_index": sample["true_index"],
            "predicted_class": classes[predicted_index],
            "predicted_index": predicted_index,
            "confidence": confidence,
            "correct": predicted_index == sample["true_index"],
            "topk": [
                {"class_name": classes[int(index)], "confidence": float(probability)}
                for probability, index in zip(top_confidence, top_indices)
            ],
            "model_input": str(model_input_relative),
            "heatmap": str(heatmap_relative),
        }
        rows.append(row)
        mark = "correct" if row["correct"] else "WRONG"
        print(
            f"[{number:>3}/{len(samples)}] {sample['path'].name}: "
            f"{_friendly(row['predicted_class'])} {confidence:.1%} ({mark})"
        )

    metrics = compute_metrics(rows, classes)
    model_info = {
        "checkpoint": str(checkpoint.resolve()),
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "arch": arch,
        "training_config": saved.get("config"),
        "best_validation_accuracy": saved.get("best_val_accuracy"),
    }
    write_report(out_dir, rows, metrics, classes, model_info)
    print(
        f"\naccuracy={metrics['overall_accuracy']:.3f} "
        f"({metrics['correct']}/{metrics['total']})  "
        f"macro_f1={metrics['macro_f1_present']:.3f}"
    )
    print(f"report: {out_dir.resolve() / 'index.html'}")
    return {"rows": rows, "metrics": metrics, "model": model_info}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "data" / "photos" / "holdout_own"))
    parser.add_argument("--checkpoint", default=str(ROOT / "models" / "best.pt"))
    parser.add_argument("--out", required=True, help="new or empty directory for the report")
    args = parser.parse_args(argv)
    evaluate_folder(args.data_dir, args.checkpoint, args.out)


if __name__ == "__main__":
    main()
