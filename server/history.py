"""Private SQLite scan history with app-managed media files."""

import json
import os
import pathlib
import re
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timezone

from PIL import Image


_MANAGED_MEDIA_NAME = re.compile(r"^[0-9a-f]{32}-(?:thumbnail|original)\.jpg$")


class HistoryStore:
    """Persist scan metadata and remove only media owned by this store."""

    def __init__(self, database_path: pathlib.Path, media_dir: pathlib.Path):
        self.database_path = pathlib.Path(database_path)
        self.media_dir = pathlib.Path(media_dir).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scans (
                    scan_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    prediction_json TEXT NOT NULL,
                    thumbnail_path TEXT NOT NULL,
                    original_path TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_media_deletions (
                    scan_id TEXT NOT NULL,
                    media_name TEXT PRIMARY KEY CHECK (
                        typeof(media_name) = 'text'
                        AND length(substr(media_name, 1, 32)) = 32
                        AND substr(media_name, 1, 32) NOT GLOB '*[^0-9a-f]*'
                        AND substr(media_name, 33) IN (
                            '-thumbnail.jpg', '-original.jpg'
                        )
                    )
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS pending_media_deletions_scan_id
                ON pending_media_deletions (scan_id)
                """
            )
            connection.commit()

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _new_media_path(self, kind: str) -> pathlib.Path:
        return self.media_dir / f"{uuid.uuid4().hex}-{kind}.jpg"

    @staticmethod
    def _save_jpeg(image: Image.Image, path: pathlib.Path, *, thumbnail: bool) -> None:
        prepared = image.copy().convert("RGB")
        if thumbnail:
            prepared.thumbnail((320, 320), Image.Resampling.LANCZOS)
        prepared.save(path, format="JPEG", quality=88)

    def add_scan(
        self,
        prediction: Mapping,
        thumbnail: Image.Image,
        *,
        retain_original: bool,
        original: Image.Image | None,
    ) -> str:
        prediction_json = json.dumps(
            dict(prediction), allow_nan=False, separators=(",", ":"), sort_keys=True
        )
        if retain_original and original is None:
            raise ValueError("original image is required when retain_original is true")

        scan_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        thumbnail_path = self._new_media_path("thumbnail")
        original_path = self._new_media_path("original") if retain_original else None
        written_paths = []
        try:
            written_paths.append(thumbnail_path)
            self._save_jpeg(thumbnail, thumbnail_path, thumbnail=True)
            if original_path is not None:
                written_paths.append(original_path)
                self._save_jpeg(original, original_path, thumbnail=False)

            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO scans (
                            scan_id, created_at, prediction_json,
                            thumbnail_path, original_path
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            scan_id,
                            created_at,
                            prediction_json,
                            str(thumbnail_path),
                            str(original_path) if original_path is not None else None,
                        ),
                    )
        except Exception:
            for path in written_paths:
                path.unlink(missing_ok=True)
            raise
        return scan_id

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        return {
            "scan_id": row["scan_id"],
            "created_at": row["created_at"],
            "prediction": json.loads(row["prediction_json"]),
            "thumbnail_path": row["thumbnail_path"],
            "original_path": row["original_path"],
        }

    def list_scans(self) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM scans ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [self._record(row) for row in rows]

    def get_scan(self, scan_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scans WHERE scan_id = ?", (scan_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    def _managed_media_name(self, stored_path: str | None) -> str | None:
        if stored_path is None:
            return None
        target = pathlib.Path(stored_path)
        if (
            target.is_absolute()
            and target.parent == self.media_dir
            and _MANAGED_MEDIA_NAME.fullmatch(target.name)
        ):
            return target.name
        return None

    def _queue_media(self, connection, scan_id: str, row: sqlite3.Row) -> None:
        for column in ("thumbnail_path", "original_path"):
            media_name = self._managed_media_name(row[column])
            if media_name is not None:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO pending_media_deletions (scan_id, media_name)
                    VALUES (?, ?)
                    """,
                    (scan_id, media_name),
                )

    def _unlink_media_name(self, media_name: str) -> None:
        if not isinstance(media_name, str) or not _MANAGED_MEDIA_NAME.fullmatch(
            media_name
        ):
            return
        directory_fd = os.open(
            self.media_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            try:
                os.unlink(media_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        finally:
            os.close(directory_fd)

    def _drain_pending_deletions(self, scan_id: str | None = None) -> None:
        query = "SELECT scan_id, media_name FROM pending_media_deletions"
        parameters = ()
        if scan_id is not None:
            query += " WHERE scan_id = ?"
            parameters = (scan_id,)
        query += " ORDER BY rowid"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()

        for row in rows:
            self._unlink_media_name(row["media_name"])
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute(
                        "DELETE FROM pending_media_deletions WHERE media_name = ?",
                        (row["media_name"],),
                    )

    def delete_scan(self, scan_id: str) -> bool:
        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    "SELECT thumbnail_path, original_path FROM scans WHERE scan_id = ?",
                    (scan_id,),
                ).fetchone()
                pending = connection.execute(
                    "SELECT 1 FROM pending_media_deletions WHERE scan_id = ? LIMIT 1",
                    (scan_id,),
                ).fetchone()
                if row is None and pending is None:
                    return False
                if row is not None:
                    self._queue_media(connection, scan_id, row)
                    connection.execute("DELETE FROM scans WHERE scan_id = ?", (scan_id,))
        self._drain_pending_deletions(scan_id)
        return True

    def clear(self) -> int:
        with closing(self._connect()) as connection:
            with connection:
                rows = connection.execute(
                    "SELECT scan_id, thumbnail_path, original_path FROM scans"
                ).fetchall()
                for row in rows:
                    self._queue_media(connection, row["scan_id"], row)
                connection.execute("DELETE FROM scans")
        self._drain_pending_deletions()
        return len(rows)
