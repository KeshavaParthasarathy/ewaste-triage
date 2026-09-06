import os
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from PIL import Image

from server.history import HistoryStore


PREDICTION = {
    "class_name": "0306_mobile_phone",
    "unu_key": "0306",
    "confidence": 0.91,
    "low_confidence": False,
    "topk": [
        {"class_name": "0306_mobile_phone", "confidence": 0.91},
        {"class_name": "0303_laptop", "confidence": 0.09},
    ],
}


def test_assessment_snapshot_is_versioned_and_survives_store_reopen(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    scan_id = store.add_scan(PREDICTION, Image.new("RGB", (10, 10)), retain_original=False, original=None)
    template = {
        "category_id": "0306_mobile_phone",
        "template_version": "1.0.0",
        "components": [{"component_id": "battery", "lifecycle": None}],
        "rules": [],
        "source_ids": ["source"],
    }

    created = store.create_assessment(scan_id, template)
    updated = store.update_assessment(scan_id, {"usage": "heavy"}, {})
    reopened = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media").get_assessment(scan_id)

    assert created["template_version"] == "1.0.0"
    assert updated["inputs"] == {"usage": "heavy"}
    assert reopened == updated
    assert store.create_assessment(scan_id, {**template, "template_version": "2.0.0"}) == updated


def test_scan_persists_with_stable_uuid_and_utc_timestamp(tmp_path):
    database = tmp_path / "history.sqlite"
    media = tmp_path / "media"
    scan_id = HistoryStore(database, media).add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50), "blue"),
        retain_original=False,
        original=None,
    )

    record = HistoryStore(database, media).get_scan(scan_id)

    assert record is not None
    assert str(uuid.UUID(record["scan_id"], version=4)) == scan_id
    created_at = datetime.fromisoformat(record["created_at"])
    assert created_at.tzinfo is not None
    assert created_at.utcoffset() == timezone.utc.utcoffset(created_at)
    assert record["prediction"] == PREDICTION
    assert HistoryStore(database, media).list_scans() == [record]


def test_original_photo_is_not_retained_by_default(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")

    scan_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50), "blue"),
        retain_original=False,
        original=Image.new("RGB", (100, 80), "red"),
    )

    record = store.get_scan(scan_id)
    assert record["original_path"] is None
    assert sorted(pathlib.Path(tmp_path / "media").iterdir()) == [
        pathlib.Path(record["thumbnail_path"])
    ]


def test_explicitly_retained_original_is_managed_by_the_store(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")

    scan_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50), "blue"),
        retain_original=True,
        original=Image.new("RGB", (100, 80), "red"),
    )

    record = store.get_scan(scan_id)
    assert pathlib.Path(record["original_path"]).exists()
    assert pathlib.Path(record["original_path"]).parent == (tmp_path / "media").resolve()


def test_delete_scan_removes_managed_thumbnail(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    scan_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50)),
        retain_original=False,
        original=None,
    )
    thumb = pathlib.Path(store.get_scan(scan_id)["thumbnail_path"])

    assert thumb.exists()
    assert store.delete_scan(scan_id) is True
    assert not thumb.exists()
    assert store.delete_scan(scan_id) is False


def test_delete_scan_never_unlinks_a_path_outside_media_dir(tmp_path):
    database = tmp_path / "history.sqlite"
    media = tmp_path / "media"
    store = HistoryStore(database, media)
    scan_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50)),
        retain_original=False,
        original=None,
    )
    outside = tmp_path / "do-not-delete.jpg"
    outside.write_bytes(b"private")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE scans SET thumbnail_path = ? WHERE scan_id = ?",
            (str(outside), scan_id),
        )

    assert store.delete_scan(scan_id) is True
    assert outside.read_bytes() == b"private"


def test_delete_scan_never_treats_media_directory_as_a_file(tmp_path):
    database = tmp_path / "history.sqlite"
    media = tmp_path / "media"
    store = HistoryStore(database, media)
    scan_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50)),
        retain_original=False,
        original=None,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE scans SET thumbnail_path = ? WHERE scan_id = ?",
            (str(media), scan_id),
        )

    assert store.delete_scan(scan_id) is True
    assert media.is_dir()


def test_delete_scan_keeps_failed_cleanup_recoverable(tmp_path, monkeypatch):
    database = tmp_path / "history.sqlite"
    media = tmp_path / "media"
    store = HistoryStore(database, media)
    scan_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50)),
        retain_original=False,
        original=None,
    )
    thumbnail = pathlib.Path(store.get_scan(scan_id)["thumbnail_path"])
    real_unlink = os.unlink

    def deny_unlink_once(path, *args, **kwargs):
        monkeypatch.setattr(os, "unlink", real_unlink)
        raise PermissionError("media is busy")

    monkeypatch.setattr(os, "unlink", deny_unlink_once)

    with pytest.raises(PermissionError, match="media is busy"):
        store.delete_scan(scan_id)

    assert thumbnail.exists()
    reopened = HistoryStore(database, media)
    assert reopened.delete_scan(scan_id) is True
    assert not thumbnail.exists()
    assert reopened.delete_scan(scan_id) is False


def test_clear_reports_partial_cleanup_failure_and_retries_remaining_media(
    tmp_path, monkeypatch
):
    database = tmp_path / "history.sqlite"
    media = tmp_path / "media"
    store = HistoryStore(database, media)
    for color in ("blue", "red"):
        store.add_scan(
            PREDICTION,
            Image.new("RGB", (50, 50), color),
            retain_original=False,
            original=None,
        )
    real_unlink = os.unlink
    calls = 0

    def fail_second_unlink(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("second media file is busy")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_second_unlink)

    with pytest.raises(PermissionError, match="second media file is busy"):
        store.clear()

    assert len(list(media.iterdir())) == 1
    monkeypatch.setattr(os, "unlink", real_unlink)
    reopened = HistoryStore(database, media)
    assert reopened.clear() == 0
    assert list(media.iterdir()) == []


def test_delete_scan_unlinks_symlink_alias_without_deleting_another_scan(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    first_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50), "blue"),
        retain_original=False,
        original=None,
    )
    second_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50), "red"),
        retain_original=False,
        original=None,
    )
    first_thumbnail = pathlib.Path(store.get_scan(first_id)["thumbnail_path"])
    second_thumbnail = pathlib.Path(store.get_scan(second_id)["thumbnail_path"])
    first_thumbnail.unlink()
    first_thumbnail.symlink_to(second_thumbnail)

    assert store.delete_scan(first_id) is True
    assert not os.path.lexists(first_thumbnail)
    assert second_thumbnail.exists()
    assert store.get_scan(second_id) is not None


@pytest.mark.parametrize("tampered_kind", ["traversal", "absolute"])
def test_clear_discards_invalid_legacy_journal_path_and_deletes_valid_media(
    tmp_path, tampered_kind
):
    database = tmp_path / "history.sqlite"
    media = tmp_path / "media"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE pending_media_deletions (
                scan_id TEXT NOT NULL,
                media_name TEXT PRIMARY KEY
            )
            """
        )
    store = HistoryStore(database, media)
    scan_id = store.add_scan(
        PREDICTION,
        Image.new("RGB", (50, 50), "blue"),
        retain_original=False,
        original=None,
    )
    thumbnail = pathlib.Path(store.get_scan(scan_id)["thumbnail_path"])
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"must survive")
    tampered = "../outside.jpg" if tampered_kind == "traversal" else str(outside)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO pending_media_deletions (scan_id, media_name) VALUES (?, ?)",
            ("tampered", tampered),
        )

    assert store.clear() == 1
    assert outside.read_bytes() == b"must survive"
    assert not thumbnail.exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT media_name FROM pending_media_deletions"
        ).fetchall() == []


def test_new_history_schema_rejects_invalid_journal_media_name(tmp_path):
    database = tmp_path / "history.sqlite"
    HistoryStore(database, tmp_path / "media")

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO pending_media_deletions (scan_id, media_name) VALUES (?, ?)",
                ("tampered", "../outside.jpg"),
            )


def test_failed_database_insert_removes_new_media_files(tmp_path):
    database = tmp_path / "history.sqlite"
    media = tmp_path / "media"
    store = HistoryStore(database, media)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER reject_scan BEFORE INSERT ON scans "
            "BEGIN SELECT RAISE(ABORT, 'reject scan'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="reject scan"):
        store.add_scan(
            PREDICTION,
            Image.new("RGB", (50, 50)),
            retain_original=True,
            original=Image.new("RGB", (100, 80)),
        )

    assert store.list_scans() == []
    assert list(media.iterdir()) == []


def test_failed_image_write_removes_partial_media_and_creates_no_row(
    tmp_path, monkeypatch
):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    real_save = Image.Image.save
    save_count = 0

    def fail_during_original_save(image, path, *args, **kwargs):
        nonlocal save_count
        save_count += 1
        if save_count == 2:
            pathlib.Path(path).write_bytes(b"partial jpeg")
            raise OSError("disk full")
        return real_save(image, path, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", fail_during_original_save)

    with pytest.raises(OSError, match="disk full"):
        store.add_scan(
            PREDICTION,
            Image.new("RGB", (50, 50)),
            retain_original=True,
            original=Image.new("RGB", (100, 80)),
        )

    assert store.list_scans() == []
    assert list((tmp_path / "media").iterdir()) == []


def test_clear_removes_all_rows_and_managed_files(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite", tmp_path / "media")
    for color in ("blue", "red"):
        store.add_scan(
            PREDICTION,
            Image.new("RGB", (50, 50), color),
            retain_original=True,
            original=Image.new("RGB", (100, 80), color),
        )

    assert store.clear() == 2
    assert store.list_scans() == []
    assert list((tmp_path / "media").iterdir()) == []
