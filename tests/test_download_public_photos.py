import csv
import base64
import io

from PIL import Image
import pytest

from scripts.download_public_photos import (
    assemble_candidates,
    candidate_ids,
    fetch_url,
    ensure_indexes,
    import_candidates,
    load_metadata,
    normalize_image,
    parse_rotation,
    public_filename,
    run_import,
)
from scripts.split_dataset import scan


def _write_annotations(path, rows):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["ImageID", "Source", "LabelName", "Confidence"]
        )
        writer.writeheader()
        writer.writerows(rows)


def test_candidate_ids_keep_only_positive_images_with_one_target_class(tmp_path):
    """A multi-target or negative image would teach an ambiguous/wrong class."""
    annotations = tmp_path / "validation-labels.csv"
    _write_annotations(
        annotations,
        [
            {"ImageID": "phone", "Source": "verification", "LabelName": "/phone", "Confidence": "1"},
            {"ImageID": "laptop", "Source": "verification", "LabelName": "/laptop", "Confidence": "1"},
            {"ImageID": "overlap", "Source": "verification", "LabelName": "/phone", "Confidence": "1"},
            {"ImageID": "overlap", "Source": "verification", "LabelName": "/laptop", "Confidence": "1"},
            {"ImageID": "negative", "Source": "verification", "LabelName": "/phone", "Confidence": "0"},
            {"ImageID": "other", "Source": "verification", "LabelName": "/other", "Confidence": "1"},
        ],
    )

    got = candidate_ids({"validation": annotations}, {"/phone", "/laptop"})

    assert got == {
        "/phone": [("validation", "phone")],
        "/laptop": [("validation", "laptop")],
    }


def test_load_metadata_keeps_only_wanted_cc_by_images(tmp_path):
    """Unlicensed and unrelated metadata must never enter the download set."""
    metadata = tmp_path / "images.csv"
    fields = [
        "ImageID", "Subset", "OriginalURL", "OriginalLandingURL", "License",
        "AuthorProfileURL", "Author", "Title",
    ]
    with metadata.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows([
            {"ImageID": "wanted", "Subset": "validation", "OriginalURL": "https://images.test/a.jpg",
             "OriginalLandingURL": "https://photos.test/a", "License": "https://creativecommons.org/licenses/by/2.0/",
             "AuthorProfileURL": "https://photos.test/author", "Author": "A Person", "Title": "A phone"},
            {"ImageID": "no-license", "Subset": "validation", "OriginalURL": "https://images.test/b.jpg",
             "OriginalLandingURL": "https://photos.test/b", "License": "", "AuthorProfileURL": "",
             "Author": "B Person", "Title": "Another phone"},
            {"ImageID": "unrelated", "Subset": "validation", "OriginalURL": "https://images.test/c.jpg",
             "OriginalLandingURL": "https://photos.test/c", "License": "https://creativecommons.org/licenses/by/2.0/",
             "AuthorProfileURL": "", "Author": "C Person", "Title": "Other"},
        ])

    got = load_metadata({"validation": metadata}, {("validation", "wanted"), ("validation", "no-license")})

    assert set(got) == {("validation", "wanted")}
    assert got[("validation", "wanted")]["Author"] == "A Person"
    assert got[("validation", "wanted")]["OriginalLandingURL"] == "https://photos.test/a"


def test_normalize_image_writes_bounded_rgb_jpeg(tmp_path):
    """A huge or non-RGB source must not consume uncontrolled space or break torchvision."""
    source = io.BytesIO()
    Image.new("RGBA", (3200, 1200), (10, 20, 30, 128)).save(source, format="PNG")
    output = tmp_path / "normalized.jpg"

    info = normalize_image(source.getvalue(), output, max_side=1600)

    with Image.open(output) as saved:
        assert saved.format == "JPEG"
        assert saved.mode == "RGB"
        assert saved.size == (1600, 600)
    assert info["width"] == 1600
    assert info["height"] == 600
    assert len(info["sha256"]) == 64


@pytest.mark.parametrize(
    ("rotation", "expected_size"),
    [(90, (20, 40)), (180, (40, 20)), (270, (20, 40))],
)
def test_normalize_image_applies_openimages_counterclockwise_rotation(tmp_path, rotation, expected_size):
    """Open Images strips EXIF, so its CSV rotation is the only orientation source."""
    source = io.BytesIO()
    image = Image.new("RGB", (40, 20), "red")
    for x in range(20, 40):
        for y in range(20):
            image.putpixel((x, y), (0, 0, 255))
    image.save(source, format="PNG")
    output = tmp_path / f"rotated-{rotation}.jpg"

    normalize_image(source.getvalue(), output, rotation=rotation)

    with Image.open(output) as saved:
        assert saved.size == expected_size
        if rotation == 180:
            left, right = saved.getpixel((5, 10)), saved.getpixel((35, 10))
            assert left[2] > left[0]
            assert right[0] > right[2]


def test_parse_rotation_accepts_official_values_and_treats_unknown_as_zero():
    assert parse_rotation("") == 0
    assert parse_rotation("nan") == 0
    assert parse_rotation("270.0") == 270
    with pytest.raises(ValueError):
        parse_rotation("45")


def test_public_filenames_remain_distinct_devices_for_the_splitter(tmp_path):
    """An underscore in the source prefix would collapse every public photo into one device."""
    class_dir = tmp_path / "0306_mobile_phone"
    class_dir.mkdir()
    for image_id in ("0000000000000001", "0000000000000002"):
        Image.new("RGB", (10, 10)).save(class_dir / public_filename(image_id))

    records = scan(tmp_path)

    assert {device_id for _, _, device_id in records} == {
        "oi0000000000000001", "oi0000000000000002"
    }


@pytest.mark.parametrize("image_id", ["../escape", "abc", "ABCDEF0123456789", "0123456789abcdef/../x"])
def test_public_filename_rejects_non_official_or_path_traversing_ids(image_id):
    with pytest.raises(ValueError, match="16 lowercase hex"):
        public_filename(image_id)


def test_import_candidates_writes_balanced_images_and_attribution_manifest(tmp_path):
    """Every saved training image must remain traceable to its author, page, and license."""
    image_bytes = {}
    for image_id, color in (("0000000000000001", (20, 40, 60)), ("0000000000000002", (80, 100, 120))):
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), color).save(buf, format="PNG")
        image_bytes[image_id] = buf.getvalue()

    candidates = {
        "0306_mobile_phone": [{
            "split": "validation", "image_id": "0000000000000001", "mid": "/phone", "label": "Mobile phone",
            "OriginalURL": "https://images.test/phone.jpg", "OriginalLandingURL": "https://photos.test/phone",
            "License": "https://creativecommons.org/licenses/by/2.0/", "AuthorProfileURL": "",
            "Author": "Phone Author", "Title": "Phone title",
        }],
        "0303_laptop": [{
            "split": "test", "image_id": "0000000000000002", "mid": "/laptop", "label": "Laptop",
            "OriginalURL": "https://images.test/laptop.jpg", "OriginalLandingURL": "https://photos.test/laptop",
            "License": "https://creativecommons.org/licenses/by/2.0/", "AuthorProfileURL": "",
            "Author": "Laptop Author", "Title": "Laptop title",
        }],
    }

    def fetch(url):
        image_id = url.rsplit("/", 1)[-1].removesuffix(".jpg")
        return image_bytes[image_id]

    summary = import_candidates(candidates, tmp_path, per_class=1, fetch=fetch)

    assert summary == {"0303_laptop": 1, "0306_mobile_phone": 1}
    assert (tmp_path / "0306_mobile_phone" / "oi0000000000000001_000.jpg").exists()
    assert (tmp_path / "0303_laptop" / "oi0000000000000002_000.jpg").exists()
    with (tmp_path / "public_manifest.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert {(row["class_name"], row["author"], row["license"]) for row in rows} == {
        ("0306_mobile_phone", "Phone Author", "https://creativecommons.org/licenses/by/2.0/"),
        ("0303_laptop", "Laptop Author", "https://creativecommons.org/licenses/by/2.0/"),
    }


def test_import_candidates_skips_duplicate_pixels_across_classes(tmp_path):
    """The same photo in two folders would create label conflict and validation leakage."""
    def png(color):
        buf = io.BytesIO()
        Image.new("RGB", (30, 20), color).save(buf, format="PNG")
        return buf.getvalue()

    payloads = {
        "0000000000000001": png((10, 20, 30)),
        "0000000000000002": png((10, 20, 30)),
        "0000000000000003": png((90, 80, 70)),
    }

    def record(image_id):
        return {
            "split": "validation", "image_id": image_id, "mid": "/object", "label": "Object",
            "OriginalURL": "https://images.test/source.jpg", "OriginalLandingURL": "https://photos.test/source",
            "License": "https://creativecommons.org/licenses/by/2.0/", "AuthorProfileURL": "",
            "Author": "Author", "Title": "Title",
        }

    candidates = {
        "class_a": [record("0000000000000001")],
        "class_b": [record("0000000000000002"), record("0000000000000003")],
    }
    summary = import_candidates(
        candidates,
        tmp_path,
        per_class=1,
        fetch=lambda url: payloads[url.rsplit("/", 1)[-1].removesuffix(".jpg")],
    )

    assert summary == {"class_a": 1, "class_b": 1}
    assert not (tmp_path / "class_b" / "oi0000000000000002_000.jpg").exists()
    assert (tmp_path / "class_b" / "oi0000000000000003_000.jpg").exists()


def test_assemble_candidates_is_seeded_and_attaches_source_metadata():
    """A reproducible seed must produce the same auditable source selection."""
    ids = {"/phone": [("validation", "a"), ("test", "b")]}
    metadata = {
        ("validation", "a"): {"Author": "A"},
        ("test", "b"): {"Author": "B"},
    }
    specs = {"0306_mobile_phone": {"mid": "/phone", "label": "Mobile phone"}}

    first = assemble_candidates(ids, metadata, specs, seed=19)
    second = assemble_candidates(ids, metadata, specs, seed=19)

    assert first == second
    assert {row["image_id"] for row in first["0306_mobile_phone"]} == {"a", "b"}
    assert all(row["mid"] == "/phone" and row["label"] == "Mobile phone" for row in first["0306_mobile_phone"])
    assert {row["Author"] for row in first["0306_mobile_phone"]} == {"A", "B"}


def test_run_import_coordinates_all_five_project_classes(tmp_path):
    """The default import must populate every class exposed by the collection UI."""
    cache = tmp_path / "cache"
    cache.mkdir()
    mids = {
        "0000000000000001": "/m/050k8",
        "0000000000000002": "/m/01c648",
        "0000000000000003": "/m/01m2v",
        "0000000000000004": "/m/020lf",
        "0000000000000005": "/m/01b7fy",
    }
    annotation_fields = ["ImageID", "Source", "LabelName", "Confidence"]
    metadata_fields = [
        "ImageID", "Subset", "OriginalURL", "OriginalLandingURL", "License",
        "AuthorProfileURL", "Author", "Title",
    ]
    for split, annotation_name, metadata_name in (
        ("train", "train-annotations-human-imagelabels-boxable.csv", "train-images-boxable-with-rotation.csv"),
        ("validation", "validation-annotations-human-imagelabels.csv", "validation-images-with-rotation.csv"),
        ("test", "test-annotations-human-imagelabels.csv", "test-images-with-rotation.csv"),
    ):
        with (cache / annotation_name).open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=annotation_fields)
            writer.writeheader()
            if split == "validation":
                writer.writerows({"ImageID": image_id, "Source": "verification", "LabelName": mid, "Confidence": "1"}
                                 for image_id, mid in mids.items())
        with (cache / metadata_name).open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=metadata_fields)
            writer.writeheader()
            if split == "validation":
                writer.writerows({
                    "ImageID": image_id, "Subset": split, "OriginalURL": f"https://images.test/{image_id}.jpg",
                    "OriginalLandingURL": f"https://photos.test/{image_id}",
                    "License": "https://creativecommons.org/licenses/by/2.0/", "AuthorProfileURL": "",
                    "Author": image_id, "Title": image_id,
                } for image_id in mids)

    payloads = {}
    for index, image_id in enumerate(mids):
        buf = io.BytesIO()
        Image.new("RGB", (30 + index, 20), (20 * index, 10, 10)).save(buf, format="PNG")
        payloads[image_id] = buf.getvalue()

    summary = run_import(
        cache,
        tmp_path / "raw",
        per_class=1,
        fetch=lambda url: payloads[url.rsplit("/", 1)[-1].removesuffix(".jpg")],
    )

    assert summary == {
        "0301_computer_mouse": 1,
        "0301_keyboard": 1,
        "0303_laptop": 1,
        "0306_mobile_phone": 1,
        "0401_headphones": 1,
    }


def test_fetch_url_returns_response_bytes():
    assert fetch_url("data:text/plain;base64,aGVsbG8=") == b"hello"


def test_fetch_url_rejects_a_response_over_the_byte_limit():
    payload = base64.b64encode(b"123456").decode()
    with pytest.raises(ValueError, match="byte limit"):
        fetch_url(f"data:application/octet-stream;base64,{payload}", max_bytes=5)


def test_normalize_image_rejects_a_source_over_the_pixel_limit(tmp_path):
    source = io.BytesIO()
    Image.new("RGB", (40, 20)).save(source, format="PNG")

    with pytest.raises(ValueError, match="pixel limit"):
        normalize_image(source.getvalue(), tmp_path / "too-large.jpg", max_input_pixels=799)

    assert not (tmp_path / "too-large.jpg").exists()


def test_ensure_indexes_downloads_only_missing_files(tmp_path):
    """A restart must reuse completed gigabyte-scale indexes and fill only gaps."""
    (tmp_path / "kept.csv").write_text("already here")
    calls = []

    def download(url, path):
        calls.append((url, path.name))
        path.write_text(f"downloaded from {url}")

    ensure_indexes(
        tmp_path,
        {"kept.csv": "https://data.test/kept", "missing.csv": "https://data.test/missing"},
        download,
    )

    assert calls == [("https://data.test/missing", "missing.csv.part")]
    assert (tmp_path / "kept.csv").read_text() == "already here"
    assert (tmp_path / "missing.csv").read_text() == "downloaded from https://data.test/missing"
    assert not (tmp_path / "missing.csv.part").exists()


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_import_candidates_repairs_a_damaged_manifest_file_on_resume(tmp_path, damage):
    """A manifest row must not count when its normalized image is gone or invalid."""
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (12, 34, 56)).save(buf, format="PNG")
    payload = buf.getvalue()
    record = {
        "split": "validation", "image_id": "0000000000000001", "mid": "/phone", "label": "Mobile phone",
        "OriginalURL": "https://images.test/phone.jpg", "OriginalLandingURL": "https://photos.test/phone",
        "License": "https://creativecommons.org/licenses/by/2.0/", "AuthorProfileURL": "",
        "Author": "Author", "Title": "Title", "Rotation": "0.0",
    }
    fetches = []

    def fetch(url):
        fetches.append(url)
        return payload

    candidates = {"0306_mobile_phone": [record]}
    import_candidates(candidates, tmp_path, per_class=1, fetch=fetch)
    image_path = tmp_path / "0306_mobile_phone" / "oi0000000000000001_000.jpg"
    if damage == "missing":
        image_path.unlink()
    else:
        image_path.write_bytes(b"not an image")

    summary = import_candidates(candidates, tmp_path, per_class=1, fetch=fetch)

    assert summary == {"0306_mobile_phone": 1}
    assert len(fetches) == 2
    with Image.open(image_path) as repaired:
        repaired.verify()
    with (tmp_path / "public_manifest.csv").open(newline="") as fh:
        assert len(list(csv.DictReader(fh))) == 1


def test_import_candidates_removes_an_unmanifested_public_orphan(tmp_path):
    """A crash-created Open Images JPEG must not silently enter the next split."""
    class_dir = tmp_path / "0306_mobile_phone"
    class_dir.mkdir()
    orphan = class_dir / "oi0123456789abcdef_000.jpg"
    own_photo = class_dir / "oilaptop_000.jpg"
    Image.new("RGB", (20, 20)).save(orphan)
    Image.new("RGB", (20, 20)).save(own_photo)

    import_candidates({"0306_mobile_phone": []}, tmp_path, per_class=0, fetch=lambda _: b"")

    assert not orphan.exists()
    assert own_photo.exists()
