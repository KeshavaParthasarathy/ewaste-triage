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


class AssessmentConflictError(RuntimeError):
    pass


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
                    original_path TEXT,
                    confirmation_json TEXT
                )
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(scans)")}
            if "confirmation_json" not in columns:
                connection.execute("ALTER TABLE scans ADD COLUMN confirmation_json TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assessments (
                    scan_id TEXT PRIMARY KEY REFERENCES scans(scan_id) ON DELETE CASCADE,
                    category_id TEXT NOT NULL,
                    template_version TEXT NOT NULL,
                    assessment_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS assessments_category_version ON assessments(category_id, template_version)"
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
            "confirmation": json.loads(row["confirmation_json"]) if row["confirmation_json"] else None,
        }

    def list_scans(self, limit: int | None = None) -> list[dict]:
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise ValueError("history limit must be a positive integer")
        query = "SELECT * FROM scans ORDER BY created_at DESC, rowid DESC"
        parameters = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._record(row) for row in rows]

    def get_scan(self, scan_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scans WHERE scan_id = ?", (scan_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    def set_confirmation(
        self,
        scan_id: str,
        accepted_class_name: str,
        *,
        known_category_ids: set[str] | None = None,
    ):
        """Store a validated user choice separately from immutable model evidence.

        Callers with a component reference store pass its canonical category IDs.
        Older callers without references retain the narrower model-top-k contract.
        """
        confirmation = {"accepted_class_name": accepted_class_name, "source": "user"}
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT prediction_json FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()
            if row is None:
                connection.rollback()
                return None
            assessment = connection.execute("SELECT category_id FROM assessments WHERE scan_id = ?", (scan_id,)).fetchone()
            if assessment is not None and assessment["category_id"] != accepted_class_name:
                connection.rollback()
                raise AssessmentConflictError("assessment category is immutable")
            prediction = json.loads(row["prediction_json"])
            allowed = known_category_ids
            if allowed is None:
                allowed = {
                    item.get("class_name") for item in prediction.get("topk", [])
                }
            if accepted_class_name not in allowed:
                connection.rollback()
                return False
            connection.execute("UPDATE scans SET confirmation_json = ? WHERE scan_id = ?", (json.dumps(confirmation, separators=(",", ":"), sort_keys=True), scan_id))
            connection.commit()
        return self.get_scan(scan_id)

    @staticmethod
    def _canonical_json(value: Mapping) -> str:
        return json.dumps(dict(value), allow_nan=False, separators=(",", ":"), sort_keys=True)

    def get_assessment(self, scan_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT assessment_json FROM assessments WHERE scan_id = ?", (scan_id,)
            ).fetchone()
        return json.loads(row["assessment_json"]) if row is not None else None

    def create_assessment(
        self,
        scan_id: str,
        template: Mapping,
        inputs: Mapping,
        component_overrides: Mapping,
        components: list[dict],
        *,
        return_created: bool = False,
    ) -> dict | None | tuple[dict | None, bool]:
        """Persist an immutable category-template snapshot once a category is confirmed."""
        def outcome(value, created):
            return (value, created) if return_created else value

        category_id = template.get("category_id")
        template_version = template.get("template_version")
        if not isinstance(category_id, str) or not isinstance(template_version, str):
            raise ValueError("template requires category_id and template_version")
        if not isinstance(components, list) or not components:
            raise ValueError("assessment components must not be empty")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                scan = connection.execute("SELECT confirmation_json FROM scans WHERE scan_id = ?", (scan_id,)).fetchone()
                if scan is None:
                    return outcome(None, False)
                confirmation = json.loads(scan["confirmation_json"]) if scan["confirmation_json"] else None
                if confirmation is None or confirmation.get("accepted_class_name") != category_id:
                    raise AssessmentConflictError("confirmed category changed before snapshot creation")
                existing = connection.execute(
                    "SELECT assessment_json FROM assessments WHERE scan_id = ?", (scan_id,)
                ).fetchone()
                if existing is not None:
                    return outcome(json.loads(existing["assessment_json"]), False)
                assessment = {
                    "scan_id": scan_id,
                    "category_id": category_id,
                    "template_version": template_version,
                    "template": dict(template),
                    "inputs": dict(inputs),
                    "component_overrides": dict(component_overrides),
                    "components": components,
                }
                updated_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
                connection.execute(
                    "INSERT INTO assessments(scan_id, category_id, template_version, assessment_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (scan_id, category_id, template_version, self._canonical_json(assessment), updated_at),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return outcome(assessment, True)

    def repair_incomplete_assessment(
        self,
        scan_id: str,
        expected_assessment: Mapping,
        inputs: Mapping,
        component_overrides: Mapping,
        components: list[dict],
    ) -> dict | None:
        """Atomically complete a legacy empty assessment without replacing its template."""
        if not isinstance(components, list) or not components:
            raise ValueError("assessment components must not be empty")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT assessment_json FROM assessments WHERE scan_id = ?",
                    (scan_id,),
                ).fetchone()
                if row is None:
                    connection.rollback()
                    return None
                assessment = json.loads(row["assessment_json"])
                if assessment.get("components"):
                    connection.rollback()
                    return assessment
                if assessment != dict(expected_assessment):
                    raise AssessmentConflictError(
                        "incomplete assessment changed before repair"
                    )
                assessment["inputs"] = dict(inputs)
                assessment["component_overrides"] = dict(component_overrides)
                assessment["components"] = components
                updated_at = datetime.now(timezone.utc).isoformat(
                    timespec="microseconds"
                )
                connection.execute(
                    "UPDATE assessments SET assessment_json = ?, updated_at = ? WHERE scan_id = ?",
                    (self._canonical_json(assessment), updated_at, scan_id),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return assessment

    def update_assessment(
        self,
        scan_id: str,
        inputs: Mapping,
        component_overrides: Mapping,
        components: list[dict] | None = None,
    ) -> dict | None:
        """Atomically replace only item-specific assessment state and derived results."""
        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    "SELECT assessment_json FROM assessments WHERE scan_id = ?", (scan_id,)
                ).fetchone()
                if row is None:
                    return None
                assessment = json.loads(row["assessment_json"])
                assessment["inputs"] = dict(inputs)
                assessment["component_overrides"] = dict(component_overrides)
                if components is not None:
                    if not isinstance(components, list) or not components:
                        raise ValueError("assessment components must not be empty")
                    assessment["components"] = components
                updated_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
                connection.execute(
                    "UPDATE assessments SET assessment_json = ?, updated_at = ? WHERE scan_id = ?",
                    (self._canonical_json(assessment), updated_at, scan_id),
                )
        return assessment

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
        try:
            os.unlink(self.media_dir / media_name)
        except FileNotFoundError:
            pass

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
