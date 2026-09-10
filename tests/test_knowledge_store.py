"""Runtime boundary tests against real compiled, synthetic evidence bundles."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import date
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from scripts.knowledge_compiler import compile_knowledge_bundle, logical_content_sha256
from tests.knowledge_helpers import make_valid_knowledge_source, mutate_yaml
from server.evidence_types import (
    AssociationStatus, BatteryArchitecture, CanonicalIdentityScope, CategorySnapshot,
    ComponentAssociationSnapshot, EvidenceLevel, HazardSeverity, HazardSnapshot,
    IdentityKind, IdentityRecordSnapshot, LifecycleEndpointKind,
    LifecycleRecordSnapshot, MarketState, PolicyBundleSnapshot, PolicyRuleSnapshot,
    RecommendationValue, RELEASED_CATEGORY_IDS, ResolutionTier, ScopeKind, SourceSnapshot,
)
from server.knowledge_store import KnowledgeStartupError, KnowledgeStore


C = "0303_laptop"
M = C + "_model_01"
ERROR = "knowledge bundle is unavailable or incompatible"


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    root = tmp_path_factory.mktemp("store").resolve()
    source = make_valid_knowledge_source(root / "source")
    out = root / "bundle"
    manifest = compile_knowledge_bundle(source, out)
    return out, manifest


@pytest.fixture
def bundle(compiled, tmp_path):
    out = tmp_path.resolve() / "bundle"
    shutil.copytree(compiled[0], out)
    return out / "knowledge.sqlite", out / "evidence-coverage.json", compiled[1]


def source(kind="claim"):
    ident = C + "_" + kind + "_source"
    return SourceSnapshot(ident, C + " " + kind + " evidence",
        "Synthetic Evidence Publisher", "https://example.invalid/" + ident,
        date(2026, 1, 1), date(2026, 9, 7), "synthetic-test-fixture",
        "test-reviewer", date(2026, 9, 7))


def test_full_identity_category_and_scope_values(bundle):
    database, coverage, manifest = bundle
    with KnowledgeStore(database, coverage,
            expected_sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
            expected_content_sha256=manifest.content_sha256,
            expected_coverage_sha256=manifest.coverage_sha256,
            expected_schema_version=3, expected_bundle_version="3.0.0",
            expected_identity_catalog_version="1.0.0", expected_policy_revision="2.0.0") as store:
        assert store.manifest == manifest
        assert store.list_categories() == tuple(CategorySnapshot(c, "Synthetic category " + c)
                                                for c in RELEASED_CATEGORY_IDS)
        assert store.get_category(C) == CategorySnapshot(C, "Synthetic category " + C)
        expected = IdentityRecordSnapshot(M, IdentityKind.MODEL, C, C + "_subtype_0",
            C + "_maker_0", "Synthetic Maker 0", C + "_family_00", "Synthetic Family 00",
            M, "Model 01", "Synthetic " + C + " model 01",
            ("Synthetic " + C + " model 01 Alias", "Catalog code 01"),
            ("synthetic token 01", "synthetic series 01"), 2021, 2021,
            date(2020, 1, 1), date(2020, 12, 31),
            (C + "_variant_0a", C + "_variant_0b"), MarketState.CURRENT,
            BatteryArchitecture.BATTERY_BEARING, (source(),))
        assert store.get_identity(M) == expected
        assert store.search_identities("model 01", category_id=C) == (expected,)
        assert store.identity_scope(M) == CanonicalIdentityScope(C, C + "_subtype_0",
            C + "_family_00", M, (C + "_variant_0a", C + "_variant_0b"), 2021, None)
        with pytest.raises(FrozenInstanceError):
            expected.display_name = "changed"
        with pytest.raises(FrozenInstanceError):
            store.get_identity(M).sources[0].title = "changed"


def test_full_lifecycle_values_and_sources_are_independent(bundle):
    with KnowledgeStore(bundle[0]) as store:
        records = store.lifecycle_candidates(store.identity_scope(M))
        average = LifecycleRecordSnapshot(C + "_industry_service_life",
            ResolutionTier.INDUSTRY_AVERAGE, ScopeKind.CATEGORY, C, "device",
            "service_life", LifecycleEndpointKind.TOTAL_LIFE, "elapsed_time", "years",
            3.0, 7.0, "Synthetic broad service-life interval.", None, None, None, None,
            (), (), 0, EvidenceLevel.C, ("Comparable population",),
            "Synthetic devices in the category.", "2020-2025",
            "Synthetic test-fixture interval study.", "Category-level uncertainty remains.",
            ("Not an exact-model estimate.",), (source(),))
        exact = LifecycleRecordSnapshot(C + "_lifecycle_0_model_service",
            ResolutionTier.EXACT_MODEL, ScopeKind.MODEL, M, "device", "service_life",
            LifecycleEndpointKind.TOTAL_LIFE, "elapsed_time", "years", 4.0, 6.0,
            "Synthetic total service life.", None, None, None, None,
            (C + "_variant_0a",), (), 0, EvidenceLevel.A,
            ("Normal operation", "Comparable configuration"), None, None, None, None,
            (), (source(),))
        assert records == (average, exact)  # Stable record-ID order; no resolution here.
        assert store.lifecycle_candidates(CanonicalIdentityScope(C)) == (average,)
        hazard = HazardSnapshot(C + "_damaged_battery_hazard", "battery",
            ScopeKind.CATEGORY, C, "Possible only when the user reports damage.",
            ("observations.issue_flags.odor", "observations.issue_flags.overheating"),
            HazardSeverity.URGENT, ("Stop using the item.",), ("Seek specialist handling.",),
            ("Avoid pressure or puncture.",), ("Use a certified recycler.",),
            EvidenceLevel.D, (source("hazard"),))
        assert store.hazard_candidates(store.identity_scope(M)) == (hazard,)
        assert hazard.sources != exact.sources


def test_full_component_and_policy_values(bundle):
    with KnowledgeStore(bundle[0]) as store:
        layers = store.component_layers(store.identity_scope(M))
        assert tuple(layer.template_id for layer in layers) == (C + "_standard", C + "_modern_overlay")
        assert layers[0].associations == (
            ComponentAssociationSnapshot(C + "_association_standard_0", C + "_standard",
                "chassis", "Chassis", AssociationStatus.COMMONLY_ASSOCIATED,
                ScopeKind.CATEGORY, C, "Category-standard enclosure.", (), EvidenceLevel.C, (source(),)),
            ComponentAssociationSnapshot(C + "_association_standard_1", C + "_standard",
                "battery", "Battery", AssociationStatus.CONDITIONAL, ScopeKind.CATEGORY, C,
                "Present only in battery-bearing variants.", ("Omission never establishes absence.",),
                EvidenceLevel.C, (source(),)),
        )
        assert layers[1].associations[1] == ComponentAssociationSnapshot(
            C + "_association_modern_1_unknown", C + "_modern_overlay", "storage", "Storage",
            AssociationStatus.UNKNOWN, ScopeKind.SUBTYPE, C + "_subtype_0",
            "The hidden storage form is unsupported.", ("Requires a model-specific source.",), None, ())
        with pytest.raises(FrozenInstanceError):
            layers[0].template_id = "changed"
        psource = replace(source(), source_id="shared_policy_source", title="Shared policy evidence",
                          canonical_url="https://example.invalid/shared_policy_source")
        usource = replace(psource, source_id="shared_process_source", title="Shared process evidence",
                          canonical_url="https://example.invalid/shared_process_source")
        assert store.policy_bundle() == PolicyBundleSnapshot("2.0.0", (
            PolicyRuleSnapshot("baseline_canonical_policy", 0, RecommendationValue.REUSE,
                ("identity.state=canonical",), (), "Canonical records can reach reviewed policy.", EvidenceLevel.D, (psource,)),
            PolicyRuleSnapshot("baseline_unknown_policy", 1, RecommendationValue.MORE_INFORMATION_NEEDED,
                ("identity.state=unknown",), (), "Unknown identity needs more information.", EvidenceLevel.D, (usource,)),
        ))
        assert store.source_snapshots([source("hazard").source_id, "absent", source().source_id,
                                       source().source_id]) == (source(), source("hazard"))


def test_missing_keys_and_empty_search_do_not_invent_scope(bundle):
    with KnowledgeStore(bundle[0]) as store:
        assert store.get_category("absent") is None
        assert store.get_identity("absent") is None
        with pytest.raises(KeyError):
            store.identity_scope("absent")
        for text, category, limit in [(" ", None, 20), ("model", "absent", 20), ("model", C, 0), ("model", C, -1)]:
            assert store.search_identities(text, category_id=category, limit=limit) == ()
        for method in (store.lifecycle_candidates, store.hazard_candidates, store.component_layers):
            assert method(CanonicalIdentityScope("absent", model_id=M)) == ()


@pytest.mark.parametrize("option,value", [
    ("expected_sha256", "0" * 64), ("expected_content_sha256", "0" * 64),
    ("expected_coverage_sha256", "0" * 64), ("expected_schema_version", 2),
    ("expected_bundle_version", "99.0.0"), ("expected_identity_catalog_version", "99.0.0"),
    ("expected_policy_revision", "99.0.0"),
])
def test_release_mismatches_fail_closed(bundle, option, value):
    with pytest.raises(KnowledgeStartupError, match=ERROR):
        KnowledgeStore(bundle[0], bundle[1], **{option: value})


@pytest.mark.parametrize("mutation", ["missing", "empty", "corrupt", "extra_table", "view", "trigger", "column",
    "metadata", "data", "foreign_key", "category_order", "wal_header", "journal", "wal", "shm",
    "coverage_missing", "coverage_corrupt", "coverage_changed", "symlink", "parent_symlink"])
def test_invalid_artifacts_fail_closed(bundle, mutation, tmp_path):
    database, coverage, _ = bundle
    if mutation == "missing": database.unlink()
    elif mutation == "empty": database.write_bytes(b"")
    elif mutation == "corrupt": database.write_bytes(b"not SQLite")
    elif mutation == "wal_header":
        data = bytearray(database.read_bytes()); data[18:20] = b"\x02\x02"; database.write_bytes(data)
    elif mutation in {"journal", "wal", "shm"}:
        Path(str(database) + "-" + mutation).write_bytes(b"")
    elif mutation == "coverage_missing": coverage.unlink()
    elif mutation == "coverage_corrupt": coverage.write_bytes(b"{")
    elif mutation == "coverage_changed": coverage.write_bytes(coverage.read_bytes() + b" ")
    elif mutation == "symlink":
        target = database.with_name("real.sqlite"); database.rename(target); database.symlink_to(target)
    elif mutation == "parent_symlink":
        link = tmp_path / "link"; link.symlink_to(database.parent, target_is_directory=True); database = link / database.name
    else:
        statements = {
            "extra_table": "CREATE TABLE extras (x TEXT)", "view": "CREATE VIEW extras AS SELECT * FROM sources",
            "trigger": "CREATE TRIGGER extras AFTER DELETE ON sources BEGIN SELECT 1; END",
            "column": "ALTER TABLE sources ADD COLUMN extra TEXT",
            "metadata": "UPDATE metadata SET value='2' WHERE key='schema_version'",
            "data": "UPDATE sources SET title='tampered'",
            "foreign_key": "UPDATE identity_variants SET variant_id='missing' WHERE ordinal=0",
            "category_order": "UPDATE categories SET category_id='wrong' WHERE release_order=0",
        }
        with sqlite3.connect(database) as connection: connection.execute(statements[mutation])
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(database)


def test_readonly_snapshot_survives_external_replace_and_rewrite(bundle):
    database, coverage, _ = bundle
    original = database.read_bytes(); original_coverage = coverage.read_bytes()
    with KnowledgeStore(database) as store:
        before = store.get_identity(M)
        assert store._connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert store._connection.serialize() == original
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store._connection.execute("DELETE FROM sources")
        assert database.read_bytes() == original
        assert coverage.read_bytes() == original_coverage
        assert sorted(p.name for p in database.parent.iterdir()) == ["evidence-coverage.json", "knowledge.sqlite"]
        database.write_bytes(b"rewritten in place")
        assert store.get_identity(M) == before
        database.unlink(); database.write_bytes(original)
        coverage.write_bytes(b"later coverage")
        assert store.get_identity(M) == before


def test_concurrent_reads_and_close(bundle):
    store = KnowledgeStore(bundle[0])
    expected = store.get_identity(M)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(lambda _: store.get_identity(M), range(100))) == [expected] * 100
        def read_or_close(i):
            if i % 5 == 0: store.close(); return None
            try: return store.get_identity(M)
            except RuntimeError as exc: assert "closed" in str(exc); return None
        results = list(pool.map(read_or_close, range(100)))
        assert all(result is None or result == expected for result in results)
    store.close()
    with pytest.raises(RuntimeError, match="closed"): store.list_categories()


def test_unsupported_threadsafety_fails_closed(bundle, monkeypatch):
    monkeypatch.setattr(sqlite3, "threadsafety", 0)
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(bundle[0])


def test_runtime_import_is_standard_library_only():
    code = '''import builtins
real = builtins.__import__
def guard(name, *args, **kwargs):
    if name == "yaml" or name.startswith("scripts"):
        raise AssertionError(name)
    return real(name, *args, **kwargs)
builtins.__import__ = guard
from server.knowledge_store import KnowledgeStore
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def varied_bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("varied-store").resolve()
    source_dir = make_valid_knowledge_source(root / "source")
    def identities(doc):
        for index, bounds in enumerate([
            (2024, 2024, "2024-06-01", "2024-06-01"),
            (2020, 2025, "2020-01-01", "2025-01-01"),
            (None, 2025, "2020-01-01", None),
        ], 1):
            record = doc["identities"][index]
            record.update(zip(("model_year_from", "model_year_to", "applicable_from", "applicable_to"), bounds))
        # Collision-free fields exercise every ranking rule and Unicode normalization.
        doc["identities"][1]["aliases"] = ["Café Pro", "Alpha omega"]
        doc["identities"][2]["aliases"] = ["Café Pro Plus", "Alpha skip omega"]
        doc["identities"][3]["distinguishing_tokens"] = ["Brand Café Professional", "Alpine omega"]
        doc["identities"][4]["aliases"] = ["Brand Décafé Pro", "prefix Alpha omega suffix"]
        subtype = deepcopy(doc["subtypes"][0])
        subtype.update(subtype_id="test_laptop_subtype", display_name="Range test subtype")
        doc["subtypes"].append(subtype)
        for suffix in ("a", "b"):
            variant = deepcopy(doc["variants"][0])
            variant.update(variant_id="variant_" + suffix, subtype_id="test_laptop_subtype",
                           display_name="Range variant " + suffix)
            doc["variants"].append(variant)
        for name, lower, upper, start, end, variants in (
            ("exact_identity", 2024, 2024, "2024-06-01", "2024-06-01", ["variant_a", "variant_b"]),
            ("ranged_identity", 2020, 2025, "2020-01-01", "2025-01-01", ["variant_a"]),
            ("open_range_identity", 2020, None, None, "2025-01-01", []),
        ):
            record = deepcopy(doc["identities"][1])
            record.update(identity_id=name, model_id=name, model_name=name, display_name=name,
                subtype_id="test_laptop_subtype", family_id="test_laptop_family", family_name="Test Laptop Family",
                aliases=[name + " alias"], distinguishing_tokens=[name + " token"],
                model_year_from=lower, model_year_to=upper, applicable_from=start, applicable_to=end,
                variant_ids=variants)
            doc["identities"].append(record)
        doc["identities"].sort(key=lambda record: record["identity_id"])
    mutate_yaml(source_dir / "categories" / C / "identities.yaml", identities)
    def templates(doc):
        doc["templates"].extend([
            {"template_id": "empty_family", "template_kind": "modern_overlay",
             "scope": {"kind": "family", "id": C + "_family_00"}, "application_order": 9},
            {"template_id": "empty_model", "template_kind": "modern_overlay",
             "scope": {"kind": "model", "id": M}, "application_order": 1},
            {"template_id": "empty_subtype", "template_kind": "modern_overlay",
             "scope": {"kind": "subtype", "id": C + "_subtype_0"}, "application_order": 2},
        ])
    mutate_yaml(source_dir / "categories" / C / "components.yaml", templates)
    mutate_yaml(source_dir / "categories" / C / "lifecycles.yaml",
                lambda doc: doc["lifecycles"][0].update(excluded_variant_ids=[C + "_variant_0b"]))
    def actions(doc):
        for field in ("immediate_actions", "follow_up_actions", "handling_guidance", "disposal_guidance"):
            doc["hazards"][0][field] = ["First " + field, "Second " + field]
    mutate_yaml(source_dir / "categories" / C / "hazards.yaml", actions)
    mutate_yaml(source_dir / "common/policies.yaml",
                lambda doc: doc["policies"][1].update(when_any=["visible_condition.grade=good"]))
    out = root / "bundle"
    compile_knowledge_bundle(source_dir, out)
    return out


def test_identity_ranges_never_select_non_singleton_endpoint(varied_bundle):
    with KnowledgeStore(varied_bundle / "knowledge.sqlite") as store:
        assert store.identity_scope(M) == CanonicalIdentityScope(C, C + "_subtype_0", C + "_family_00", M,
            (C + "_variant_0a", C + "_variant_0b"), 2024, date(2024, 6, 1))
        for index in (2, 3):
            model = C + f"_model_{index:02d}"
            assert store.identity_scope(model) == CanonicalIdentityScope(C, C + "_subtype_1", C + "_family_01", model,
                (C + "_variant_1a", C + "_variant_1b"), None, None)
        family = store.identity_scope(C + "_family_00")
        assert family.model_id is None
        assert store.identity_scope("exact_identity") == CanonicalIdentityScope(
            C, "test_laptop_subtype", "test_laptop_family", "exact_identity",
            ("variant_a", "variant_b"), 2024, date(2024, 6, 1))
        assert store.identity_scope("ranged_identity") == CanonicalIdentityScope(
            C, "test_laptop_subtype", "test_laptop_family", "ranged_identity", ("variant_a",), None, None)
        assert store.identity_scope("open_range_identity") == CanonicalIdentityScope(
            C, "test_laptop_subtype", "test_laptop_family", "open_range_identity", (), None, None)


@pytest.mark.parametrize("text,ids", [
    ("  CAFE\u0301\u2003pRo  ", (1, 2, 3)),
    ("alpha omega", (1, 4)),
    ("al om", (4,)),  # Token-window rank begins after token zero.
    ("décafé", (4,)),
    ("cafe", ()),  # Do not strip accents.
    ("afé", ()),  # Do not substring-match inside tokens.
])
def test_exact_prefix_contiguous_token_search(varied_bundle, text, ids):
    with KnowledgeStore(varied_bundle / "knowledge.sqlite") as store:
        assert tuple(r.identity_id for r in store.search_identities(text, category_id=C)) == tuple(C + f"_model_{i:02d}" for i in ids)
        assert tuple(r.identity_id for r in store.search_identities(text, category_id=C, limit=1)) == tuple(C + f"_model_{i:02d}" for i in ids[:1])


def test_empty_component_layers_preserve_template_ids_in_scope_order(varied_bundle):
    with KnowledgeStore(varied_bundle / "knowledge.sqlite") as store:
        layers = store.component_layers(store.identity_scope(M))
        assert tuple(layer.template_id for layer in layers) == (
            C + "_standard", C + "_modern_overlay", "empty_subtype", "empty_family", "empty_model")
        assert tuple(layer.associations for layer in layers[2:]) == ((), (), ())


def test_valid_coverage_from_another_bundle_rejected(compiled, varied_bundle):
    with pytest.raises(KnowledgeStartupError, match=ERROR):
        KnowledgeStore(compiled[0] / "knowledge.sqlite", varied_bundle / "evidence-coverage.json")


@pytest.mark.parametrize("mutation", ["replace", "rewrite", "coverage", "sidecar", "parent"])
def test_startup_descriptor_or_path_tampering_rejected(bundle, monkeypatch, mutation):
    database, coverage, _ = bundle
    real_connect = sqlite3.connect
    opened = []
    def racing_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        if mutation == "replace":
            original = database.read_bytes(); database.unlink(); database.write_bytes(original)
        elif mutation == "rewrite": database.write_bytes(b"tampered after capture")
        elif mutation == "coverage": coverage.write_bytes(b"tampered coverage")
        elif mutation == "sidecar": Path(str(database) + "-wal").write_bytes(b"")
        elif mutation == "parent":
            moved = database.parent.with_name("moved"); database.parent.rename(moved)
            shutil.copytree(moved, database.parent)
        return connection
    monkeypatch.setattr(sqlite3, "connect", racing_connect)
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(database)
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"): connection.execute("SELECT 1")


def test_mode_ro_and_snapshot_before_any_content_queries(bundle, monkeypatch):
    real_connect = sqlite3.connect
    trace = []
    class Audited(sqlite3.Connection):
        def deserialize(self, data, **kwargs):
            trace.append("deserialize")
            return super().deserialize(data, **kwargs)
        def execute(self, sql, *args, **kwargs):
            trace.append(sql)
            return super().execute(sql, *args, **kwargs)
    def connect(database_uri, **kwargs):
        assert "mode=ro" in database_uri and kwargs["uri"] is True
        assert kwargs["check_same_thread"] is False
        return real_connect(database_uri, factory=Audited, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", connect)
    with KnowledgeStore(bundle[0]): pass
    assert trace[0] == "deserialize"
    assert "PRAGMA quick_check" in trace
    assert "PRAGMA foreign_key_check" in trace


def rewrite_coverage_hash(database, coverage, data):
    coverage.write_bytes(data)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE metadata SET value=? WHERE key='coverage_sha256'",
                           (hashlib.sha256(data).hexdigest(),))


def relink_tampered_rows(database, coverage):
    # Administrator digest is used only to manufacture an internally rehashed
    # negative artifact; it never supplies a query-value assertion.
    with sqlite3.connect(database) as connection:
        rows = {}
        for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid"):
            info = list(connection.execute(f'PRAGMA table_info("{table}")'))
            keys = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
            rows[table] = tuple(connection.execute(f'SELECT * FROM "{table}" ORDER BY ' + ','.join(keys)))
        digest = logical_content_sha256(rows)
        connection.execute("UPDATE metadata SET value=? WHERE key='content_sha256'", (digest,))
    report = json.loads(coverage.read_bytes())
    report["knowledge_content_sha256"] = digest
    data = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    rewrite_coverage_hash(database, coverage, data)


@pytest.mark.parametrize("mutation", ["top_fields", "summary_fields", "summary_type", "summary_count",
    "schema_bool", "bundle_link", "content_link", "claim_fields", "claim_category", "claim_kind",
    "claim_id", "claim_order", "claim_duplicate", "source_order", "source_duplicate", "source_id",
    "reviewed_evidence", "reviewed_reason", "reviewed_sources", "unknown_evidence", "unknown_reason",
    "unknown_sources", "source_state", "noncanonical", "duplicate_json_key"])
def test_closed_coverage_rejects_even_with_recomputed_file_hash(bundle, mutation):
    database, coverage, _ = bundle
    report = json.loads(coverage.read_bytes())
    claim = next(c for c in report["claims"] if c["source_state"] == "reviewed")
    unknown = next(c for c in report["claims"] if c["source_state"] == "unknown")
    if mutation == "top_fields": report["extra"] = None
    elif mutation == "summary_fields": report["summary"]["extra"] = 0
    elif mutation == "summary_type": report["summary"]["categories"] = True
    elif mutation == "summary_count": report["summary"]["reviewed_claims"] += 1
    elif mutation == "schema_bool": report["schema_version"] = True
    elif mutation == "bundle_link": report["bundle_version"] = "99.0.0"
    elif mutation == "content_link": report["knowledge_content_sha256"] = "0" * 64
    elif mutation == "claim_fields": claim["extra"] = None
    elif mutation == "claim_category": claim["category_id"] = "unreleased"
    elif mutation == "claim_kind": claim["claim_kind"] = "made_up"
    elif mutation == "claim_id": claim["claim_id"] = "Not an ID"
    elif mutation == "claim_order": report["claims"].reverse()
    elif mutation == "claim_duplicate": report["claims"].insert(0, report["claims"][0])
    elif mutation == "source_order": claim["source_ids"] = ["z_source", "a_source"]
    elif mutation == "source_duplicate": claim["source_ids"] *= 2
    elif mutation == "source_id": claim["source_ids"] = ["Not an ID"]
    elif mutation == "reviewed_evidence": claim["evidence_level"] = None
    elif mutation == "reviewed_reason": claim["unknown_reason"] = "reason"
    elif mutation == "reviewed_sources": claim["source_ids"] = []
    elif mutation == "unknown_evidence": unknown["evidence_level"] = "A"
    elif mutation == "unknown_reason": unknown["unknown_reason"] = "\u0000"
    elif mutation == "unknown_sources": unknown["source_ids"] = ["a_source"]
    elif mutation == "source_state": claim["source_state"] = "unchecked"
    data = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    if mutation == "noncanonical": data += b" "
    elif mutation == "duplicate_json_key": data = data.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
    rewrite_coverage_hash(database, coverage, data)
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(database)


@pytest.mark.parametrize("sql", [
    "UPDATE identity_variants SET variant_id='missing' WHERE ordinal=0",
    "UPDATE lifecycle_records SET precedence=-1",
    "UPDATE metadata SET value='03' WHERE key='schema_version'",
    "UPDATE metadata SET value='v3.0.0' WHERE key='bundle_version'",
])
def test_integrity_and_metadata_checks_survive_recomputed_logical_hash(bundle, sql):
    database, coverage, _ = bundle
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(sql)
    relink_tampered_rows(database, coverage)
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(database)


def test_family_lifecycle_keeps_ranges_and_candidates_ignore_usage_filters(bundle):
    with KnowledgeStore(bundle[0]) as store:
        scope = store.identity_scope(C + "_model_02")
        candidates = store.lifecycle_candidates(replace(scope, model_year=1900, applicable_on=date(1900, 1, 1)))
        assert candidates[1] == LifecycleRecordSnapshot(C + "_lifecycle_1_family_capacity",
            ResolutionTier.FAMILY, ScopeKind.FAMILY, C + "_family_01", "battery", "capacity_threshold",
            LifecycleEndpointKind.CAPACITY_THRESHOLD, "full_charge_cycles", "cycles", 800.0, 800.0,
            "Synthetic sourced point threshold.", date(2020, 1, 1), date(2030, 1, 1), 2020, 2030,
            (), (), 1, EvidenceLevel.B, (), None, None, None, None, (), (source(),))
        assert tuple(r.record_id for r in candidates) == (C + "_industry_service_life", C + "_lifecycle_1_family_capacity")
        assert len(store.lifecycle_candidates(replace(store.identity_scope(M), variant_ids=()))) == 2


def test_parameter_binding_and_cross_category_scope_isolation(bundle):
    with KnowledgeStore(bundle[0]) as store:
        assert store.get_identity("' OR 1=1 --") is None
        assert store.get_category("' OR 1=1 --") is None
        assert store.source_snapshots(["' OR 1=1 --"]) == ()
        assert store.search_identities("model", category_id="' OR 1=1 --") == ()
        other = CanonicalIdentityScope("0301_keyboard", C + "_subtype_0", C + "_family_00", M)
        assert tuple(r.record_id for r in store.lifecycle_candidates(other)) == ("0301_keyboard_industry_service_life",)
        assert tuple(r.template_id for r in store.component_layers(other)) == ("0301_keyboard_standard",)


def test_nonempty_exclusions_and_all_action_groups_preserve_authored_order(varied_bundle):
    with KnowledgeStore(varied_bundle / "knowledge.sqlite") as store:
        records = store.lifecycle_candidates(store.identity_scope(M))
        assert records[1].excluded_variant_ids == (C + "_variant_0b",)
        assert records[1].required_variant_ids == (C + "_variant_0a",)
        hazard = store.hazard_candidates(store.identity_scope(M))[0]
        assert hazard.immediate_actions == ("First immediate_actions", "Second immediate_actions")
        assert hazard.follow_up_actions == ("First follow_up_actions", "Second follow_up_actions")
        assert hazard.handling_guidance == ("First handling_guidance", "Second handling_guidance")
        assert hazard.disposal_guidance == ("First disposal_guidance", "Second disposal_guidance")
        assert store.policy_bundle().rules[1].when_any == ("visible_condition.grade=good",)
        assert store.policy_bundle().rules[1].when_all == ("identity.state=unknown",)


@pytest.mark.parametrize("failure", ["deserialize", "serialize", "query_only", "quick_check", "foreign_key_check"])
def test_failed_startup_closes_snapshot_and_all_anchored_handles(bundle, monkeypatch, failure):
    real_connect, real_open = sqlite3.connect, os.open
    connections, descriptors = [], []
    class Broken(sqlite3.Connection):
        def deserialize(self, *args, **kwargs):
            if failure == "deserialize": raise sqlite3.NotSupportedError("not supported")
            return super().deserialize(*args, **kwargs)
        def serialize(self, *args, **kwargs):
            if failure == "serialize": raise sqlite3.NotSupportedError("not supported")
            return super().serialize(*args, **kwargs)
        def execute(self, sql, *args, **kwargs):
            if (failure == "query_only" and sql == "PRAGMA query_only = ON"):
                return super().execute("PRAGMA query_only")  # Setting was ignored.
            if sql == "PRAGMA " + failure and failure in {"quick_check", "foreign_key_check"}:
                raise sqlite3.DatabaseError("integrity unavailable")
            return super().execute(sql, *args, **kwargs)
    def connect(*args, **kwargs):
        connection = real_connect(*args, factory=Broken, **kwargs)
        connections.append(connection)
        return connection
    def open_file(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor
    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(os, "open", open_file)
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(bundle[0])
    assert connections and descriptors
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"): connection.execute("SELECT 1")
    for descriptor in descriptors:
        with pytest.raises(OSError): os.fstat(descriptor)


def test_snapshot_capability_absence_fails_closed(bundle, monkeypatch):
    monkeypatch.setattr(sqlite3, "Connection", object)
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(bundle[0])


@pytest.mark.parametrize("target", ["coverage_file", "coverage_parent", "database_fifo", "coverage_fifo"])
def test_nonregular_or_linked_artifacts_rejected_without_blocking(bundle, tmp_path, target):
    database, coverage, _ = bundle
    if target == "coverage_file":
        original = coverage.with_name("real.json"); coverage.rename(original); coverage.symlink_to(original)
    elif target == "coverage_parent":
        link = tmp_path / "coverage_link"; link.symlink_to(coverage.parent, target_is_directory=True)
        coverage = link / coverage.name
    else:
        path = database if target == "database_fifo" else coverage
        path.unlink(); os.mkfifo(path)
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(database, coverage)


def test_internal_hashes_validate_without_expected_release_hash(bundle):
    database, coverage, _ = bundle
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sources SET title='legitimate new compiled contents'")
    # Internal linkage is necessary even when the caller omits release pins;
    # it is not an authenticity claim without a trusted expected raw hash.
    with pytest.raises(KnowledgeStartupError, match=ERROR): KnowledgeStore(database, coverage)


def test_snapshot_enum_types_and_nested_records_are_frozen(bundle):
    with KnowledgeStore(bundle[0]) as store:
        identity = store.get_identity(M)
        assert type(identity.identity_kind) is IdentityKind
        assert type(identity.market_state) is MarketState
        assert type(identity.battery_architecture) is BatteryArchitecture
        assert type(identity.applicable_from) is date
        assert type(identity.sources[0].reviewed_on) is date
        scope = store.identity_scope(M)
        lifecycle = store.lifecycle_candidates(scope)[0]
        assert type(lifecycle.resolution_tier) is ResolutionTier
        assert type(lifecycle.scope_kind) is ScopeKind
        assert type(lifecycle.endpoint_kind) is LifecycleEndpointKind
        assert type(lifecycle.evidence_level) is EvidenceLevel
        assert type(lifecycle.lower_bound) is float
        association = store.component_layers(scope)[0].associations[0]
        assert type(association.status) is AssociationStatus
        assert type(association.scope_kind) is ScopeKind
        assert type(association.evidence_level) is EvidenceLevel
        hazard = store.hazard_candidates(scope)[0]
        assert type(hazard.scope_kind) is ScopeKind
        assert type(hazard.severity) is HazardSeverity
        assert type(hazard.evidence_level) is EvidenceLevel
        policy = store.policy_bundle()
        assert type(policy.rules[0].outcome) is RecommendationValue
        assert type(policy.rules[0].evidence_level) is EvidenceLevel
        for record, field in ((lifecycle, "record_id"), (association, "association_id"),
                              (hazard, "hazard_id"), (policy, "revision"), (policy.rules[0], "rule_id")):
            with pytest.raises(FrozenInstanceError): setattr(record, field, "changed")
