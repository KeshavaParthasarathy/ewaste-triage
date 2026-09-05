"""
One photo -> device category -> mass -> material value.

    .venv/bin/python scripts/predict.py path/to/photo.jpg
    .venv/bin/python scripts/predict.py photo.jpg --mass-g 168     # measured mass beats the average

Class folder names must start with the UNU-KEY so the value chain can join, e.g.
"0306_mobile_phone". Anything before the first underscore is treated as the key.

Low confidence is reported, not hidden. A triage tool that says "I am not sure, open
this one by hand" is more useful — and more honest — than one that always guesses.
"""
import argparse, pathlib, sys
import torch
from PIL import Image
from torchvision import models, transforms

from scripts import valuation

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
CONFIDENCE_FLOOR = 0.60


def load(ckpt_path, device):
    ck = torch.load(ckpt_path, map_location=device)
    classes, arch = ck["classes"], ck.get("arch", "resnet18")
    import torch.nn as nn
    if arch == "resnet18":
        m = models.resnet18(); m.fc = nn.Linear(m.fc.in_features, len(classes))
    elif arch == "resnet50":
        m = models.resnet50(); m.fc = nn.Linear(m.fc.in_features, len(classes))
    else:
        m = models.efficientnet_b0()
        m.classifier = nn.Sequential(nn.Dropout(0.2), nn.Linear(m.classifier[1].in_features, len(classes)))
    m.load_state_dict(ck["state_dict"])
    return m.to(device).eval(), classes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--ckpt", default=str(ROOT / "models" / "best.pt"))
    ap.add_argument("--mass-g", type=float, default=None)
    ap.add_argument("--topk", type=int, default=3)
    a = ap.parse_args()

    if not pathlib.Path(a.ckpt).exists():
        sys.exit(f"No model at {a.ckpt} — train one first with scripts/train_classifier.py")

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model, classes = load(a.ckpt, device)

    tf = transforms.Compose([transforms.Resize(256), transforms.CenterCrop(224),
                             transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    x = tf(Image.open(a.image).convert("RGB")).unsqueeze(0).to(device)
    with torch.no_grad():
        prob = torch.softmax(model(x), 1)[0]
    conf, idx = prob.topk(min(a.topk, len(classes)))

    print(f"{a.image}\n")
    for c, i in zip(conf.tolist(), idx.tolist()):
        print(f"  {c:6.1%}  {classes[i]}")

    top_conf, top_class = conf[0].item(), classes[idx[0].item()]
    if top_conf < CONFIDENCE_FLOOR:
        print(f"\n  LOW CONFIDENCE ({top_conf:.0%} < {CONFIDENCE_FLOOR:.0%}) — route this device to manual teardown.")
        print("  Log it as a model miss; these are the photos worth adding to training next.")
        return

    key = top_class.split("_")[0]
    if not (key.isdigit() and len(key) == 4):
        print(f"\n  Class name '{top_class}' does not start with a 4-digit UNU-KEY — cannot estimate value.")
        return

    print(f"\n  -> UNU-KEY {key}\n")
    try:
        r = valuation.estimate(key, mass_g=a.mass_g)
    except (valuation.UnknownKey, valuation.CompositionUnavailable) as e:
        print(f"  {e}")
        return

    print(f"  {r['description']}")
    print(f"  mass {r['mass_kg']:.3f} kg ({r['mass_source']})")
    print(f"  material value ${r['value_usd']:.2f}  "
          f"(${r['value_low']:.2f} - ${r['value_high']:.2f})")


if __name__ == "__main__":
    main()
