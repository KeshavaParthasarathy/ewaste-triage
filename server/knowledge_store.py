"""Offline, descriptor-bound, read-only queries over released schema-3 bundles.

The external SQLite file is opened mode=ro, then immediately detached into an
in-memory snapshot of the captured descriptor bytes. No query is authorized by
a pathname hash alone. Administrator schema/compiler modules are not imported.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from functools import wraps
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import unicodedata

from server.evidence_types import (
    AssociationStatus, BatteryArchitecture, CanonicalIdentityScope, CategorySnapshot,
    ComponentAssociationSnapshot, EvidenceLevel, HazardSeverity, HazardSnapshot,
    IdentityKind, IdentityRecordSnapshot, KnowledgeManifest, LifecycleEndpointKind,
    LifecycleRecordSnapshot, MarketState, PolicyBundleSnapshot, PolicyRuleSnapshot,
    RecommendationValue, RELEASED_CATEGORY_IDS, ResolutionTier, ScopeKind, SourceSnapshot,
)


class KnowledgeStartupError(RuntimeError):
    """The released artifact could not be safely opened or validated."""


_STARTUP_MESSAGE = "knowledge bundle is unavailable or incompatible"
_TABLE_ORDER = (
    "metadata", "sources", "categories", "subtypes", "variants", "identities",
    "identity_aliases", "identity_tokens", "identity_variants", "lifecycle_records",
    "lifecycle_required_variants", "lifecycle_excluded_variants", "lifecycle_assumptions",
    "industry_averages", "lifecycle_limitations", "components", "component_templates",
    "component_associations", "component_association_notes", "hazards", "hazard_triggers",
    "hazard_actions", "policy_rules", "policy_predicates", "coverage_unknowns", "claim_sources",
)
# Schema-3's frozen sqlite_master (type, name, tbl_name, sql), sorted by those
# four columns and encoded with _json_bytes. Includes every DDL constraint and
# automatic index, excludes physical root pages. Pinned to the accepted producer
# at edea04e; changing the wire schema requires an explicit consumer update.
_SCHEMA_SHA256 = "9e46f4501848c75de67d7b7cbe806217d8d31f51b6964ffbd85792293f061c74"
_METADATA_KEYS = {
    "schema_version", "bundle_version", "identity_catalog_version", "policy_revision",
    "content_sha256", "coverage_sha256",
}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9_.-]*\Z")
_SCOPE_ORDER = {"category": 0, "subtype": 1, "family": 2, "model": 3}


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


class _CapturedFile:
    """Keep every ancestor anchored, reject links, and recheck the same entries."""

    def __init__(self, path: Path, stack: ExitStack):
        path = Path(path)
        _require(".." not in path.parts, "parent traversal")
        self.path = path.absolute()
        parts = self.path.parts
        _require(len(parts) > 1, "missing file name")
        descriptor = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, descriptor)
        self.entries = []
        for index, name in enumerate(parts[1:]):
            final = index == len(parts) - 2
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if not final:
                flags |= os.O_DIRECTORY
            child = os.open(name, flags, dir_fd=descriptor)
            stack.callback(os.close, child)
            info = os.fstat(child)
            _require(stat.S_ISREG(info.st_mode) if final else stat.S_ISDIR(info.st_mode),
                     "not a regular file/directory")
            self.entries.append((descriptor, name, child, _identity(info)))
            descriptor = child
        self.descriptor = descriptor
        self.parent_descriptor = self.entries[-1][0]
        self.name = parts[-1]

    def read(self) -> bytes:
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        chunks = []
        while chunk := os.read(self.descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)

    def recheck(self) -> None:
        for parent, name, child, identity in self.entries:
            _require(_identity(os.fstat(child)) == identity, "descriptor identity changed")
            _require(_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == identity,
                     "path identity changed")

    def reject_sidecars(self) -> None:
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                os.stat(self.name + suffix, dir_fd=self.parent_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ValueError("SQLite sidecar is prohibited")


@dataclass(frozen=True)
class _ComponentTemplateLayer:
    template_id: str
    associations: tuple[ComponentAssociationSnapshot, ...]


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            if self._closed:
                raise RuntimeError("knowledge store is closed")
            return method(self, *args, **kwargs)
    return call


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def _search_rank(field: str, query: str) -> int | None:
    field = _normalized(field)
    if field == query:
        return 0
    if field.startswith(query):
        return 1
    query_tokens, field_tokens = query.split(), field.split()
    for start in range(1, len(field_tokens) - len(query_tokens) + 1):
        if all(token.startswith(prefix) for token, prefix in
               zip(field_tokens[start:], query_tokens)):
            return 2
    return None


def _coverage(data: bytes, manifest: KnowledgeManifest) -> None:
    report = json.loads(data)
    _require(type(report) is dict and set(report) == {
        "schema_version", "bundle_version", "knowledge_content_sha256", "summary", "claims"},
        "coverage fields")
    _require(type(report["schema_version"]) is int and report["schema_version"] == 1,
             "coverage schema")
    _require(report["bundle_version"] == manifest.bundle_version and
             report["knowledge_content_sha256"] == manifest.content_sha256, "coverage linkage")
    summary = report["summary"]
    _require(type(summary) is dict and set(summary) == {
        "categories", "canonical_identities", "subtypes", "lifecycle_records", "industry_averages",
        "component_templates", "modern_overlays", "legacy_overlays", "hazard_records",
        "reviewed_claims", "unknown_claims"}, "coverage summary fields")
    _require(all(type(v) is int and v >= 0 for v in summary.values()), "coverage counts")
    _require(type(report["claims"]) is list, "coverage claims")
    keys, counts = [], Counter()
    for claim in report["claims"]:
        _require(type(claim) is dict and set(claim) == {
            "category_id", "claim_kind", "claim_id", "evidence_level", "source_state",
            "source_ids", "unknown_reason"}, "coverage claim fields")
        _require(claim["category_id"] in RELEASED_CATEGORY_IDS, "coverage category")
        _require(claim["claim_kind"] in {
            "subtype", "variant", "identity", "specific_lifecycle", "industry_average",
            "component_association", "hazard"}, "coverage kind")
        _require(type(claim["claim_id"]) is str and _ID.fullmatch(claim["claim_id"]) is not None,
                 "coverage claim ID")
        sources = claim["source_ids"]
        _require(type(sources) is list and all(type(s) is str and _ID.fullmatch(s) for s in sources),
                 "coverage source IDs")
        _require(sources == sorted(set(sources)), "coverage source ordering")
        state = claim["source_state"]
        if state == "reviewed":
            _require(claim["evidence_level"] in {"A", "B", "C", "D"} and bool(sources)
                     and claim["unknown_reason"] is None, "reviewed coverage")
            counts[claim["claim_kind"]] += 1
        elif state == "unknown":
            reason = claim["unknown_reason"]
            _require(claim["evidence_level"] is None and not sources and type(reason) is str
                     and bool(reason.strip()) and reason.strip() == reason
                     and unicodedata.normalize("NFC", reason) == reason
                     and not any(unicodedata.category(c).startswith("C") for c in reason),
                     "unknown coverage")
        else:
            raise ValueError("coverage source state")
        counts[state] += 1
        keys.append((claim["category_id"], claim["claim_kind"], claim["claim_id"]))
    _require(keys == sorted(set(keys)), "coverage claim ordering")
    for field, kind in {
        "canonical_identities": "identity", "subtypes": "subtype",
        "lifecycle_records": "specific_lifecycle", "industry_averages": "industry_average",
        "hazard_records": "hazard", "reviewed_claims": "reviewed", "unknown_claims": "unknown",
    }.items():
        _require(summary[field] == counts[kind], "coverage count mismatch")
    _require(_json_bytes(report) + b"\n" == data, "noncanonical coverage bytes")
    _require(_sha256(data) == manifest.coverage_sha256, "coverage hash")


class KnowledgeStore:
    def __init__(
        self, database_path: Path, coverage_path: Path | None = None, *,
        expected_sha256: str | None = None, expected_content_sha256: str | None = None,
        expected_coverage_sha256: str | None = None, expected_schema_version: int | None = None,
        expected_bundle_version: str | None = None,
        expected_identity_catalog_version: str | None = None,
        expected_policy_revision: str | None = None,
    ):
        self._lock = threading.RLock()
        self._closed = True
        self._connection = None
        with self._lock:
            try:
                _require(sqlite3.threadsafety >= 1, "unsupported SQLite threading")
                _require(hasattr(sqlite3.Connection, "deserialize") and
                         hasattr(sqlite3.Connection, "serialize"), "SQLite snapshot API unavailable")
                with ExitStack() as handles:
                    database = _CapturedFile(database_path, handles)
                    coverage = _CapturedFile(coverage_path if coverage_path is not None else
                                             Path(database_path).with_name("evidence-coverage.json"), handles)
                    database.reject_sidecars()
                    captured = database.read()
                    coverage_bytes = coverage.read()
                    _require(captured[:16] == b"SQLite format 3\x00" and captured[18:20] == b"\x01\x01",
                             "unsupported SQLite file format")
                    raw_hash = _sha256(captured)
                    if expected_sha256 is not None:
                        _require(raw_hash == expected_sha256, "external hash")
                    # Opening the anchored descriptor does not authorize content reads.
                    # Deserialize is deliberately the first operation on the connection.
                    self._connection = sqlite3.connect(
                        f"file:/dev/fd/{database.descriptor}?mode=ro&immutable=1",
                        uri=True, check_same_thread=False,
                    )
                    self._connection.deserialize(captured)
                    self._execute("PRAGMA query_only = ON")
                    _require(self._execute("PRAGMA query_only") == [(1,)], "query_only unavailable")
                    self._execute("PRAGMA trusted_schema = OFF")
                    _require(self._connection.serialize() == captured, "snapshot bytes differ")
                    self._manifest = self._validate_snapshot()
                    for name, expected in (
                        ("content_sha256", expected_content_sha256),
                        ("coverage_sha256", expected_coverage_sha256),
                        ("schema_version", expected_schema_version),
                        ("bundle_version", expected_bundle_version),
                        ("identity_catalog_version", expected_identity_catalog_version),
                        ("policy_revision", expected_policy_revision),
                    ):
                        if expected is not None:
                            actual = getattr(self._manifest, name)
                            _require(type(actual) is type(expected) and actual == expected,
                                     "release expectation mismatch")
                    _coverage(coverage_bytes, self._manifest)
                    _require(database.read() == captured and coverage.read() == coverage_bytes,
                             "captured artifact changed")
                    database.reject_sidecars()
                    database.recheck()
                    coverage.recheck()
                self._closed = False
            except BaseException as exc:
                if self._connection is not None:
                    self._connection.close()
                if isinstance(exc, Exception):
                    raise KnowledgeStartupError(_STARTUP_MESSAGE) from exc
                raise

    def _execute(self, sql: str, parameters: tuple = ()) -> list[tuple]:
        # Every caller is under _lock, including startup and complete fetching.
        cursor = self._connection.execute(sql, parameters)
        try:
            return cursor.fetchall()
        finally:
            cursor.close()

    def _validate_snapshot(self) -> KnowledgeManifest:
        signature = self._execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                                  "ORDER BY type, name, tbl_name, sql")
        _require(_sha256(_json_bytes(signature)) == _SCHEMA_SHA256, "schema objects differ")
        tables = self._execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid")
        _require(tuple(r[0] for r in tables) == _TABLE_ORDER, "table order differs")
        _require(self._execute("PRAGMA quick_check") == [("ok",)], "SQLite integrity")
        _require(not self._execute("PRAGMA foreign_key_check"), "SQLite foreign keys")
        metadata = dict(self._execute("SELECT key, value FROM metadata"))
        _require(set(metadata) == _METADATA_KEYS and metadata["schema_version"] == "3", "metadata")
        for key in ("bundle_version", "identity_catalog_version", "policy_revision"):
            _require(_SEMVER.fullmatch(metadata[key]) is not None, "release version")
        for key in ("content_sha256", "coverage_sha256"):
            _require(_HASH.fullmatch(metadata[key]) is not None, "metadata hash")
        _require(dict(self._execute("SELECT category_id, release_order FROM categories")) ==
                 dict(zip(RELEASED_CATEGORY_IDS, range(5))), "released categories")
        logical_tables = []
        for table in _TABLE_ORDER:
            # Schema fingerprint has already authenticated column/PK/affinity/DDL.
            info = self._execute(f'PRAGMA table_info("{table}")')
            columns = [row[1] for row in info]
            primary = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
            order = ",".join('"' + column + '"' for column in primary)
            rows = self._execute(f'SELECT * FROM "{table}" ORDER BY {order}')
            for row in rows:
                for value, column in zip(row, info):
                    if value is None:
                        _require(not column[3], "null in required column")
                    else:
                        expected = {"TEXT": str, "INTEGER": int, "REAL": float}[column[2]]
                        _require(type(value) is expected, "invalid SQLite scalar")
                        if expected is float:
                            _require(math.isfinite(value), "nonfinite SQLite scalar")
            if table == "metadata":
                rows = [row for row in rows if row[0] not in {"content_sha256", "coverage_sha256"}]
            logical_tables.append({"name": table, "columns": columns, "rows": rows})
        digest = _sha256(_json_bytes({"format": "ewaste-knowledge-logical-v1", "tables": logical_tables}))
        _require(digest == metadata["content_sha256"], "logical content hash")
        return KnowledgeManifest(3, metadata["bundle_version"], metadata["identity_catalog_version"],
                                 metadata["policy_revision"], digest, metadata["coverage_sha256"])

    @property
    def manifest(self) -> KnowledgeManifest:
        return self._manifest

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> KnowledgeStore:
        with self._lock:
            if self._closed:
                raise RuntimeError("knowledge store is closed")
            return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _rows(self, table: str, where: str = "1", parameters: tuple = (), order: str = "") -> list[dict]:
        # Table/where/order identifiers are internal literals; external values are bound.
        cursor = self._connection.execute(f'SELECT * FROM "{table}" WHERE {where}' +
                                          (f" ORDER BY {order}" if order else ""), parameters)
        try:
            names = [item[0] for item in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def _children(self, table: str, key: str, value: str, column: str, *,
                  group_key: str | None = None, group: str | None = None) -> tuple:
        where, params = f"{key}=?", (value,)
        if group_key is not None:
            where += f" AND {group_key}=?"
            params += (group,)
        return tuple(row[column] for row in self._rows(table, where, params, "ordinal"))

    def _sources(self, kind: str, category: str, claim: str) -> tuple[SourceSnapshot, ...]:
        return tuple(self._source(row) for row in self._rows("sources",
            "source_id IN (SELECT source_id FROM claim_sources WHERE claim_kind=? AND category_key=? AND claim_id=?)",
            (kind, category, claim), "source_id"))

    @staticmethod
    def _source(row: dict) -> SourceSnapshot:
        row = dict(row)
        for field in ("publication_or_revision_date", "accessed_on", "reviewed_on"):
            row[field] = date.fromisoformat(row[field])
        return SourceSnapshot(**row)

    @_locked
    def list_categories(self) -> tuple[CategorySnapshot, ...]:
        return tuple(CategorySnapshot(row["category_id"], row["display_name"])
                     for row in self._rows("categories", order="release_order"))

    @_locked
    def get_category(self, category_id: str) -> CategorySnapshot | None:
        rows = self._rows("categories", "category_id=?", (category_id,))
        return CategorySnapshot(rows[0]["category_id"], rows[0]["display_name"]) if rows else None

    def _identity_record(self, row: dict) -> IdentityRecordSnapshot:
        row = dict(row)
        key, category = row["identity_id"], row["category_id"]
        row.pop("evidence_level")
        row["identity_kind"] = IdentityKind(row["identity_kind"])
        row["market_state"] = MarketState(row["market_state"])
        row["battery_architecture"] = BatteryArchitecture(row["battery_architecture"])
        for field in ("applicable_from", "applicable_to"):
            row[field] = date.fromisoformat(row[field]) if row[field] is not None else None
        row["aliases"] = self._children("identity_aliases", "identity_id", key, "alias")
        row["distinguishing_tokens"] = self._children("identity_tokens", "identity_id", key, "token")
        row["variant_ids"] = self._children("identity_variants", "identity_id", key, "variant_id")
        row["sources"] = self._sources("identity", category, key)
        return IdentityRecordSnapshot(**row)

    @_locked
    def get_identity(self, identity_id: str) -> IdentityRecordSnapshot | None:
        rows = self._rows("identities", "identity_id=?", (identity_id,))
        return self._identity_record(rows[0]) if rows else None

    @_locked
    def search_identities(self, text: str, *, category_id: str | None = None,
                          limit: int = 20) -> tuple[IdentityRecordSnapshot, ...]:
        query = _normalized(text)
        if not query or limit <= 0:
            return ()
        rows = self._rows("identities", "category_id=?" if category_id is not None else "1",
                          (category_id,) if category_id is not None else ())
        matches = []
        for row in rows:
            identity = self._identity_record(row)
            ranks = [_search_rank(field, query) for field in
                     (identity.display_name, *identity.aliases, *identity.distinguishing_tokens)]
            ranks = [rank for rank in ranks if rank is not None]
            if ranks:
                matches.append((min(ranks), identity.identity_id, identity))
        return tuple(match[2] for match in sorted(matches, key=lambda m: m[:2])[:limit])

    @_locked
    def identity_scope(self, identity_id: str) -> CanonicalIdentityScope:
        record = self.get_identity(identity_id)
        if record is None:
            raise KeyError(identity_id)
        return CanonicalIdentityScope(record.category_id, record.subtype_id, record.family_id,
            record.model_id, record.variant_ids,
            record.model_year_from if record.model_year_from == record.model_year_to else None,
            record.applicable_from if record.applicable_from == record.applicable_to else None)

    def _scoped(self, table: str, scope: CanonicalIdentityScope) -> list[dict]:
        keys = {"category": scope.category_id, "subtype": scope.subtype_id,
                "family": scope.family_id, "model": scope.model_id}
        return [row for row in self._rows(table, "category_id=?", (scope.category_id,))
                if row["scope_id"] == keys.get(row["scope_kind"])]

    @_locked
    def lifecycle_candidates(self, scope: CanonicalIdentityScope) -> tuple[LifecycleRecordSnapshot, ...]:
        result = []
        for row in sorted(self._scoped("lifecycle_records", scope), key=lambda r: r["record_id"]):
            key, category = row["record_id"], row.pop("category_id")
            row["resolution_tier"] = ResolutionTier(row["resolution_tier"])
            row["scope_kind"] = ScopeKind(row["scope_kind"])
            row["endpoint_kind"] = LifecycleEndpointKind(row["endpoint_kind"])
            row["evidence_level"] = EvidenceLevel(row["evidence_level"])
            for field in ("applicable_from", "applicable_to"):
                row[field] = date.fromisoformat(row[field]) if row[field] is not None else None
            for field, table, column in (
                ("required_variant_ids", "lifecycle_required_variants", "variant_id"),
                ("excluded_variant_ids", "lifecycle_excluded_variants", "variant_id"),
                ("assumptions", "lifecycle_assumptions", "assumption"),
                ("limitations", "lifecycle_limitations", "limitation"),
            ):
                row[field] = self._children(table, "record_id", key, column)
            extensions = self._rows("industry_averages", "record_id=?", (key,))
            for field in ("population_definition", "publication_period", "methodology", "uncertainty"):
                row[field] = extensions[0][field] if extensions else None
            kind = "industry_average" if row["resolution_tier"] == ResolutionTier.INDUSTRY_AVERAGE else "specific_lifecycle"
            row["sources"] = self._sources(kind, category, key)
            result.append(LifecycleRecordSnapshot(**row))
        return tuple(result)

    @_locked
    def component_layers(self, scope: CanonicalIdentityScope) -> tuple[_ComponentTemplateLayer, ...]:
        result = []
        templates = sorted(self._scoped("component_templates", scope),
                           key=lambda r: (_SCOPE_ORDER[r["scope_kind"]], r["application_order"], r["template_id"]))
        for template in templates:
            associations = []
            for row in self._rows("component_associations", "template_id=?", (template["template_id"],), "position"):
                key, category = row["association_id"], row.pop("category_id")
                row.pop("position")
                row["scope_kind"], row["scope_id"] = ScopeKind(template["scope_kind"]), template["scope_id"]
                row["display_name"] = self._rows("components", "category_id=? AND component_id=?",
                    (category, row["component_id"]))[0]["display_name"]
                row["status"] = AssociationStatus(row["status"])
                row["evidence_level"] = EvidenceLevel(row["evidence_level"]) if row["evidence_level"] is not None else None
                row["notes"] = self._children("component_association_notes", "association_id", key, "note")
                row["sources"] = self._sources("component_association", category, key)
                associations.append(ComponentAssociationSnapshot(**row))
            result.append(_ComponentTemplateLayer(template["template_id"], tuple(associations)))
        return tuple(result)

    @_locked
    def hazard_candidates(self, scope: CanonicalIdentityScope) -> tuple[HazardSnapshot, ...]:
        result = []
        for row in sorted(self._scoped("hazards", scope), key=lambda r: r["hazard_id"]):
            key, category = row["hazard_id"], row.pop("category_id")
            row["scope_kind"] = ScopeKind(row["scope_kind"])
            row["severity"] = HazardSeverity(row["severity"])
            row["evidence_level"] = EvidenceLevel(row["evidence_level"])
            row["trigger_observation_keys"] = self._children("hazard_triggers", "hazard_id", key, "observation_key")
            for field, kind in (("immediate_actions", "immediate"), ("follow_up_actions", "follow_up"),
                                ("handling_guidance", "handling"), ("disposal_guidance", "disposal")):
                row[field] = self._children("hazard_actions", "hazard_id", key, "action_text",
                                           group_key="action_kind", group=kind)
            row["sources"] = self._sources("hazard", category, key)
            result.append(HazardSnapshot(**row))
        return tuple(result)

    @_locked
    def policy_bundle(self) -> PolicyBundleSnapshot:
        rules = []
        for row in self._rows("policy_rules", order="priority,rule_id"):
            key = row["rule_id"]
            row["outcome"] = RecommendationValue(row["outcome"])
            row["evidence_level"] = EvidenceLevel(row["evidence_level"])
            for field, group in (("when_all", "all"), ("when_any", "any")):
                row[field] = self._children("policy_predicates", "rule_id", key, "predicate",
                                           group_key="predicate_group", group=group)
            row["sources"] = self._sources("policy", "", key)
            rules.append(PolicyRuleSnapshot(**row))
        return PolicyBundleSnapshot(self.manifest.policy_revision, tuple(rules))

    @_locked
    def source_snapshots(self, source_ids: Iterable[str]) -> tuple[SourceSnapshot, ...]:
        result = []
        for source_id in sorted(set(source_ids)):
            rows = self._rows("sources", "source_id=?", (source_id,))
            if rows:
                result.append(self._source(rows[0]))
        return tuple(result)
