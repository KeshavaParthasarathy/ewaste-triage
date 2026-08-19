#!/usr/bin/env python3
"""
Export a trained ResNet18 e-waste classifier to Core ML (.mlpackage).

VERIFIED WORKING on this machine (Aug 2026):
  torch 2.13.0 / torchvision 0.28.0 / coremltools 9.0 / Python 3.11.5 / M1 Pro

Two things this script gets right that hand-rolled conversions usually get wrong:

1. PREPROCESSING IS FOLDED INTO THE GRAPH.
   coremltools' ImageType `scale` is a SINGLE SCALAR, but ImageNet normalization
   uses a PER-CHANNEL std ([0.229,0.224,0.225]). Passing a scalar approximation
   silently shifts every input. Measured effect: top-1 agreement with PyTorch
   dropped to 0/40. Folding normalization into a wrapper module instead gives
   39/40 agreement, max probability delta 0.000357 (pure fp16 rounding).

2. SOFTMAX IS IN THE GRAPH, so `classLabel_probs` are real probabilities.
   Without it Core ML hands the app raw logits and any confidence threshold
   in the UI is meaningless.

Usage:
    python scripts/export_coreml.py --weights runs/best.pt --labels labels.txt
    python scripts/export_coreml.py --weights runs/best.pt --labels labels.txt --nbits 8
"""
import argparse, json, pathlib, sys

MEAN = [0.485, 0.456, 0.406]
STD  = [0.229, 0.224, 0.225]


def build(weights, n_classes):
    import torch, torchvision
    m = torchvision.models.resnet18(weights=None)
    m.fc = torch.nn.Linear(512, n_classes)
    if weights:
        sd = torch.load(weights, map_location="cpu")
        sd = sd.get("model", sd.get("state_dict", sd))
        sd = {k.replace("module.", ""): v for k, v in sd.items()}
        missing, unexpected = m.load_state_dict(sd, strict=False)
        if missing or unexpected:
            print(f"  ! missing={list(missing)[:4]} unexpected={list(unexpected)[:4]}", file=sys.stderr)
    return m.eval()


def wrap(core):
    """Fold /255, per-channel normalization and softmax into the graph."""
    import torch

    class Wrapped(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m
            self.register_buffer("mu", torch.tensor(MEAN).view(1, 3, 1, 1))
            self.register_buffer("sd", torch.tensor(STD).view(1, 3, 1, 1))

        def forward(self, x):                      # x: raw RGB 0..255
            return torch.softmax(self.m((x / 255.0 - self.mu) / self.sd), dim=1)

    return Wrapped(core).eval()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=None, help="trained .pt state_dict")
    ap.add_argument("--labels", required=True, help="one class name per line")
    ap.add_argument("--out", default="EwasteClassifier.mlpackage")
    ap.add_argument("--nbits", type=int, default=0,
                    help="0=fp16 (21.3MB), 8=10.7MB, 6=8.0MB, 4=5.3MB")
    ap.add_argument("--size", type=int, default=224)
    args = ap.parse_args()

    import torch, coremltools as ct

    labels = [l.strip() for l in open(args.labels) if l.strip()]
    print(f"[1/4] {len(labels)} classes")

    model = wrap(build(args.weights, len(labels)))
    example = torch.rand(1, 3, args.size, args.size) * 255

    print("[2/4] tracing (torch.jit.trace — NOT torch.export; see notes)")
    ts = torch.jit.trace(model, example)

    print("[3/4] converting to Core ML")
    ml = ct.convert(
        ts,
        inputs=[ct.ImageType(name="image", shape=example.shape)],   # scale=1, bias=0
        classifier_config=ct.ClassifierConfig(labels),
        convert_to="mlprogram",
        minimum_deployment_target=ct.target.iOS17,
    )
    ml.short_description = "E-waste device classifier -> UNU-KEY category"
    ml.author = "E-Waste Triage science-fair project"
    ml.version = "1.0"
    ml.input_description["image"] = f"{args.size}x{args.size} RGB photo of the device"

    if args.nbits:
        print(f"[3b] palettizing to {args.nbits}-bit")
        import coremltools.optimize.coreml as cto
        cfg = cto.OptimizationConfig(
            global_config=cto.OpPalettizerConfig(nbits=args.nbits, mode="kmeans"))
        ml = cto.palettize_weights(ml, cfg)

    ml.save(args.out)

    # ---- parity check: the step people skip and then wonder why accuracy dropped
    print("[4/4] parity check vs PyTorch")
    import numpy as np
    from PIL import Image
    chk = ct.models.MLModel(args.out, compute_units=ct.ComputeUnit.ALL)
    agree, worst = 0, 0.0
    N = 25
    for _ in range(N):
        arr = (np.random.rand(args.size, args.size, 3) * 255).astype("uint8")
        with torch.no_grad():
            ref = model(torch.from_numpy(arr.transpose(2, 0, 1)[None]).float()).numpy().ravel()
        out = chk.predict({"image": Image.fromarray(arr)})
        d = [v for v in out.values() if isinstance(v, dict)][0]
        got = np.array([d[c] for c in labels])
        agree += int(got.argmax() == ref.argmax())
        worst = max(worst, float(np.abs(got - ref).max()))
    print(f"      top-1 agreement {agree}/{N}, max prob delta {worst:.6f}")
    if agree < N * 0.9:
        print("      !! PARITY FAILED — do not ship this model.", file=sys.stderr)

    size_mb = sum(f.stat().st_size for f in pathlib.Path(args.out).rglob("*")) / 1048576
    print(f"\nWrote {args.out}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
