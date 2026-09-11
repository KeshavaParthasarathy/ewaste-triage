"""Release verifier mechanics over synthetic evidence, never real corpus approval."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, fields
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.evidence_coverage import (
    compare_coverage, coverage_json_bytes, validate_release_floor,
)
from scripts.knowledge_compiler import compile_knowledge_bundle
from scripts import knowledge_release as release
from scripts.knowledge_release import (
    KnowledgeReleaseError, KnowledgeReleaseInputs, verify_knowledge_release_inputs,
)
from tests.knowledge_helpers import make_valid_knowledge_source, mutate_yaml


FILES = ("knowledge.sqlite", "evidence-coverage.json", "evidence-coverage-change.json")
UNAVAILABLE = "knowledge release inputs unavailable or incompatible"
UNSAFE = "unsafe release input path"
RESULT_FIELDS = (
    "knowledge_database_path", "evidence_coverage_path", "evidence_coverage_change_path",
    "knowledge_sha256", "stamp", "coverage_sha256", "coverage_change_sha256",
)
ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8") + b"\n"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_bytes(canonical(value))


def approve_synthetic(candidate, approval, manifest):
    coverage = json.loads((candidate / FILES[1]).read_bytes())
    write_json(approval, {
        "approval_schema_version": 1, "schema_version": manifest.schema_version,
        "bundle_version": manifest.bundle_version,
        "identity_catalog_version": manifest.identity_catalog_version,
        "policy_revision": manifest.policy_revision,
        "knowledge_sha256": sha256(candidate / FILES[0]),
        "content_sha256": manifest.content_sha256,
        "coverage_sha256": manifest.coverage_sha256,
        "coverage_change_sha256": sha256(candidate / FILES[2]),
        "corpus_counts": coverage["summary"],
        "reviewed_by": "SYNTHETIC verifier test — not a real review",
        "reviewed_on": "2026-09-07",
    })


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("release-baseline").resolve()
    source = make_valid_knowledge_source(root / "source")
    candidate = root / "candidate"
    manifest = compile_knowledge_bundle(source, candidate)
    raw = (candidate / FILES[1]).read_bytes()
    coverage = json.loads(raw)
    assert coverage_json_bytes(coverage) == raw
    validate_release_floor(coverage)
    assert coverage["summary"] == {
        "categories": 5, "canonical_identities": 50, "subtypes": 20,
        "lifecycle_records": 15, "industry_averages": 5, "component_templates": 15,
        "modern_overlays": 5, "legacy_overlays": 5, "hazard_records": 5,
        "reviewed_claims": 155, "unknown_claims": 5,
    }
    write_json(candidate / FILES[2], compare_coverage(None, coverage))
    approval = root / "synthetic-approval.json"
    approve_synthetic(candidate, approval, manifest)
    return candidate, approval, manifest


@pytest.fixture
def approved_candidate(baseline, tmp_path):
    candidate = tmp_path.resolve() / "candidate"
    approval = tmp_path.resolve() / "synthetic-approval.json"
    shutil.copytree(baseline[0], candidate)
    shutil.copyfile(baseline[1], approval)
    return candidate, approval, baseline[2]


def rejects(candidate, approval, message=UNAVAILABLE):
    with pytest.raises(KnowledgeReleaseError) as caught:
        verify_knowledge_release_inputs(candidate, approval)
    assert str(caught.value) == message


def amend_approval(approval, mutation):
    record = json.loads(approval.read_bytes())
    mutation(record)
    write_json(approval, record)


def amend_change(candidate, approval, mutation):
    path = candidate / FILES[2]
    change = json.loads(path.read_bytes())
    mutation(change)
    write_json(path, change)
    amend_approval(approval, lambda a: a.update(coverage_change_sha256=sha256(path)))


def test_verifier_returns_every_release_expectation_without_writes(approved_candidate):
    candidate, approval, manifest = approved_candidate
    paths = [candidate / name for name in FILES] + [approval]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    result = verify_knowledge_release_inputs(candidate, approval)
    assert isinstance(result, KnowledgeReleaseInputs)
    assert tuple(f.name for f in fields(result)) == RESULT_FIELDS
    assert result.knowledge_database_path == candidate / FILES[0]
    assert result.evidence_coverage_path == candidate / FILES[1]
    assert result.evidence_coverage_change_path == candidate / FILES[2]
    assert result.knowledge_sha256 == sha256(candidate / FILES[0])
    assert result.stamp == manifest.stamp
    assert result.coverage_sha256 == manifest.coverage_sha256
    assert result.coverage_change_sha256 == sha256(candidate / FILES[2])
    with pytest.raises(FrozenInstanceError):
        result.knowledge_sha256 = "0" * 64
    assert before == [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    assert set(p.name for p in candidate.iterdir()) == set(FILES)


def test_relative_paths_are_returned_absolute(approved_candidate, monkeypatch):
    candidate, approval, _ = approved_candidate
    monkeypatch.chdir(candidate.parent)
    result = verify_knowledge_release_inputs(Path(candidate.name), Path(approval.name))
    assert result.knowledge_database_path == candidate / FILES[0]


@pytest.mark.parametrize("artifact", FILES)
def test_each_artifact_tamper_fails(approved_candidate, artifact):
    candidate, approval, _ = approved_candidate
    path = candidate / artifact
    path.write_bytes(path.read_bytes() + b"tampered")
    rejects(candidate, approval)


@pytest.mark.parametrize("target", ("candidate", "approval", *FILES))
def test_missing_inputs_fail(approved_candidate, target):
    candidate, approval, _ = approved_candidate
    path = candidate if target == "candidate" else approval if target == "approval" else candidate / target
    path.rename(candidate.parent / "absent-input")
    rejects(candidate, approval)


def test_extra_candidate_entry_fails(approved_candidate):
    candidate, approval, _ = approved_candidate
    (candidate / "extra").mkdir()
    rejects(candidate, approval)


@pytest.mark.parametrize("target", ("candidate", "approval", *FILES, "candidate_ancestor", "approval_ancestor"))
def test_symlinks_fail_before_any_content_read(approved_candidate, monkeypatch, target):
    candidate, approval, _ = approved_candidate
    if target.endswith("ancestor"):
        link = candidate.parent / "linked-parent"
        link.symlink_to(candidate.parent, target_is_directory=True)
        if target == "candidate_ancestor":
            candidate = link / candidate.name
        else:
            approval = link / approval.name
    else:
        path = candidate if target == "candidate" else approval if target == "approval" else candidate / target
        real = candidate.parent / "real-input"
        path.rename(real)
        path.symlink_to(real, target_is_directory=target == "candidate")
    def forbidden_read(*args):
        pytest.fail("content was read before every input was inspected")
    monkeypatch.setattr(os, "read", forbidden_read)
    rejects(candidate, approval, UNSAFE)


@pytest.mark.parametrize("target", ("candidate", "approval", *FILES))
@pytest.mark.parametrize("kind", ("wrong_type", "fifo"))
def test_nonregular_inputs_fail(approved_candidate, target, kind):
    candidate, approval, _ = approved_candidate
    path = candidate if target == "candidate" else approval if target == "approval" else candidate / target
    path.rename(candidate.parent / "original-input")
    if kind == "fifo":
        os.mkfifo(path)
    elif target == "candidate":
        path.write_bytes(b"not a directory")
    else:
        path.mkdir()
    rejects(candidate, approval, UNSAFE)


@pytest.mark.parametrize("target", ("candidate", "approval"))
def test_explicit_parent_traversal_is_not_resolved_away(approved_candidate, target):
    candidate, approval, _ = approved_candidate
    if target == "candidate":
        candidate = candidate / ".." / candidate.name
    else:
        approval = candidate / ".." / approval.name
    rejects(candidate, approval, UNSAFE)


@pytest.mark.parametrize("left,right", [(a, b) for i, a in enumerate((*FILES, "approval"))
                                       for b in (*FILES, "approval")[i + 1:]])
def test_every_captured_inode_alias_fails_before_parsing(approved_candidate, left, right):
    candidate, approval, _ = approved_candidate
    first = approval if left == "approval" else candidate / left
    second = approval if right == "approval" else candidate / right
    second.rename(candidate.parent / "original-input")
    os.link(first, second)
    rejects(candidate, approval, UNSAFE)


def test_approval_inside_candidate_fails_as_unsafe(approved_candidate):
    candidate, approval, _ = approved_candidate
    inside = candidate / "approval.json"
    approval.rename(inside)
    rejects(candidate, inside, UNSAFE)


@pytest.mark.parametrize("damage", ("malformed", "missing", "extra"))
def test_existing_unsafe_input_precedes_other_failure(approved_candidate, damage):
    candidate, approval, _ = approved_candidate
    if damage == "malformed":
        approval.write_bytes(b"{")
    elif damage == "missing":
        approval.rename(candidate.parent / "missing-approval")
    else:
        (candidate / "extra").write_bytes(b"")
    path = candidate / FILES[2]
    path.rename(candidate.parent / "real-change")
    path.symlink_to(candidate.parent / "real-change")
    rejects(candidate, approval, UNSAFE)


@pytest.mark.parametrize("key,value", [
    ("approval_schema_version", True), ("approval_schema_version", 2),
    ("approval_schema_version", 1.0), ("schema_version", True), ("schema_version", 3.0),
    ("schema_version", 2), ("bundle_version", "3.0.1"),
    ("identity_catalog_version", "2.0.0"), ("policy_revision", "2.0.1"),
    ("reviewed_by", " \t"), ("reviewed_by", None), ("reviewed_on", "2026-02-30"),
    ("reviewed_on", "20260907"), ("reviewed_on", "2026-W37-1"), ("reviewed_on", 20260907),
    *[(key, value) for key in ("knowledge_sha256", "content_sha256", "coverage_sha256", "coverage_change_sha256")
      for value in ("0" * 64, "A" * 64, "abc", None)],
])
def test_invalid_approval_values_fail(approved_candidate, key, value):
    candidate, approval, _ = approved_candidate
    amend_approval(approval, lambda a: a.update({key: value}))
    rejects(candidate, approval)


@pytest.mark.parametrize("mutation", (lambda a: a.update(extra=1), lambda a: a.pop("reviewed_on"),
                                    lambda a: a.update(corpus_counts=[]),
                                    lambda a: a["corpus_counts"].update(extra=1),
                                    lambda a: a["corpus_counts"].pop("unknown_claims")))
def test_approval_objects_are_closed(approved_candidate, mutation):
    candidate, approval, _ = approved_candidate
    amend_approval(approval, mutation)
    rejects(candidate, approval)


@pytest.mark.parametrize("count", ("categories", "canonical_identities", "subtypes", "lifecycle_records",
                                  "industry_averages", "component_templates", "modern_overlays",
                                  "legacy_overlays", "hazard_records", "reviewed_claims", "unknown_claims"))
@pytest.mark.parametrize("value", (True, 0, -1, 1.0, 999))
def test_complete_positive_exact_approval_counts(approved_candidate, count, value):
    candidate, approval, _ = approved_candidate
    amend_approval(approval, lambda a: a["corpus_counts"].update({count: value}))
    rejects(candidate, approval)


@pytest.mark.parametrize("target", ("approval", FILES[1], FILES[2]))
@pytest.mark.parametrize("encoding", ("space", "no_lf", "two_lf", "ascii", "duplicate", "nested_duplicate",
                                       "nan", "infinity", "utf8", "array", "scalar", "broken"))
def test_all_json_inputs_require_exact_canonical_objects(approved_candidate, target, encoding):
    candidate, approval, _ = approved_candidate
    path = approval if target == "approval" else candidate / target
    raw = path.read_bytes()
    obj = json.loads(raw)
    if encoding == "space": raw = b" " + raw
    elif encoding == "no_lf": raw = raw[:-1]
    elif encoding == "two_lf": raw += b"\n"
    elif encoding == "ascii":
        # An escaped ASCII character is legal JSON but not the canonical encoding.
        raw = raw.replace(b'"schema_version"', b'"schema_versi\\u006fn"', 1)
    elif encoding == "duplicate":
        key = next(iter(obj))
        raw = b"{" + canonical({key: obj[key]})[1:-2] + b"," + raw[1:]
    elif encoding == "nested_duplicate":
        raw = raw.replace(b'"category_id":', b'"category_id":"0303_laptop","category_id":', 1)
        if target == "approval":
            raw = raw.replace(b'"categories":', b'"categories":5,"categories":', 1)
    elif encoding == "nan": raw = b'{"unexpected":NaN}\n'
    elif encoding == "infinity": raw = b'{"unexpected":Infinity}\n'
    elif encoding == "utf8": raw = b'"\xff"\n'
    elif encoding == "array": raw = b"[]\n"
    elif encoding == "scalar": raw = b"null\n"
    else: raw = b"{"
    path.write_bytes(raw)
    if target != "approval":
        key = "coverage_sha256" if target == FILES[1] else "coverage_change_sha256"
        amend_approval(approval, lambda a: a.update({key: sha256(path)}))
    rejects(candidate, approval)


def noninitial(change):
    change.update(from_bundle_version="2.9.0", added=[], removed=[], changed=[])


def current_claims(candidate):
    report = json.loads((candidate / FILES[1]).read_bytes())
    return {(c["category_id"], c["claim_kind"], c["claim_id"]): c for c in report["claims"]}


def changed_row(key, claims):
    current = claims[(key["category_id"], key["claim_kind"], key["claim_id"])]
    reviewed = current["source_state"] == "reviewed"
    return {"claim_key": deepcopy(key),
            "before_source_state": "unknown" if reviewed else "reviewed",
            "before_evidence_level": None if reviewed else "A",
            "after_source_state": current["source_state"],
            "after_evidence_level": current["evidence_level"]}


@pytest.mark.parametrize("current_state", ("reviewed", "unknown"))
def test_noninitial_reviewed_history_is_accepted(approved_candidate, current_state):
    candidate, approval, _ = approved_candidate
    claims = current_claims(candidate)
    def mutation(change):
        added = change["added"][0]
        key = next(k for k in change["added"][1:]
                   if claims[(k["category_id"], k["claim_kind"], k["claim_id"])]["source_state"] == current_state)
        noninitial(change)
        change["added"] = [added]
        change["changed"] = [changed_row(key, claims)]
        change["removed"] = [{**key, "claim_id": "historical_removed"}]
    amend_change(candidate, approval, mutation)
    assert verify_knowledge_release_inputs(candidate, approval).coverage_change_sha256 == sha256(candidate / FILES[2])


@pytest.mark.parametrize("damage", (None, "nonexistent_added", "nonexistent_changed", "current_removed",
                                    "after_state", "after_level"))
def test_noninitial_current_side_is_independently_checked(approved_candidate, damage):
    candidate, approval, _ = approved_candidate
    claims = current_claims(candidate)
    def mutation(change):
        added, changed = deepcopy(change["added"][:2])
        noninitial(change)
        row = changed_row(changed, claims)
        assert row["after_source_state"] == "reviewed"
        change.update(added=[added], changed=[row], removed=[{**added, "claim_id": "historical_removed"}])
        if damage == "nonexistent_added": change["added"][0]["claim_id"] = "absent_added"
        elif damage == "nonexistent_changed": row["claim_key"]["claim_id"] = "absent_changed"
        elif damage == "current_removed":
            # A third current key avoids masking this error with disjointness.
            key = list(claims)[2]
            change["removed"] = [dict(zip(("category_id", "claim_kind", "claim_id"), key))]
        elif damage == "after_state":
            row.update(before_source_state="reviewed", before_evidence_level="A",
                       after_source_state="unknown", after_evidence_level=None)
        elif damage == "after_level":
            row["after_evidence_level"] = "B" if row["after_evidence_level"] == "A" else "A"
    amend_change(candidate, approval, mutation)
    if damage is None:
        assert verify_knowledge_release_inputs(candidate, approval).coverage_change_sha256 == sha256(candidate / FILES[2])
    else:
        rejects(candidate, approval)


@pytest.mark.parametrize("mutation", (
    lambda c: c.update(extra=1), lambda c: c.pop("removed"), lambda c: c.update(schema_version=True),
    lambda c: c.update(schema_version=1.0), lambda c: c.update(schema_version=2),
    lambda c: c.update(to_bundle_version="3.0.1"), lambda c: c.update(from_bundle_version="02.0.0"),
    lambda c: c.update(from_bundle_version=[]), lambda c: c.update(added={}),
    lambda c: c["added"].pop(), lambda c: c["added"].reverse(),
    lambda c: c["added"].append(c["added"][-1]), lambda c: c["added"][0].update(extra=1),
    lambda c: c["added"][0].pop("claim_id"), lambda c: c["added"][0].update(category_id="wrong"),
    lambda c: c["added"][0].update(claim_kind=[]), lambda c: c["added"][0].update(claim_id="bad ID"),
    lambda c: c["known_limitations"].pop(), lambda c: c["known_limitations"].reverse(),
    lambda c: c["known_limitations"][0].update(reason="different reason"),
    lambda c: c["known_limitations"][0].update(extra=1),
    lambda c: c["known_limitations"][0]["claim_key"].update(claim_id="different_key"),
))
def test_initial_change_contract_and_full_unknown_projection(approved_candidate, mutation):
    candidate, approval, _ = approved_candidate
    amend_change(candidate, approval, mutation)
    rejects(candidate, approval)


@pytest.mark.parametrize("collection", ("added", "removed", "changed", "known_limitations"))
@pytest.mark.parametrize("damage", (None, "not_array", "not_object", "missing_key", "extra_key", "category", "kind", "id", "duplicate", "order"))
def test_closed_change_collections_and_claim_keys(approved_candidate, collection, damage):
    candidate, approval, _ = approved_candidate
    claims = current_claims(candidate)
    def mutation(change):
        keys = deepcopy(change["added"][:2])
        noninitial(change)
        if collection == "added": rows = keys
        elif collection == "removed": rows = [{**keys[0], "claim_id": "historical_a"}, {**keys[1], "claim_id": "historical_b"}]
        elif collection == "changed": rows = [changed_row(k, claims) for k in keys]
        else: rows = deepcopy(change["known_limitations"])
        change[collection] = rows
        if damage is None: return
        if damage == "not_array": change[collection] = {}
        elif damage == "not_object": rows[0] = []
        elif damage == "duplicate": rows.append(deepcopy(rows[-1]))
        elif damage == "order": rows.reverse()
        else:
            key = rows[0] if collection in ("added", "removed") else rows[0]["claim_key"]
            if damage == "missing_key": key.pop("claim_id")
            elif damage == "extra_key": key["extra"] = 1
            elif damage == "category": key["category_id"] = []
            elif damage == "kind": key["claim_kind"] = "unsupported"
            else: key["claim_id"] = "UPPER"
    amend_change(candidate, approval, mutation)
    if damage is None:
        assert verify_knowledge_release_inputs(candidate, approval).coverage_change_sha256 == sha256(candidate / FILES[2])
    else:
        rejects(candidate, approval)


@pytest.mark.parametrize("damage", (None, "missing", "extra", "key_type", "before_state", "after_state", "before_level", "after_level",
                                    "before_pair", "after_pair", "noop", "overlap"))
def test_changed_rows_validate_pairings_and_actual_disjoint_changes(approved_candidate, damage):
    candidate, approval, _ = approved_candidate
    claims = current_claims(candidate)
    def mutation(change):
        key = deepcopy(change["added"][0])
        noninitial(change)
        row = changed_row(key, claims)
        change["changed"] = [row]
        if damage is None: return
        if damage == "missing": row.pop("before_source_state")
        elif damage == "extra": row["extra"] = 1
        elif damage == "key_type": row["claim_key"] = []
        elif damage == "before_state": row["before_source_state"] = []
        elif damage == "after_state": row["after_source_state"] = "wrong"
        elif damage == "before_level": row["before_evidence_level"] = 1
        elif damage == "after_level": row["after_evidence_level"] = "E"
        elif damage == "before_pair": row["before_evidence_level"] = "A"
        elif damage == "after_pair": row["after_evidence_level"] = None
        elif damage == "noop": row.update(before_source_state=row["after_source_state"], before_evidence_level=row["after_evidence_level"])
        else: change["added"] = [key]
    amend_change(candidate, approval, mutation)
    if damage is None:
        assert verify_knowledge_release_inputs(candidate, approval).coverage_change_sha256 == sha256(candidate / FILES[2])
    else:
        rejects(candidate, approval)


@pytest.mark.parametrize("target", ("approval", *FILES, "candidate", "ancestor", "extra"))
@pytest.mark.parametrize("mode", ("same_inode", "replacement"))
def test_final_capture_checks_detect_drift_after_real_store_validation(approved_candidate, monkeypatch, target, mode):
    candidate, approval, _ = approved_candidate
    real_store = release.KnowledgeStore
    stores = []
    def mutate_after_store(*args, **kwargs):
        store = real_store(*args, **kwargs)
        stores.append(store)
        if target == "extra":
            (candidate / "new-entry").write_bytes(b"")
        elif target in ("candidate", "ancestor"):
            path = candidate if target == "candidate" else candidate.parent
            saved = path.with_name(path.name + "-saved")
            path.rename(saved)
            shutil.copytree(saved, path)
        else:
            path = approval if target == "approval" else candidate / target
            raw, info = path.read_bytes(), path.stat()
            if mode == "replacement":
                saved = candidate.parent / "replacement-input"
                saved.write_bytes(raw)
                saved.replace(path)
            else:
                # Same length and restored mtime defeat metadata-only drift checks.
                path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                assert path.stat().st_ino == info.st_ino
        return store
    monkeypatch.setattr(release, "KnowledgeStore", mutate_after_store)
    rejects(candidate, approval)
    assert len(stores) == 1
    with pytest.raises(RuntimeError, match="closed"):
        stores[0].list_categories()


def test_all_seven_store_expectations_bind_to_one_approval(approved_candidate, monkeypatch):
    candidate, approval, manifest = approved_candidate
    real_store = release.KnowledgeStore
    calls = []
    def checked_store(database, coverage, **kwargs):
        calls.append(kwargs)
        assert database == candidate / FILES[0] and coverage == candidate / FILES[1]
        assert kwargs == {
            "expected_sha256": sha256(database), "expected_content_sha256": manifest.content_sha256,
            "expected_coverage_sha256": manifest.coverage_sha256, "expected_schema_version": 3,
            "expected_bundle_version": "3.0.0", "expected_identity_catalog_version": "1.0.0",
            "expected_policy_revision": "2.0.0",
        }
        return real_store(database, coverage, **kwargs)
    monkeypatch.setattr(release, "KnowledgeStore", checked_store)
    assert verify_knowledge_release_inputs(candidate, approval).stamp == manifest.stamp
    assert len(calls) == 1


def test_nofollow_open_rejects_link_inserted_after_inspection(approved_candidate, monkeypatch):
    candidate, approval, _ = approved_candidate
    real_open = os.open
    swapped = []
    def replace_before_open(path, flags, *args, **kwargs):
        if str(path) == FILES[2] and not swapped:
            swapped.append(True)
            original = candidate / FILES[2]
            saved = candidate.parent / "saved-change"
            original.rename(saved)
            original.symlink_to(saved)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", replace_before_open)
    rejects(candidate, approval, UNSAFE)
    assert swapped


@pytest.mark.parametrize("mutation", (
    lambda c: c["claims"][0].update(claim_kind=[]),
    lambda c: c["claims"][0].update(evidence_level={}),
    lambda c: c["claims"][0].update(extra=1),
    lambda c: c["summary"].update(categories=True),
    lambda c: c.update(summary=[]),
))
def test_malformed_coverage_shapes_are_normalized(approved_candidate, mutation):
    candidate, approval, _ = approved_candidate
    path = candidate / FILES[1]
    report = json.loads(path.read_bytes())
    mutation(report)
    write_json(path, report)
    amend_approval(approval, lambda a: a.update(coverage_sha256=sha256(path)))
    rejects(candidate, approval)


@pytest.mark.parametrize("outcome", ("success", "bad_json", "unsafe", "store_error", "interrupt", "programmer_error"))
def test_descriptors_close_on_all_exits_and_unexpected_errors_propagate(approved_candidate, monkeypatch, outcome):
    candidate, approval, _ = approved_candidate
    opened = set()
    real_open, real_close = os.open, os.close
    def track_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.add(fd)
        return fd
    def track_close(fd):
        real_close(fd)
        opened.discard(fd)
    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "close", track_close)
    if outcome == "bad_json": approval.write_bytes(b"{")
    elif outcome == "unsafe":
        approval.rename(candidate.parent / "original-approval")
        approval.symlink_to(candidate.parent / "original-approval")
    elif outcome in ("store_error", "interrupt", "programmer_error"):
        error = release.KnowledgeStartupError("synthetic failure") if outcome == "store_error" else KeyboardInterrupt() if outcome == "interrupt" else AssertionError("programmer bug")
        def fail(*args, **kwargs): raise error
        monkeypatch.setattr(release, "KnowledgeStore", fail)
    if outcome == "success": verify_knowledge_release_inputs(candidate, approval)
    elif outcome in ("interrupt", "programmer_error"):
        with pytest.raises(KeyboardInterrupt if outcome == "interrupt" else AssertionError):
            verify_knowledge_release_inputs(candidate, approval)
    else: rejects(candidate, approval, UNSAFE if outcome == "unsafe" else UNAVAILABLE)
    assert not opened


def test_report_floor_is_explicit_even_when_counts_agree(approved_candidate):
    candidate, approval, _ = approved_candidate
    path = candidate / FILES[1]
    report = json.loads(path.read_bytes())
    report["summary"]["component_templates"] = 14
    write_json(path, report)
    amend_approval(approval, lambda a: a.update(corpus_counts=report["summary"], coverage_sha256=sha256(path)))
    # Store metadata would also reject this report; the cause proves the explicit report floor ran.
    with pytest.raises(KnowledgeReleaseError) as caught:
        verify_knowledge_release_inputs(candidate, approval)
    assert "at least 15 component templates" in str(caught.value.__cause__)


def test_coordinated_valid_bundle_report_swap_cannot_rewrite_trust(approved_candidate, tmp_path):
    candidate, approval, _ = approved_candidate
    source = make_valid_knowledge_source(tmp_path / "other-source")
    mutate_yaml(source / "categories" / "0303_laptop" / "sources.yaml",
                lambda d: d["sources"][0].update(title="Different synthetic reviewed source"))
    other = tmp_path / "other-bundle"
    compile_knowledge_bundle(source, other)
    for name in FILES[:2]: shutil.copyfile(other / name, candidate / name)
    report = json.loads((candidate / FILES[1]).read_bytes())
    write_json(candidate / FILES[2], compare_coverage(None, report))
    rejects(candidate, approval)


def run_cli(candidate, approval, *extra):
    return subprocess.run([sys.executable, "scripts/knowledge_release.py", "--candidate", str(candidate),
                           "--approval", str(approval), *extra], cwd=ROOT, capture_output=True, text=True)


def test_cli_is_silent_or_emits_exact_deterministic_summary(approved_candidate):
    candidate, approval, manifest = approved_candidate
    silent = run_cli(candidate, approval)
    assert (silent.returncode, silent.stdout, silent.stderr) == (0, "", "")
    printed = run_cli(candidate, approval, "--print-summary")
    assert printed.returncode == 0 and printed.stderr == ""
    summary = json.loads(printed.stdout)
    assert set(summary) == set(RESULT_FIELDS)
    assert summary == {
        "knowledge_database_path": str(candidate / FILES[0]),
        "evidence_coverage_path": str(candidate / FILES[1]),
        "evidence_coverage_change_path": str(candidate / FILES[2]),
        "knowledge_sha256": sha256(candidate / FILES[0]), "stamp": asdict(manifest.stamp),
        "coverage_sha256": manifest.coverage_sha256,
        "coverage_change_sha256": sha256(candidate / FILES[2]),
    }
    assert printed.stdout.encode() == canonical(summary)
    assert run_cli(candidate, approval, "--print-summary").stdout == printed.stdout


def test_cli_failure_and_usage_exits(approved_candidate):
    candidate, approval, _ = approved_candidate
    approval.write_bytes(b"{")
    failed = run_cli(candidate, approval, "--print-summary")
    assert (failed.returncode, failed.stdout, failed.stderr) == (1, "", UNAVAILABLE + "\n")
    usage = subprocess.run([sys.executable, "scripts/knowledge_release.py", "--cand", str(candidate),
                            "--approval", str(approval)],
                           cwd=ROOT, capture_output=True, text=True)
    assert usage.returncode == 2 and usage.stdout == "" and "usage:" in usage.stderr
