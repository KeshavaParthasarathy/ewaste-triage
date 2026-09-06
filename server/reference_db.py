"""Compile reviewed component-reference YAML into a read-only SQLite release artifact."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import sqlite3
import tempfile
import threading
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = 1
_PRESENCE_LABELS = {"standard", "common", "optional", "unknown"}
_SOURCE_FIELDS = {"source_id", "title", "publisher", "url", "reviewed_on", "evidence_grade"}
_CATEGORY_FIELDS = {"category_id", "display_name", "handling_note", "source_ids", "components", "rules"}
_COMPONENT_FIELDS = {
    "component_id", "display_name", "presence_label", "lifecycle", "source_ids",
    "evidence_grade", "reviewed_on", "safety_sensitive", "notes",
}
_RULE_FIELDS = {"rule_id", "text", "source_ids", "evidence_grade", "reviewed_on"}
_STARTUP_ERROR = "component reference database is unavailable or incompatible"
_REQUIRED_DATABASE_COLUMNS = {
    "metadata": {"key", "value"},
    "sources": {
        "source_id",
        "title",
        "publisher",
        "url",
        "reviewed_on",
        "evidence_grade",
    },
    "categories": {
        "category_id",
        "display_name",
        "template_version",
        "handling_note",
        "source_ids_json",
    },
    "components": {"component_id", "display_name"},
    "category_components": {
        "category_id",
        "component_id",
        "ordinal",
        "presence_label",
        "lifecycle_json",
        "source_ids_json",
        "evidence_grade",
        "reviewed_on",
        "safety_sensitive",
        "notes_json",
    },
    "rules": {
        "category_id",
        "rule_id",
        "text",
        "source_ids_json",
        "evidence_grade",
        "reviewed_on",
    },
}


class ReferenceValidationError(ValueError):
    """Raised when reviewed source data cannot safely become a release artifact."""

    def __init__(self, filename: str, record_path: str, message: str):
        self.filename = filename
        self.record_path = record_path
        super().__init__(f"{filename}: {record_path}: {message}")


class ReferenceStartupError(ValueError):
    """Raised when a compiled reference artifact is unusable at startup."""


@dataclasses.dataclass(frozen=True)
class ReferenceManifest:
    schema_version: int
    version: str
    content_sha256: str


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode, deep: bool = False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _read_yaml(directory: Path, filename: str) -> dict[str, Any]:
    path = directory / filename
    try:
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as error:
        raise ReferenceValidationError(filename, "$", str(error)) from error
    if not isinstance(document, dict):
        raise ReferenceValidationError(filename, "$", "must be a mapping")
    return document


def _fail(filename: str, path: str, message: str) -> None:
    raise ReferenceValidationError(filename, path, message)


def _mapping(value: Any, filename: str, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(filename, path, "must be a mapping")
    return value


def _list(value: Any, filename: str, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(filename, path, "must be a list")
    return value


def _string(value: Any, filename: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(filename, path, "must be a non-empty string")
    return value


def _known_fields(record: Mapping[str, Any], allowed: set[str], filename: str, path: str) -> None:
    unknown = sorted(set(record) - allowed)
    if unknown:
        _fail(filename, path, f"unknown field(s): {', '.join(unknown)}")


def _required_fields(record: Mapping[str, Any], required: set[str], filename: str, path: str) -> None:
    missing = sorted(required - set(record))
    if missing:
        _fail(filename, path, f"missing required field(s): {', '.join(missing)}")


def _source_ids(value: Any, known_sources: set[str], filename: str, path: str, *, required: bool) -> list[str]:
    if value is None and not required:
        return []
    values = _list(value, filename, path)
    if required and not values:
        _fail(filename, path, "must not be empty")
    result = []
    for index, source_id in enumerate(values):
        source_id = _string(source_id, filename, f"{path}[{index}]")
        if source_id not in known_sources:
            _fail(filename, path, f"references unknown source ID {source_id!r}")
        if source_id in result:
            _fail(filename, path, f"contains duplicate source ID {source_id!r}")
        result.append(source_id)
    return result


def _validate_source_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    filename = "sources.yaml"
    _known_fields(document, {"schema_version", "version", "sources"}, filename, "$")
    _required_fields(document, {"schema_version", "version", "sources"}, filename, "$")
    if document["schema_version"] != SCHEMA_VERSION:
        _fail(filename, "schema_version", f"must equal {SCHEMA_VERSION}")
    _string(document["version"], filename, "version")
    sources = _list(document["sources"], filename, "sources")
    if not sources:
        _fail(filename, "sources", "must not be empty")
    identifiers = set()
    normalized = []
    for index, value in enumerate(sources):
        path = f"sources[{index}]"
        source = _mapping(value, filename, path)
        _known_fields(source, _SOURCE_FIELDS, filename, path)
        _required_fields(source, _SOURCE_FIELDS, filename, path)
        normalized_source = {field: _string(source[field], filename, f"{path}.{field}") for field in _SOURCE_FIELDS}
        if not normalized_source["url"].startswith("https://"):
            _fail(filename, f"{path}.url", "must use https")
        source_id = normalized_source["source_id"]
        if source_id in identifiers:
            _fail(filename, f"{path}.source_id", f"duplicate source ID {source_id!r}")
        identifiers.add(source_id)
        normalized.append(normalized_source)
    return normalized


def _validate_component(
    value: Any, known_sources: set[str], filename: str, path: str
) -> dict[str, Any]:
    component = _mapping(value, filename, path)
    _known_fields(component, _COMPONENT_FIELDS, filename, path)
    _required_fields(component, {"component_id", "display_name", "presence_label"}, filename, path)
    component_id = _string(component["component_id"], filename, f"{path}.component_id")
    display_name = _string(component["display_name"], filename, f"{path}.display_name")
    presence_label = _string(component["presence_label"], filename, f"{path}.presence_label")
    if presence_label not in _PRESENCE_LABELS:
        _fail(filename, f"{path}.presence_label", "must be standard, common, optional, or unknown")
    lifecycle = component.get("lifecycle")
    safety_sensitive = component.get("safety_sensitive", False)
    if type(safety_sensitive) is not bool:
        _fail(filename, f"{path}.safety_sensitive", "must be boolean")
    provenance_required = lifecycle is not None or safety_sensitive
    source_ids = _source_ids(
        component.get("source_ids"),
        known_sources,
        filename,
        f"{path}.source_ids",
        required=provenance_required,
    )
    evidence_grade = component.get("evidence_grade")
    reviewed_on = component.get("reviewed_on")
    if lifecycle is not None:
        lifecycle = _mapping(lifecycle, filename, f"{path}.lifecycle")
        allowed = {"metric", "minimum", "maximum", "capacity_percent"}
        _known_fields(lifecycle, allowed, filename, f"{path}.lifecycle")
        _required_fields(lifecycle, {"metric", "minimum", "maximum"}, filename, f"{path}.lifecycle")
        metric = _string(lifecycle["metric"], filename, f"{path}.lifecycle.metric")
        minimum, maximum = lifecycle["minimum"], lifecycle["maximum"]
        for field, number in (("minimum", minimum), ("maximum", maximum)):
            if type(number) not in (int, float) or not math.isfinite(number):
                _fail(filename, f"{path}.lifecycle.{field}", "must be a finite number")
        if minimum <= 0 or maximum < minimum:
            _fail(filename, f"{path}.lifecycle", "minimum and maximum must be positive ordered numbers")
        lifecycle = {"metric": metric, "minimum": minimum, "maximum": maximum}
        if "capacity_percent" in component.get("lifecycle", {}):
            capacity_percent = component["lifecycle"]["capacity_percent"]
            if (
                type(capacity_percent) not in (int, float)
                or not math.isfinite(capacity_percent)
                or not 0 < capacity_percent <= 100
            ):
                _fail(filename, f"{path}.lifecycle.capacity_percent", "must be a percentage from 1 through 100")
            lifecycle["capacity_percent"] = capacity_percent
    if provenance_required:
        evidence_grade = _string(evidence_grade, filename, f"{path}.evidence_grade")
        reviewed_on = _string(reviewed_on, filename, f"{path}.reviewed_on")
    elif evidence_grade is not None or reviewed_on is not None:
        _fail(filename, path, "evidence_grade and reviewed_on require a non-null lifecycle")
    notes = component.get("notes", [])
    notes = [_string(note, filename, f"{path}.notes[{index}]") for index, note in enumerate(_list(notes, filename, f"{path}.notes"))]
    return {
        "component_id": component_id,
        "display_name": display_name,
        "presence_label": presence_label,
        "lifecycle": lifecycle,
        "source_ids": source_ids,
        "evidence_grade": evidence_grade,
        "reviewed_on": reviewed_on,
        "safety_sensitive": safety_sensitive,
        "notes": notes,
    }


def _validate_rule(value: Any, known_sources: set[str], filename: str, path: str) -> dict[str, Any]:
    rule = _mapping(value, filename, path)
    _known_fields(rule, _RULE_FIELDS, filename, path)
    _required_fields(rule, _RULE_FIELDS, filename, path)
    return {
        "rule_id": _string(rule["rule_id"], filename, f"{path}.rule_id"),
        "text": _string(rule["text"], filename, f"{path}.text"),
        "source_ids": _source_ids(rule["source_ids"], known_sources, filename, f"{path}.source_ids", required=True),
        "evidence_grade": _string(rule["evidence_grade"], filename, f"{path}.evidence_grade"),
        "reviewed_on": _string(rule["reviewed_on"], filename, f"{path}.reviewed_on"),
    }


def _validate_components_document(document: dict[str, Any], known_sources: set[str]) -> list[dict[str, Any]]:
    filename = "device_components.yaml"
    _known_fields(document, {"schema_version", "version", "categories"}, filename, "$")
    _required_fields(document, {"schema_version", "version", "categories"}, filename, "$")
    if document["schema_version"] != SCHEMA_VERSION:
        _fail(filename, "schema_version", f"must equal {SCHEMA_VERSION}")
    _string(document["version"], filename, "version")
    categories = _list(document["categories"], filename, "categories")
    if not categories:
        _fail(filename, "categories", "must not be empty")
    normalized = []
    category_ids = set()
    for index, value in enumerate(categories):
        path = f"categories[{index}]"
        category = _mapping(value, filename, path)
        _known_fields(category, _CATEGORY_FIELDS, filename, path)
        _required_fields(category, _CATEGORY_FIELDS, filename, path)
        category_id = _string(category["category_id"], filename, f"{path}.category_id")
        if category_id in category_ids:
            _fail(filename, f"{path}.category_id", f"duplicate category ID {category_id!r}")
        category_ids.add(category_id)
        components = []
        component_ids = set()
        for component_index, component in enumerate(_list(category["components"], filename, f"{path}.components")):
            normalized_component = _validate_component(component, known_sources, filename, f"{path}.components[{component_index}]")
            if normalized_component["component_id"] in component_ids:
                _fail(filename, f"{path}.components[{component_index}].component_id", "duplicate component ID in category")
            component_ids.add(normalized_component["component_id"])
            components.append(normalized_component)
        if not components:
            _fail(filename, f"{path}.components", "must not be empty")
        rules = [
            _validate_rule(rule, known_sources, filename, f"{path}.rules[{rule_index}]")
            for rule_index, rule in enumerate(_list(category["rules"], filename, f"{path}.rules"))
        ]
        normalized.append({
            "category_id": category_id,
            "display_name": _string(category["display_name"], filename, f"{path}.display_name"),
            "handling_note": _string(category["handling_note"], filename, f"{path}.handling_note"),
            "source_ids": _source_ids(category["source_ids"], known_sources, filename, f"{path}.source_ids", required=True),
            "components": components,
            "rules": rules,
        })
    return normalized


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE sources (
            source_id TEXT PRIMARY KEY, title TEXT NOT NULL, publisher TEXT NOT NULL,
            url TEXT NOT NULL, reviewed_on TEXT NOT NULL, evidence_grade TEXT NOT NULL
        );
        CREATE TABLE categories (
            category_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            template_version TEXT NOT NULL, handling_note TEXT NOT NULL,
            source_ids_json TEXT NOT NULL
        );
        CREATE TABLE components (component_id TEXT PRIMARY KEY, display_name TEXT NOT NULL);
        CREATE TABLE category_components (
            category_id TEXT NOT NULL REFERENCES categories(category_id),
            component_id TEXT NOT NULL REFERENCES components(component_id),
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0), presence_label TEXT NOT NULL,
            lifecycle_json TEXT, source_ids_json TEXT NOT NULL, evidence_grade TEXT,
            reviewed_on TEXT, safety_sensitive INTEGER NOT NULL CHECK (safety_sensitive IN (0, 1)),
            notes_json TEXT NOT NULL, PRIMARY KEY (category_id, component_id),
            UNIQUE (category_id, ordinal)
        );
        CREATE TABLE rules (
            category_id TEXT NOT NULL REFERENCES categories(category_id), rule_id TEXT NOT NULL,
            text TEXT NOT NULL, source_ids_json TEXT NOT NULL, evidence_grade TEXT NOT NULL,
            reviewed_on TEXT NOT NULL, PRIMARY KEY (category_id, rule_id)
        );
    """)


def _write_database(
    path: Path, manifest: ReferenceManifest, sources: list[dict[str, Any]], categories: list[dict[str, Any]]
) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            [("schema_version", str(manifest.schema_version)), ("version", manifest.version), ("content_sha256", manifest.content_sha256)],
        )
        connection.executemany(
            "INSERT INTO sources VALUES (:source_id, :title, :publisher, :url, :reviewed_on, :evidence_grade)", sources
        )
        seen_components = set()
        for category in categories:
            connection.execute(
                "INSERT INTO categories VALUES (?, ?, ?, ?, ?)",
                (category["category_id"], category["display_name"], manifest.version, category["handling_note"], _json(category["source_ids"])),
            )
            for ordinal, component in enumerate(category["components"]):
                if component["component_id"] not in seen_components:
                    connection.execute("INSERT INTO components VALUES (?, ?)", (component["component_id"], component["display_name"]))
                    seen_components.add(component["component_id"])
                connection.execute(
                    """INSERT INTO category_components VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (category["category_id"], component["component_id"], ordinal, component["presence_label"],
                     _json(component["lifecycle"]) if component["lifecycle"] is not None else None,
                     _json(component["source_ids"]), component["evidence_grade"], component["reviewed_on"],
                     int(component["safety_sensitive"]), _json(component["notes"])),
                )
            for rule in category["rules"]:
                connection.execute(
                    "INSERT INTO rules VALUES (?, ?, ?, ?, ?, ?)",
                    (category["category_id"], rule["rule_id"], rule["text"], _json(rule["source_ids"]), rule["evidence_grade"], rule["reviewed_on"]),
                )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")


def _fsync_path(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def compile_reference(source_dir: Path, destination: Path) -> ReferenceManifest:
    """Validate reviewed YAML and atomically replace *destination* with its release DB."""
    source_dir, destination = Path(source_dir), Path(destination)
    source_document = _read_yaml(source_dir, "sources.yaml")
    component_document = _read_yaml(source_dir, "device_components.yaml")
    sources = _validate_source_document(source_document)
    if component_document.get("version") != source_document.get("version"):
        _fail("device_components.yaml", "version", "must match sources.yaml version")
    categories = _validate_components_document(component_document, {source["source_id"] for source in sources})
    canonical = _json({"sources": sources, "categories": categories})
    manifest = ReferenceManifest(SCHEMA_VERSION, component_document["version"], hashlib.sha256(canonical.encode()).hexdigest())

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        _write_database(temporary, manifest, sources, categories)
        _fsync_path(temporary)
        os.replace(temporary, destination)
        try:
            directory_descriptor = os.open(destination.parent, os.O_RDONLY)
        except OSError:
            directory_descriptor = None
        if directory_descriptor is not None:
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return manifest


class ReferenceStore:
    """Query a compiled component release without permitting mutations."""

    def __init__(self, database_path: Path):
        try:
            path = Path(database_path).resolve()
        except (OSError, RuntimeError, TypeError) as exc:
            raise ReferenceStartupError(_STARTUP_ERROR) from exc
        self._lock = threading.RLock()
        connection = None
        try:
            connection = sqlite3.connect(
                f"{path.as_uri()}?mode=ro", uri=True, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            self._connection = connection
            self._manifest = self._validate_startup()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            if connection is not None:
                connection.close()
            raise ReferenceStartupError(_STARTUP_ERROR) from exc

    def _validate_startup(self) -> ReferenceManifest:
        quick_check = [row[0] for row in self._connection.execute("PRAGMA quick_check")]
        if quick_check != ["ok"]:
            raise ValueError("reference database integrity check failed")

        tables = {
            row["name"]
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not set(_REQUIRED_DATABASE_COLUMNS) <= tables:
            raise ValueError("reference database is missing required tables")
        for table, required_columns in _REQUIRED_DATABASE_COLUMNS.items():
            columns = {
                row["name"]
                for row in self._connection.execute(f"PRAGMA table_info({table})")
            }
            if not required_columns <= columns:
                raise ValueError(f"reference database table {table} is incompatible")

        metadata_rows = self._connection.execute(
            "SELECT key, value FROM metadata"
        ).fetchall()
        metadata = {row["key"]: row["value"] for row in metadata_rows}
        if set(metadata) != {"schema_version", "version", "content_sha256"}:
            raise ValueError("reference database metadata is incomplete")
        if int(metadata["schema_version"]) != SCHEMA_VERSION:
            raise ValueError("unsupported reference database schema")
        version = metadata["version"]
        content_sha256 = metadata["content_sha256"]
        if not isinstance(version, str) or not version.strip():
            raise ValueError("reference database version is invalid")
        if (
            not isinstance(content_sha256, str)
            or len(content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in content_sha256)
        ):
            raise ValueError("reference database content hash is invalid")

        for table in ("sources", "categories", "components", "category_components"):
            count = self._connection.execute(
                f"SELECT COUNT(*) AS count FROM {table}"
            ).fetchone()["count"]
            if count <= 0:
                raise ValueError(f"reference database table {table} is empty")
        category_without_components = self._connection.execute(
            """SELECT c.category_id
                 FROM categories c
                 LEFT JOIN category_components cc USING (category_id)
                GROUP BY c.category_id
               HAVING COUNT(cc.component_id) = 0
                LIMIT 1"""
        ).fetchone()
        if category_without_components is not None:
            raise ValueError("reference database category has no components")
        if self._connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("reference database has broken relationships")

        known_source_ids = {
            row["source_id"]
            for row in self._connection.execute("SELECT source_id FROM sources")
        }
        if any(
            not isinstance(source_id, str) or not source_id
            for source_id in known_source_ids
        ):
            raise ValueError("reference database has an invalid source ID")
        source_id_fields = (
            ("categories", "source_ids_json", True),
            ("category_components", "source_ids_json", False),
            ("rules", "source_ids_json", True),
        )
        for table, column, required in source_id_fields:
            rows = self._connection.execute(f"SELECT {column} FROM {table}")
            for row in rows:
                source_ids = json.loads(row[column])
                if not isinstance(source_ids, list) or (required and not source_ids):
                    raise ValueError(
                        f"reference database {table}.{column} has invalid data"
                    )
                if any(
                    not isinstance(source_id, str)
                    or not source_id
                    or source_id not in known_source_ids
                    for source_id in source_ids
                ) or len(source_ids) != len(set(source_ids)):
                    raise ValueError(
                        f"reference database {table}.{column} has invalid source IDs"
                    )

        json_fields = (
            ("category_components", "lifecycle_json", dict, True),
            ("category_components", "notes_json", list, False),
        )
        for table, column, expected_type, nullable in json_fields:
            rows = self._connection.execute(f"SELECT {column} FROM {table}")
            for row in rows:
                value = row[column]
                if value is None and nullable:
                    continue
                decoded = json.loads(value)
                if not isinstance(decoded, expected_type):
                    raise ValueError(
                        f"reference database {table}.{column} has invalid data"
                    )

        return ReferenceManifest(SCHEMA_VERSION, version, content_sha256)

    def _metadata(self, key: str) -> str:
        with self._lock:
            row = self._connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise ValueError(f"component reference database is missing {key!r} metadata")
        return row["value"]

    @property
    def manifest(self) -> ReferenceManifest:
        return self._manifest

    def list_categories(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT category_id, display_name, template_version, handling_note, source_ids_json FROM categories ORDER BY category_id"
            ).fetchall()
        return [
            {"category_id": row["category_id"], "display_name": row["display_name"], "template_version": row["template_version"],
             "handling_note": row["handling_note"], "source_ids": json.loads(row["source_ids_json"])}
            for row in rows
        ]

    def get_category(self, category_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT category_id, display_name, template_version, handling_note, source_ids_json FROM categories WHERE category_id = ?", (category_id,)
            ).fetchone()
        if row is None:
            return None
        return {"category_id": row["category_id"], "display_name": row["display_name"], "template_version": row["template_version"],
                "handling_note": row["handling_note"], "source_ids": json.loads(row["source_ids_json"])}

    def snapshot(self, category_id: str) -> dict[str, Any]:
        category = self.get_category(category_id)
        if category is None:
            raise KeyError(category_id)
        with self._lock:
            component_rows = self._connection.execute(
            """SELECT cc.component_id, c.display_name, cc.presence_label, cc.lifecycle_json,
                      cc.source_ids_json, cc.evidence_grade, cc.reviewed_on, cc.safety_sensitive, cc.notes_json
               FROM category_components cc JOIN components c USING (component_id)
               WHERE cc.category_id = ? ORDER BY cc.ordinal""",
            (category_id,),
            ).fetchall()
            rules = self._connection.execute(
                "SELECT rule_id, text, source_ids_json, evidence_grade, reviewed_on FROM rules WHERE category_id = ? ORDER BY rule_id", (category_id,)
            ).fetchall()
        return {
            **category,
            "schema_version": self.manifest.schema_version,
            "components": [
                {"component_id": row["component_id"], "display_name": row["display_name"], "presence_label": row["presence_label"],
                 "lifecycle": json.loads(row["lifecycle_json"]) if row["lifecycle_json"] is not None else None,
                 "source_ids": json.loads(row["source_ids_json"]), "evidence_grade": row["evidence_grade"],
                 "reviewed_on": row["reviewed_on"], "safety_sensitive": bool(row["safety_sensitive"]), "notes": json.loads(row["notes_json"])}
                for row in component_rows
            ],
            "rules": [
                {"rule_id": row["rule_id"], "text": row["text"], "source_ids": json.loads(row["source_ids_json"]),
                 "evidence_grade": row["evidence_grade"], "reviewed_on": row["reviewed_on"]}
                for row in rules
            ],
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
