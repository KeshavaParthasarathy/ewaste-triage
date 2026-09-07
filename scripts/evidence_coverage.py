"""Build and validate the immutable full evidence-coverage report."""

from __future__ import annotations

import json
import re
from typing import Mapping
import unicodedata

from scripts.knowledge_schema import EvidenceDocuments
from server.evidence_types import AssociationStatus, RELEASED_CATEGORY_IDS


class CoverageError(ValueError):
    """The full evidence-coverage report violates its closed contract."""


_TOP_LEVEL_FIELDS = (
    "schema_version",
    "bundle_version",
    "knowledge_content_sha256",
    "summary",
    "claims",
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
_CLAIM_FIELDS = (
    "category_id",
    "claim_kind",
    "claim_id",
    "evidence_level",
    "source_state",
    "source_ids",
    "unknown_reason",
)
_CLAIM_KINDS = frozenset(
    {
        "subtype",
        "variant",
        "identity",
        "specific_lifecycle",
        "industry_average",
        "component_association",
        "hazard",
    }
)
_COUNTED_REVIEWED_KINDS = {
    "identity": "canonical_identities",
    "subtype": "subtypes",
    "specific_lifecycle": "lifecycle_records",
    "industry_average": "industry_averages",
    "hazard": "hazard_records",
}
_ID = re.compile(r"[a-z0-9][a-z0-9_.-]*\Z")
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _require_mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CoverageError(f"{location} must be an object")
    return value


def _require_fields(
    value: Mapping[str, object], fields: tuple[str, ...], location: str
) -> None:
    if set(value) != set(fields):
        raise CoverageError(f"{location} fields must be exactly {', '.join(fields)}")


def _require_id(value: object, location: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise CoverageError(f"{location} must be a canonical ID")
    return value


def _require_text(value: object, location: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or unicodedata.normalize("NFC", value) != value
    ):
        raise CoverageError(f"{location} must be non-empty NFC text")
    return value


def build_coverage(
    documents: EvidenceDocuments, content_sha256: str
) -> dict[str, object]:
    if not isinstance(content_sha256, str) or _SHA256.fullmatch(content_sha256) is None:
        raise CoverageError(
            "knowledge_content_sha256 must be a lowercase SHA-256 digest"
        )

    claims: list[dict[str, object]] = []

    def reviewed(
        category_id: str, claim_kind: str, claim_id: str, record: object
    ) -> None:
        evidence_level = getattr(record, "evidence_level")
        source_ids = getattr(record, "source_ids")
        claims.append(
            {
                "category_id": category_id,
                "claim_kind": claim_kind,
                "claim_id": claim_id,
                "evidence_level": evidence_level.value,
                "source_state": "reviewed",
                "source_ids": sorted(source_ids),
                "unknown_reason": None,
            }
        )

    for category in documents.categories:
        category_id = category.category.category_id
        for record in category.subtypes:
            reviewed(category_id, "subtype", record.subtype_id, record)
        for record in category.variants:
            reviewed(category_id, "variant", record.variant_id, record)
        for record in category.identities:
            reviewed(category_id, "identity", record.identity_id, record)
        for record in category.specific_lifecycles:
            reviewed(category_id, "specific_lifecycle", record.record_id, record)
        for record in category.industry_averages:
            reviewed(category_id, "industry_average", record.record_id, record)
        for record in category.component_associations:
            if record.status is not AssociationStatus.UNKNOWN:
                reviewed(
                    category_id,
                    "component_association",
                    record.association_id,
                    record,
                )
        for record in category.hazards:
            reviewed(category_id, "hazard", record.hazard_id, record)
        for record in category.unknowns:
            claims.append(
                {
                    "category_id": record.category_id,
                    "claim_kind": record.claim_kind.value,
                    "claim_id": record.claim_id,
                    "evidence_level": None,
                    "source_state": "unknown",
                    "source_ids": [],
                    "unknown_reason": record.reason,
                }
            )

    claims.sort(
        key=lambda claim: (
            claim["category_id"], claim["claim_kind"], claim["claim_id"]
        )
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "bundle_version": documents.shared.bundle.bundle_version,
        "knowledge_content_sha256": content_sha256,
        "summary": {
            "categories": len(documents.categories),
            "canonical_identities": sum(
                len(category.identities) for category in documents.categories
            ),
            "subtypes": sum(
                len(category.subtypes) for category in documents.categories
            ),
            "lifecycle_records": sum(
                len(category.specific_lifecycles)
                for category in documents.categories
            ),
            "industry_averages": sum(
                len(category.industry_averages) for category in documents.categories
            ),
            "component_templates": sum(
                len(category.component_templates) for category in documents.categories
            ),
            "modern_overlays": sum(
                template.template_kind.value == "modern_overlay"
                for category in documents.categories
                for template in category.component_templates
            ),
            "legacy_overlays": sum(
                template.template_kind.value == "legacy_overlay"
                for category in documents.categories
                for template in category.component_templates
            ),
            "hazard_records": sum(
                len(category.hazards) for category in documents.categories
            ),
            "reviewed_claims": sum(
                claim["source_state"] == "reviewed" for claim in claims
            ),
            "unknown_claims": sum(
                claim["source_state"] == "unknown" for claim in claims
            ),
        },
        "claims": claims,
    }
    validate_coverage_report(report)
    return report


def validate_coverage_report(report: Mapping[str, object]) -> None:
    report = _require_mapping(report, "coverage report")
    _require_fields(report, _TOP_LEVEL_FIELDS, "top-level")

    if type(report["schema_version"]) is not int or report["schema_version"] != 1:
        raise CoverageError("schema_version must be the integer 1")
    bundle_version = report["bundle_version"]
    if not isinstance(bundle_version, str) or _SEMVER.fullmatch(bundle_version) is None:
        raise CoverageError("bundle_version must be canonical SemVer")
    digest = report["knowledge_content_sha256"]
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise CoverageError(
            "knowledge_content_sha256 must be a lowercase SHA-256 digest"
        )

    summary = _require_mapping(report["summary"], "summary")
    _require_fields(summary, _SUMMARY_FIELDS, "summary")
    for field in _SUMMARY_FIELDS:
        value = summary[field]
        if type(value) is not int or value < 0:
            raise CoverageError(f"summary.{field} must be a nonnegative integer")

    raw_claims = report["claims"]
    if not isinstance(raw_claims, list):
        raise CoverageError("claims must be an array")
    claim_keys: list[tuple[str, str, str]] = []
    reviewed_count = 0
    unknown_count = 0
    reviewed_kind_counts = {kind: 0 for kind in _COUNTED_REVIEWED_KINDS}
    for index, raw_claim in enumerate(raw_claims):
        claim = _require_mapping(raw_claim, f"claims[{index}]")
        _require_fields(claim, _CLAIM_FIELDS, "claim")
        category_id = claim["category_id"]
        if category_id not in RELEASED_CATEGORY_IDS:
            raise CoverageError(f"claims[{index}].category_id is not released")
        claim_kind = claim["claim_kind"]
        if claim_kind not in _CLAIM_KINDS:
            raise CoverageError(f"claims[{index}].claim_kind is not supported")
        claim_id = _require_id(claim["claim_id"], f"claims[{index}].claim_id")
        source_state = claim["source_state"]
        source_ids = claim["source_ids"]
        if not isinstance(source_ids, list):
            raise CoverageError(f"claims[{index}].source_ids must be an array")
        checked_sources = [
            _require_id(source_id, f"claims[{index}].source_ids")
            for source_id in source_ids
        ]
        if len(set(checked_sources)) != len(checked_sources):
            raise CoverageError(f"claims[{index}].source_ids must be unique")
        if checked_sources != sorted(checked_sources):
            raise CoverageError(f"claims[{index}].source_ids must be sorted")

        if source_state == "reviewed":
            if claim["evidence_level"] not in {"A", "B", "C", "D"}:
                raise CoverageError(f"claims[{index}] reviewed claim needs evidence")
            if not checked_sources or claim["unknown_reason"] is not None:
                raise CoverageError(
                    f"claims[{index}] reviewed claim needs sources and null reason"
                )
            reviewed_count += 1
            if claim_kind in reviewed_kind_counts:
                reviewed_kind_counts[claim_kind] += 1
        elif source_state == "unknown":
            if claim["evidence_level"] is not None or checked_sources:
                raise CoverageError(
                    f"claims[{index}] unknown claim needs null evidence and no sources"
                )
            _require_text(
                claim["unknown_reason"], f"claims[{index}].unknown_reason"
            )
            unknown_count += 1
        else:
            raise CoverageError(f"claims[{index}].source_state is not supported")
        claim_keys.append((str(category_id), str(claim_kind), claim_id))

    if len(set(claim_keys)) != len(claim_keys):
        raise CoverageError("claims contain a duplicate claim key")
    if claim_keys != sorted(claim_keys):
        raise CoverageError("claims must be sorted by category, kind, and ID")
    if summary["reviewed_claims"] != reviewed_count:
        raise CoverageError("summary.reviewed_claims does not match claims")
    if summary["unknown_claims"] != unknown_count:
        raise CoverageError("summary.unknown_claims does not match claims")
    for claim_kind, summary_field in _COUNTED_REVIEWED_KINDS.items():
        if summary[summary_field] != reviewed_kind_counts[claim_kind]:
            raise CoverageError(
                f"summary.{summary_field} does not match reviewed {claim_kind} claims"
            )


def coverage_json_bytes(report: Mapping[str, object]) -> bytes:
    validate_coverage_report(report)
    try:
        return json.dumps(
            report,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise CoverageError(f"coverage report is not canonical JSON: {exc}") from exc
