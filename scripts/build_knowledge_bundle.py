#!/usr/bin/env python3
"""Compile reviewed schema-3 knowledge YAML into one atomic bundle directory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evidence_coverage import CoverageError, validate_coverage_report
from scripts.knowledge_compiler import KnowledgeCompilationError, compile_knowledge_bundle
from scripts.knowledge_schema import EvidenceValidationError
from server.evidence_types import RELEASED_CATEGORY_IDS


_CLAIM_KIND_ORDER = (
    "subtype",
    "variant",
    "identity",
    "specific_lifecycle",
    "industry_average",
    "component_association",
    "hazard",
)
_SUMMARY_FIELDS = (
    "categories",
    "canonical_identities",
    "subtypes",
    "lifecycle_records",
    "industry_averages",
    "component_templates",
    "modern_overlays",
    "legacy_overlays",
    "hazard_records",
    "reviewed_claims",
    "unknown_claims",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_knowledge_bundle.py",
        usage="%(prog)s --source PATH --out DIRECTORY [--print-summary]",
        description=__doc__,
        allow_abbrev=False,
    )
    parser.add_argument(
        "--source",
        type=Path,
        metavar="PATH",
        required=True,
        help="reviewed schema-3 source directory",
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="DIRECTORY",
        required=True,
        help="destination bundle directory",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="print the deterministic bundle summary",
    )
    return parser


def _read_published_coverage(destination: Path) -> dict[str, object]:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory = os.open(destination, directory_flags)
    descriptor = -1
    try:
        descriptor = os.open(
            "evidence-coverage.json",
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory,
        )
        result = os.fstat(descriptor)
        if not stat.S_ISREG(result.st_mode):
            raise KnowledgeCompilationError(
                "published evidence coverage is not a regular file"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory)
    try:
        report = json.loads(b"".join(chunks))
    except json.JSONDecodeError as exc:
        raise CoverageError(f"published evidence coverage is invalid: {exc}") from exc
    validate_coverage_report(report)
    return report


def _summary_lines(
    manifest: object, report: dict[str, object]
) -> tuple[str, ...]:
    summary = report["summary"]
    claims = report["claims"]
    lines = [
        "knowledge bundle summary",
        f"schema_version={manifest.schema_version}",
        f"bundle_version={manifest.bundle_version}",
        f"identity_catalog_version={manifest.identity_catalog_version}",
        f"policy_revision={manifest.policy_revision}",
    ]
    lines.extend(f"summary.{field}={summary[field]}" for field in _SUMMARY_FIELDS)
    for category_id in RELEASED_CATEGORY_IDS:
        for claim_kind in _CLAIM_KIND_ORDER:
            reviewed = sum(
                claim["category_id"] == category_id
                and claim["claim_kind"] == claim_kind
                and claim["source_state"] == "reviewed"
                for claim in claims
            )
            unknown = sum(
                claim["category_id"] == category_id
                and claim["claim_kind"] == claim_kind
                and claim["source_state"] == "unknown"
                for claim in claims
            )
            lines.append(
                f"claims {category_id} {claim_kind} "
                f"reviewed={reviewed} unknown={unknown}"
            )
    lines.extend(
        (
            f"content_sha256={manifest.content_sha256}",
            f"coverage_sha256={manifest.coverage_sha256}",
        )
    )
    return tuple(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        manifest = compile_knowledge_bundle(args.source, args.out)
        if args.print_summary:
            report = _read_published_coverage(_absolute(args.out))
            sys.stdout.write("\n".join(_summary_lines(manifest, report)) + "\n")
    except (
        CoverageError,
        EvidenceValidationError,
        KnowledgeCompilationError,
        OSError,
        sqlite3.Error,
    ) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    return 0


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


if __name__ == "__main__":
    raise SystemExit(main())
