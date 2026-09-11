#!/usr/bin/env python3
"""Read-only verification of a closed three-artifact knowledge release candidate.

The caller supplies the reviewed, source-controlled approval trust root. This
checks its captured bytes and endpoint filesystem consistency, not that a human
review occurred or that files remain unchanged after return. The packaging
consumer must reacquire sources without following links and verify copied bytes
against the returned hashes and canonical stamp.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import date
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence_coverage import (
    CoverageError, compare_coverage, coverage_json_bytes, validate_coverage_report,
    validate_release_floor,
)
from server.evidence_types import BundleStamp, RELEASED_CATEGORY_IDS
from server.knowledge_store import KnowledgeStartupError, KnowledgeStore


class KnowledgeReleaseError(RuntimeError):
    """The supplied release inputs could not be safely verified."""


_UNSAFE = "unsafe release input path"
_UNAVAILABLE = "knowledge release inputs unavailable or incompatible"
_FILES = ("knowledge.sqlite", "evidence-coverage.json", "evidence-coverage-change.json")
_APPROVAL_FIELDS = {
    "approval_schema_version", "schema_version", "bundle_version", "identity_catalog_version",
    "policy_revision", "knowledge_sha256", "content_sha256", "coverage_sha256",
    "coverage_change_sha256", "corpus_counts", "reviewed_by", "reviewed_on",
}
_SUMMARY_FIELDS = {
    "categories", "canonical_identities", "subtypes", "lifecycle_records", "industry_averages",
    "component_templates", "modern_overlays", "legacy_overlays", "hazard_records",
    "reviewed_claims", "unknown_claims",
}
_KEY_FIELDS = {"category_id", "claim_kind", "claim_id"}
_KINDS = ("subtype", "variant", "identity", "specific_lifecycle", "industry_average",
          "component_association", "hazard")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9_.-]*\Z")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


@dataclass(frozen=True)
class KnowledgeReleaseInputs:
    knowledge_database_path: Path
    evidence_coverage_path: Path
    evidence_coverage_change_path: Path
    knowledge_sha256: str
    stamp: BundleStamp
    coverage_sha256: str
    coverage_change_sha256: str


class _InvalidInput(ValueError):
    """A checked content or filesystem consistency constraint failed."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise _InvalidInput(reason)


def _closed(value: object, keys: set[str], reason: str) -> dict:
    _require(type(value) is dict and set(value) == keys, reason)
    return value


def _matches(value: object, pattern: re.Pattern) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8") + b"\n"


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise _InvalidInput("nonfinite JSON constant")


def _parse(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        _require(type(value) is dict, "JSON root must be an object")
        _require(_json_bytes(value) == data, "noncanonical JSON bytes")
        return value
    except (ValueError, RecursionError) as exc:
        raise _InvalidInput("invalid canonical UTF-8 JSON") from exc


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


class _CapturedPath:
    """Hold no-follow descriptors for every path component until final checks."""

    def __init__(self, path: Path, handles: ExitStack, *, directory: bool = False):
        if ".." in path.parts:
            raise KnowledgeReleaseError(_UNSAFE)
        absolute = path.absolute()
        # No resolve() may erase an originally symlinked component. Traversal
        # below proves these absolute components are real directories/files.
        self.path = Path("/").joinpath(*absolute.parts[1:])
        self.entries = []
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        handles.callback(os.close, descriptor)
        self.root = descriptor, _identity(os.fstat(descriptor))
        names = self.path.parts[1:]
        if not names and not directory:
            raise KnowledgeReleaseError(_UNSAFE)
        for index, name in enumerate(names):
            want_directory = index < len(names) - 1 or directory
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            safe_type = stat.S_ISDIR(info.st_mode) if want_directory else stat.S_ISREG(info.st_mode)
            if not safe_type:
                raise KnowledgeReleaseError(_UNSAFE)
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if want_directory:
                flags |= os.O_DIRECTORY
            child = os.open(name, flags, dir_fd=descriptor)
            handles.callback(os.close, child)
            captured = os.fstat(child)
            safe_type = stat.S_ISDIR(captured.st_mode) if want_directory else stat.S_ISREG(captured.st_mode)
            if not safe_type:
                raise KnowledgeReleaseError(_UNSAFE)
            _require(_identity(captured) == _identity(info), "input replaced during capture")
            self.entries.append((descriptor, name, child, _identity(captured)))
            descriptor = child
        self.descriptor = descriptor
        self.identity = _identity(os.fstat(descriptor))

    def read(self) -> bytes:
        os.lseek(self.descriptor, 0, os.SEEK_SET)
        chunks = []
        while chunk := os.read(self.descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)

    def recheck(self) -> None:
        root, identity = self.root
        _require(_identity(os.fstat(root)) == identity, "root identity changed")
        for parent, name, child, identity in self.entries:
            _require(_identity(os.fstat(child)) == identity, "descriptor identity changed")
            _require(_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == identity,
                     "input path identity changed")


def _capture_inputs(candidate: Path, approval: Path, handles: ExitStack) -> list[_CapturedPath]:
    captures = []
    unavailable = None
    # Inspect every input before any content read. Defer absent/unavailable
    # failures so existing unsafe objects retain their specified precedence.
    for path, directory in [(candidate, True), (approval, False),
                            *((candidate / name, False) for name in _FILES)]:
        try:
            captures.append(_CapturedPath(path, handles, directory=directory))
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise KnowledgeReleaseError(_UNSAFE) from exc
            unavailable = exc
        except _InvalidInput as exc:
            unavailable = exc
    if unavailable is not None:
        raise KnowledgeReleaseError(_UNAVAILABLE) from unavailable
    directory, approval_file, *artifacts = captures
    if approval_file.path.is_relative_to(directory.path):
        raise KnowledgeReleaseError(_UNSAFE)
    files = [approval_file, *artifacts]
    if len({f.identity[:2] for f in files}) != len(files):
        raise KnowledgeReleaseError(_UNSAFE)
    for artifact in artifacts:
        if (artifact.path.parent != directory.path or
                _identity(os.fstat(artifact.entries[-1][0])) != directory.identity):
            raise KnowledgeReleaseError(_UNSAFE)
    _require(set(os.listdir(directory.descriptor)) == set(_FILES), "candidate entry set")
    return captures


def _validate_approval(approval: dict) -> None:
    _closed(approval, _APPROVAL_FIELDS, "approval fields")
    for key, expected in (("approval_schema_version", 1), ("schema_version", 3),
                          ("bundle_version", "3.0.0"), ("identity_catalog_version", "1.0.0"),
                          ("policy_revision", "2.0.0")):
        value = approval[key]
        _require(type(value) is type(expected) and value == expected, "approval version")
    for key in ("knowledge_sha256", "content_sha256", "coverage_sha256", "coverage_change_sha256"):
        _require(_matches(approval[key], _HASH), "approval hash")
    counts = _closed(approval["corpus_counts"], _SUMMARY_FIELDS, "approval count fields")
    _require(all(type(value) is int and value > 0 for value in counts.values()), "approval counts")
    reviewer, reviewed_on = approval["reviewed_by"], approval["reviewed_on"]
    _require(type(reviewer) is str and bool(reviewer.strip()), "approval reviewer")
    _require(type(reviewed_on) is str, "approval date type")
    try:
        _require(date.fromisoformat(reviewed_on).isoformat() == reviewed_on, "approval date spelling")
    except ValueError as exc:
        raise _InvalidInput("approval calendar date") from exc


def _claim_key(value: object) -> tuple[str, str, str]:
    key = _closed(value, _KEY_FIELDS, "change claim key fields")
    _require(key["category_id"] in RELEASED_CATEGORY_IDS, "change category")
    _require(key["claim_kind"] in _KINDS, "change claim kind")
    _require(_matches(key["claim_id"], _ID), "change claim ID")
    return key["category_id"], key["claim_kind"], key["claim_id"]


def _validate_change(change: dict, coverage: dict) -> None:
    """Explicit closed validator for evidence-coverage-change.schema.json.

    Producer ordering, disjointness and current-side semantics are additionally
    enforced. Historical before/removed data and noninitial completeness remain
    authenticated by the administrator's approved change hash.
    """
    _closed(change, {"schema_version", "from_bundle_version", "to_bundle_version",
                     "added", "removed", "changed", "known_limitations"}, "change fields")
    _require(type(change["schema_version"]) is int and change["schema_version"] == 1, "change schema")
    previous = change["from_bundle_version"]
    _require(previous is None or _matches(previous, _VERSION), "change previous version")
    _require(change["to_bundle_version"] == "3.0.0", "change target version")
    keys = {}
    for collection in ("added", "removed", "changed", "known_limitations"):
        rows = change[collection]
        _require(type(rows) is list, "change collection type")
        ordered = []
        for row in rows:
            if collection in ("added", "removed"):
                key = _claim_key(row)
            else:
                expected = {"claim_key", "reason"} if collection == "known_limitations" else {
                    "claim_key", "before_source_state", "after_source_state",
                    "before_evidence_level", "after_evidence_level"}
                _closed(row, expected, "change row fields")
                key = _claim_key(row["claim_key"])
                if collection == "known_limitations":
                    _require(type(row["reason"]) is str and len(row["reason"]) > 0, "limitation reason")
                else:
                    for side in ("before", "after"):
                        state, level = row[side + "_source_state"], row[side + "_evidence_level"]
                        _require((state == "reviewed" and level in ("A", "B", "C", "D")) or
                                 (state == "unknown" and level is None), "change state/evidence pairing")
                    _require((row["before_source_state"], row["before_evidence_level"]) !=
                             (row["after_source_state"], row["after_evidence_level"]), "no-op change")
            ordered.append(key)
        _require(ordered == sorted(set(ordered)), "change key order/uniqueness")
        keys[collection] = set(ordered)
    _require(not (keys["added"] & keys["removed"] or keys["added"] & keys["changed"] or
                  keys["removed"] & keys["changed"]), "overlapping change keys")
    current = {(c["category_id"], c["claim_kind"], c["claim_id"]): c for c in coverage["claims"]}
    _require(keys["added"] <= current.keys() and keys["changed"] <= current.keys(), "missing current claim")
    _require(not keys["removed"] & current.keys(), "removed claim still current")
    for row in change["changed"]:
        claim = current[_claim_key(row["claim_key"])]
        _require(row["after_source_state"] == claim["source_state"] and
                 row["after_evidence_level"] == claim["evidence_level"], "changed after-values differ")
    initial = compare_coverage(None, coverage)
    _require(change["known_limitations"] == initial["known_limitations"], "current limitation projection")
    if previous is None:
        _require(change == initial, "incomplete initial change")


def verify_knowledge_release_inputs(candidate_dir: Path, approval_path: Path) -> KnowledgeReleaseInputs:
    """Verify supplied artifacts without writing, compiling, staging or approving."""
    try:
        with ExitStack() as handles:
            captures = _capture_inputs(Path(candidate_dir), Path(approval_path), handles)
            directory, approval_file, database, coverage_file, change_file = captures
            files = [approval_file, database, coverage_file, change_file]
            raw_approval, raw_database, raw_coverage, raw_change = captured = [f.read() for f in files]
            captured_hashes = [hashlib.sha256(raw).hexdigest() for raw in captured]
            approval = _parse(raw_approval)
            _validate_approval(approval)
            for digest, field in zip(captured_hashes[1:],
                                     ("knowledge_sha256", "coverage_sha256", "coverage_change_sha256")):
                _require(digest == approval[field], "approved hash mismatch")
            coverage = _parse(raw_coverage)
            # The accepted administrative validator may raise TypeError for an
            # unhashable malformed claim scalar. Normalize only this boundary.
            try:
                validate_coverage_report(coverage)
                _require(coverage_json_bytes(coverage) == raw_coverage, "canonical coverage bytes")
                validate_release_floor(coverage)
            except TypeError as exc:
                raise _InvalidInput("invalid coverage shape") from exc
            _require(approval["corpus_counts"] == coverage["summary"], "approval/report count mismatch")
            change = _parse(raw_change)
            _validate_change(change, coverage)
            with KnowledgeStore(
                database.path, coverage_file.path,
                expected_sha256=approval["knowledge_sha256"],
                expected_content_sha256=approval["content_sha256"],
                expected_coverage_sha256=approval["coverage_sha256"],
                expected_schema_version=approval["schema_version"],
                expected_bundle_version=approval["bundle_version"],
                expected_identity_catalog_version=approval["identity_catalog_version"],
                expected_policy_revision=approval["policy_revision"],
            ) as store:
                result = KnowledgeReleaseInputs(
                    database.path, coverage_file.path, change_file.path, approval["knowledge_sha256"],
                    store.manifest.stamp, approval["coverage_sha256"], approval["coverage_change_sha256"],
                )
                for file, original, digest in zip(files, captured, captured_hashes):
                    current_bytes = file.read()
                    _require(current_bytes == original and hashlib.sha256(current_bytes).hexdigest() == digest,
                             "captured input bytes changed")
                for capture in captures:
                    capture.recheck()
                _require(set(os.listdir(directory.descriptor)) == set(_FILES), "candidate entries changed")
                return result
    except (OSError, _InvalidInput, CoverageError, KnowledgeStartupError) as exc:
        raise KnowledgeReleaseError(_UNAVAILABLE) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify_knowledge_release_inputs(args.candidate, args.approval)
    except KnowledgeReleaseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.print_summary:
        summary = asdict(result)
        for field in ("knowledge_database_path", "evidence_coverage_path", "evidence_coverage_change_path"):
            summary[field] = str(summary[field])
        sys.stdout.write(_json_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
