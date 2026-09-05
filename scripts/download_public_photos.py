"""Download a balanced, attributable Open Images subset for the photo classifier.

The official Open Images index files are cached separately because the training image
metadata alone is hundreds of megabytes. Once those indexes exist, this command is
resume-safe:

    .venv/bin/python -m scripts.download_public_photos --per-class 200
"""

import argparse
import csv
import hashlib
import io
from pathlib import Path
import random
import re
import time
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

from scripts.photo_classes import PHOTO_CLASS_SPECS


CC_BY_MARKER = "creativecommons.org/licenses/by/"
OPEN_IMAGES_ID = re.compile(r"^[0-9a-f]{16}$")
OPEN_IMAGES_FILENAME = re.compile(r"^oi[0-9a-f]{16}_000\.jpg$")
MANIFEST_FIELDS = [
    "local_path", "class_name", "openimages_label", "openimages_mid",
    "source_split", "image_id", "dataset_url", "original_url",
    "original_landing_url", "license", "author_profile_url", "author",
    "title", "rotation_ccw", "sha256", "width", "height",
]
CLASS_SPECS = PHOTO_CLASS_SPECS
ANNOTATION_FILES = {
    "train": "train-annotations-human-imagelabels-boxable.csv",
    "validation": "validation-annotations-human-imagelabels.csv",
    "test": "test-annotations-human-imagelabels.csv",
}
METADATA_FILES = {
    "train": "train-images-boxable-with-rotation.csv",
    "validation": "validation-images-with-rotation.csv",
    "test": "test-images-with-rotation.csv",
}
INDEX_URLS = {
    ANNOTATION_FILES["train"]: "https://storage.googleapis.com/openimages/v5/train-annotations-human-imagelabels-boxable.csv",
    ANNOTATION_FILES["validation"]: "https://storage.googleapis.com/openimages/v5/validation-annotations-human-imagelabels.csv",
    ANNOTATION_FILES["test"]: "https://storage.googleapis.com/openimages/v5/test-annotations-human-imagelabels.csv",
    METADATA_FILES["train"]: "https://storage.googleapis.com/openimages/2018_04/train/train-images-boxable-with-rotation.csv",
    METADATA_FILES["validation"]: "https://storage.googleapis.com/openimages/2018_04/validation/validation-images-with-rotation.csv",
    METADATA_FILES["test"]: "https://storage.googleapis.com/openimages/2018_04/test/test-images-with-rotation.csv",
}


def candidate_ids(annotation_paths, target_mids):
    """Return positive images that carry exactly one of the target labels."""
    labels_by_image = {}
    for split, path in annotation_paths.items():
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                mid = row["LabelName"]
                if mid in target_mids and row["Confidence"] == "1":
                    labels_by_image.setdefault((split, row["ImageID"]), set()).add(mid)

    out = {mid: [] for mid in target_mids}
    for image, labels in labels_by_image.items():
        if len(labels) == 1:
            out[next(iter(labels))].append(image)
    for images in out.values():
        images.sort()
    return out


def load_metadata(metadata_paths, wanted_images):
    """Load attribution for wanted images, rejecting anything not marked CC BY."""
    out = {}
    for split, path in metadata_paths.items():
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                key = (split, row["ImageID"])
                if key in wanted_images and CC_BY_MARKER in row.get("License", ""):
                    out[key] = row
    return out


def assemble_candidates(ids_by_mid, metadata, class_specs, seed=0):
    """Join labels to attribution metadata and randomize reproducibly."""
    rng = random.Random(seed)
    out = {}
    for class_name in sorted(class_specs):
        spec = class_specs[class_name]
        images = list(ids_by_mid.get(spec["mid"], []))
        rng.shuffle(images)
        rows = []
        for split, image_id in images:
            source = metadata.get((split, image_id))
            if source is not None:
                rows.append({
                    **source,
                    "split": split,
                    "image_id": image_id,
                    "mid": spec["mid"],
                    "label": spec["label"],
                })
        out[class_name] = rows
    return out


def parse_rotation(value):
    """Parse Open Images' counterclockwise rotation metadata."""
    if value in (None, "") or str(value).lower() == "nan":
        return 0
    rotation = int(float(value))
    if rotation not in {0, 90, 180, 270}:
        raise ValueError(f"unsupported Open Images rotation: {value}")
    return rotation


def normalize_image(data, output_path, max_side=1600, rotation=0, max_input_pixels=40_000_000):
    """Decode, orient, resize, and re-encode an image as a bounded RGB JPEG."""
    output_path = Path(output_path)
    partial = output_path.with_name(output_path.name + ".part")
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > max_input_pixels:
            raise ValueError(
                f"source exceeds pixel limit: {source.width}x{source.height} > {max_input_pixels}"
            )
        image = ImageOps.exif_transpose(source).convert("RGB")
        if rotation:
            image = image.rotate(rotation, expand=True)
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(partial, format="JPEG", quality=90, optimize=True)
        width, height = image.size
    digest = hashlib.sha256(partial.read_bytes()).hexdigest()
    partial.replace(output_path)
    return {"width": width, "height": height, "sha256": digest}


def public_filename(image_id):
    """Name each Open Images photo as a separate splitter-level device."""
    if not OPEN_IMAGES_ID.fullmatch(image_id):
        raise ValueError("Open Images image_id must be exactly 16 lowercase hex characters")
    return f"oi{image_id}_000.jpg"


def image_url(split, image_id):
    public_filename(image_id)
    return f"https://open-images-dataset.s3.amazonaws.com/{split}/{image_id}.jpg"


def fetch_url(url, retries=3, timeout=30, max_bytes=20 * 1024 * 1024):
    """Fetch bytes with bounded retries for transient public-dataset failures."""
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"User-Agent": "ewaste-triage-dataset/1.0"})
            with urlopen(request, timeout=timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise ValueError(f"response exceeds byte limit of {max_bytes}")
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ValueError(f"response exceeds byte limit of {max_bytes}")
                return data
        except OSError as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1 + attempt)
    raise last_error


def download_file(url, path, chunk_size=1024 * 1024):
    """Stream a large index to disk without holding it in memory."""
    request = Request(url, headers={"User-Agent": "ewaste-triage-dataset/1.0"})
    with urlopen(request, timeout=60) as response, path.open("wb") as output:
        while chunk := response.read(chunk_size):
            output.write(chunk)


def ensure_indexes(cache_dir, index_urls=INDEX_URLS, download=download_file):
    """Download missing official indexes atomically and preserve completed files."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in index_urls.items():
        destination = cache_dir / filename
        if destination.exists():
            continue
        partial = destination.with_suffix(destination.suffix + ".part")
        print(f"downloading index {filename} ...")
        download(url, partial)
        partial.replace(destination)


def _write_manifest(path, rows):
    partial = path.with_name(path.name + ".part")
    with partial.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    partial.replace(path)


def _reconcile_manifest(output_root, manifest_path, candidates):
    rows = []
    if manifest_path.exists():
        with manifest_path.open(newline="") as fh:
            rows = list(csv.DictReader(fh))

    expected = {}
    for class_name, records in candidates.items():
        for record in records:
            expected[record["image_id"]] = (class_name, parse_rotation(record.get("Rotation")))

    valid = []
    valid_paths = set()
    for row in rows:
        image_id = row.get("image_id", "")
        expectation = expected.get(image_id)
        if expectation is None:
            continue
        class_name, rotation = expectation
        try:
            expected_path = (output_root / class_name / public_filename(image_id)).resolve()
            is_valid = row.get("class_name") == class_name
            is_valid = is_valid and (output_root / row["local_path"]).resolve() == expected_path
            is_valid = is_valid and expected_path.is_relative_to(output_root.resolve())
            is_valid = is_valid and expected_path.exists()
            if is_valid:
                with Image.open(expected_path) as image:
                    image.verify()
                with Image.open(expected_path) as image:
                    is_valid = (
                        image.format == "JPEG"
                        and image.mode == "RGB"
                        and max(image.size) <= 1600
                    )
            if is_valid:
                is_valid = hashlib.sha256(expected_path.read_bytes()).hexdigest() == row.get("sha256")
            recorded_rotation = parse_rotation(row.get("rotation_ccw"))
            is_valid = is_valid and recorded_rotation == rotation
        except (KeyError, OSError, ValueError):
            continue

        if is_valid:
            row["rotation_ccw"] = str(rotation)
            valid.append(row)
            valid_paths.add(expected_path)
        elif expected_path.is_relative_to(output_root.resolve()) and expected_path.exists():
            expected_path.unlink()

    for class_name in candidates:
        class_dir = output_root / class_name
        if not class_dir.exists():
            continue
        for path in class_dir.glob("*.jpg"):
            if OPEN_IMAGES_FILENAME.fullmatch(path.name) and path.resolve() not in valid_paths:
                path.unlink()

    _write_manifest(manifest_path, valid)
    return valid


def import_candidates(candidates, output_root, per_class, fetch):
    """Download normalized candidates and append complete attribution records."""
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "public_manifest.csv"
    existing = _reconcile_manifest(output_root, manifest_path, candidates)
    known_ids = {row["image_id"] for row in existing}
    known_hashes = {row["sha256"] for row in existing if row.get("sha256")}
    summary = {
        class_name: sum(row["class_name"] == class_name for row in existing)
        for class_name in candidates
    }

    with manifest_path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        for class_name in sorted(candidates):
            for record in candidates[class_name]:
                if summary[class_name] >= per_class:
                    break
                image_id = record["image_id"]
                if image_id in known_ids:
                    continue
                dataset_url = image_url(record["split"], image_id)
                try:
                    data = fetch(dataset_url)
                    filename = public_filename(image_id)
                    output_path = output_root / class_name / filename
                    rotation = parse_rotation(record.get("Rotation"))
                    info = normalize_image(data, output_path, rotation=rotation)
                    if info["sha256"] in known_hashes:
                        output_path.unlink()
                        print(f"skip {image_id}: duplicate pixels")
                        continue
                except Exception as exc:
                    print(f"skip {image_id}: {exc}")
                    continue
                row = {
                    "local_path": str(output_path.relative_to(output_root)),
                    "class_name": class_name,
                    "openimages_label": record["label"],
                    "openimages_mid": record["mid"],
                    "source_split": record["split"],
                    "image_id": image_id,
                    "dataset_url": dataset_url,
                    "original_url": record["OriginalURL"],
                    "original_landing_url": record["OriginalLandingURL"],
                    "license": record["License"],
                    "author_profile_url": record["AuthorProfileURL"],
                    "author": record["Author"],
                    "title": record["Title"],
                    "rotation_ccw": rotation,
                    **info,
                }
                writer.writerow(row)
                fh.flush()
                known_ids.add(image_id)
                known_hashes.add(info["sha256"])
                summary[class_name] += 1
    return dict(sorted(summary.items()))


def run_import(cache_dir, output_root, per_class=200, seed=0, fetch=None):
    """Build and import the approved five-class dataset from cached indexes."""
    cache_dir = Path(cache_dir)
    annotation_paths = {split: cache_dir / name for split, name in ANNOTATION_FILES.items()}
    metadata_paths = {split: cache_dir / name for split, name in METADATA_FILES.items()}
    missing = [path for path in [*annotation_paths.values(), *metadata_paths.values()] if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing Open Images index: {missing[0]}")

    target_mids = {spec["mid"] for spec in CLASS_SPECS.values()}
    ids_by_mid = candidate_ids(annotation_paths, target_mids)
    wanted = {image for images in ids_by_mid.values() for image in images}
    metadata = load_metadata(metadata_paths, wanted)
    candidates = assemble_candidates(ids_by_mid, metadata, CLASS_SPECS, seed)
    if fetch is None:
        raise ValueError("fetch function is required")
    return import_candidates(candidates, output_root, per_class, fetch)


def main(argv=None):
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=root / "data" / "photos" / ".openimages-cache")
    parser.add_argument("--output", default=root / "data" / "photos" / "raw")
    parser.add_argument("--per-class", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    ensure_indexes(args.cache_dir)
    summary = run_import(args.cache_dir, args.output, args.per_class, args.seed, fetch_url)
    for class_name, count in summary.items():
        print(f"{class_name}: {count}/{args.per_class}")
    if any(count < args.per_class for count in summary.values()):
        raise SystemExit("dataset incomplete: one or more classes did not reach the requested count")


if __name__ == "__main__":
    main()
