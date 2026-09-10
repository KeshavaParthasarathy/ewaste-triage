"""Independent contracts for the immutable full evidence-coverage report."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Mapping

import pytest

import scripts.evidence_coverage as coverage_module
from scripts.evidence_coverage import (
    CoverageError,
    build_coverage,
    coverage_json_bytes,
    validate_coverage_report,
)
from scripts.knowledge_schema import (
    EvidenceDocuments,
    TemplateKind,
    load_evidence_documents,
)
from server.evidence_types import (
    AssociationStatus,
    BatteryArchitecture,
    MarketState,
    RELEASED_CATEGORY_IDS,
)
from tests.knowledge_helpers import make_valid_knowledge_source


SUMMARY_FIELDS = (
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
CLAIM_FIELDS = (
    "category_id",
    "claim_kind",
    "claim_id",
    "evidence_level",
    "source_state",
    "source_ids",
    "unknown_reason",
)
CLAIM_KINDS = (
    "subtype",
    "variant",
    "identity",
    "specific_lifecycle",
    "industry_average",
    "component_association",
    "hazard",
)
ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"


@pytest.fixture
def valid_documents(tmp_path: Path) -> EvidenceDocuments:
    return load_evidence_documents(make_valid_knowledge_source(tmp_path / "source"))


def expected_coverage_report(
    documents: EvidenceDocuments, content_sha256: str
) -> dict[str, object]:
    """Traverse normalized records independently of the production builder."""
    claims: list[dict[str, object]] = []

    def reviewed(category_id: str, kind: str, claim_id: str, record: object) -> None:
        evidence = getattr(record, "evidence_level")
        source_ids = getattr(record, "source_ids")
        claims.append(
            {
                "category_id": category_id,
                "claim_kind": kind,
                "claim_id": claim_id,
                "evidence_level": evidence.value,
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
        key=lambda item: (
            item["category_id"],
            item["claim_kind"],
            item["claim_id"],
        )
    )
    reviewed_count = sum(item["source_state"] == "reviewed" for item in claims)
    unknown_count = sum(item["source_state"] == "unknown" for item in claims)
    return {
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
            "reviewed_claims": reviewed_count,
            "unknown_claims": unknown_count,
        },
        "claims": claims,
    }


def expected_coverage_bytes(report: dict[str, object]) -> bytes:
    return json.dumps(
        report,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def _mutate_first_unknown(
    report: dict[str, object], field: str, value: object
) -> None:
    claim = next(
        item for item in report["claims"] if item["source_state"] == "unknown"
    )
    claim[field] = value


def test_full_coverage_matches_independent_oracle_and_exact_bytes(
    valid_documents: EvidenceDocuments,
) -> None:
    expected = expected_coverage_report(valid_documents, "a" * 64)
    report = build_coverage(valid_documents, "a" * 64)

    assert report == expected
    assert list(report) == [
        "schema_version",
        "bundle_version",
        "knowledge_content_sha256",
        "summary",
        "claims",
    ]
    assert list(report["summary"]) == list(SUMMARY_FIELDS)
    assert all(list(claim) == list(CLAIM_FIELDS) for claim in report["claims"])
    assert coverage_json_bytes(report) == expected_coverage_bytes(expected)


def test_fixture_coverage_counts_and_claim_semantics_are_pinned(
    valid_documents: EvidenceDocuments,
) -> None:
    report = build_coverage(valid_documents, "b" * 64)

    assert report["summary"] == {
        "categories": 5,
        "canonical_identities": 50,
        "subtypes": 20,
        "lifecycle_records": 15,
        "industry_averages": 5,
        "component_templates": 15,
        "modern_overlays": 5,
        "legacy_overlays": 5,
        "hazard_records": 5,
        "reviewed_claims": 155,
        "unknown_claims": 5,
    }
    assert len(report["claims"]) == 160
    assert report["claims"] == sorted(
        report["claims"],
        key=lambda item: (
            item["category_id"], item["claim_kind"], item["claim_id"]
        ),
    )
    assert all(
        claim["claim_kind"] in CLAIM_KINDS for claim in report["claims"]
    )


def test_unknown_association_emits_only_its_matching_unknown_claim(
    valid_documents: EvidenceDocuments,
) -> None:
    report = build_coverage(valid_documents, "c" * 64)
    category = RELEASED_CATEGORY_IDS[0]
    claim_id = f"{category}_association_modern_1_unknown"
    matches = [
        claim
        for claim in report["claims"]
        if claim["category_id"] == category
        and claim["claim_kind"] == "component_association"
        and claim["claim_id"] == claim_id
    ]

    assert matches == [
        {
            "category_id": category,
            "claim_kind": "component_association",
            "claim_id": claim_id,
            "evidence_level": None,
            "source_state": "unknown",
            "source_ids": [],
            "unknown_reason": "No reviewed exact association is available.",
        }
    ]


def test_builder_sorts_source_ids_without_mutating_documents(
    valid_documents: EvidenceDocuments,
) -> None:
    category = valid_documents.categories[0]
    first = category.subtypes[0]
    changed = replace(
        valid_documents,
        categories=(
            replace(
                category,
                subtypes=(
                    replace(
                        first,
                        source_ids=(
                            f"{category.category.category_id}_hazard_source",
                            f"{category.category.category_id}_claim_source",
                        ),
                    ),
                    *category.subtypes[1:],
                ),
            ),
            *valid_documents.categories[1:],
        ),
    )

    report = build_coverage(changed, "d" * 64)
    claim = next(
        item for item in report["claims"] if item["claim_id"] == first.subtype_id
    )
    assert claim["source_ids"] == sorted(first_id for first_id in changed.categories[0].subtypes[0].source_ids)
    assert changed.categories[0].subtypes[0].source_ids[0].endswith("hazard_source")


@pytest.mark.parametrize(
    ("name", "mutation", "message"),
    [
        (
            "top-level-extra",
            lambda report: report.__setitem__("extra", 1),
            "top-level fields",
        ),
        (
            "schema-bool",
            lambda report: report.__setitem__("schema_version", True),
            "schema_version",
        ),
        (
            "bundle-version",
            lambda report: report.__setitem__("bundle_version", "03.0.0"),
            "bundle_version",
        ),
        (
            "hash-uppercase",
            lambda report: report.__setitem__(
                "knowledge_content_sha256", "A" * 64
            ),
            "knowledge_content_sha256",
        ),
        (
            "summary-extra",
            lambda report: report["summary"].__setitem__("extra", 0),
            "summary fields",
        ),
        (
            "summary-bool",
            lambda report: report["summary"].__setitem__("categories", True),
            "summary.categories",
        ),
        (
            "claim-extra",
            lambda report: report["claims"][0].__setitem__("extra", None),
            "claim fields",
        ),
        (
            "category",
            lambda report: report["claims"][0].__setitem__(
                "category_id", "not_released"
            ),
            "category_id",
        ),
        (
            "claim-kind",
            lambda report: report["claims"][0].__setitem__("claim_kind", "policy"),
            "claim_kind",
        ),
        (
            "claim-id",
            lambda report: report["claims"][0].__setitem__("claim_id", "Bad ID"),
            "claim_id",
        ),
        (
            "reviewed-evidence-null",
            lambda report: report["claims"][0].__setitem__(
                "evidence_level", None
            ),
            "reviewed claim",
        ),
        (
            "reviewed-reason",
            lambda report: report["claims"][0].__setitem__(
                "unknown_reason", "not null"
            ),
            "reviewed claim",
        ),
        (
            "reviewed-empty-sources",
            lambda report: report["claims"][0].__setitem__("source_ids", []),
            "reviewed claim",
        ),
        (
            "unknown-evidence",
            lambda report: _mutate_first_unknown(report, "evidence_level", "D"),
            "unknown claim",
        ),
        (
            "unknown-sources",
            lambda report: _mutate_first_unknown(
                report, "source_ids", ["source"]
            ),
            "unknown claim",
        ),
        (
            "unsorted-sources",
            lambda report: report["claims"][0].__setitem__(
                "source_ids", ["z_source", "a_source"]
            ),
            "sorted",
        ),
        (
            "duplicate-source",
            lambda report: report["claims"][0].__setitem__(
                "source_ids", ["same", "same"]
            ),
            "unique",
        ),
        (
            "unsorted-claims",
            lambda report: report["claims"].reverse(),
            "sorted",
        ),
        (
            "duplicate-claim",
            lambda report: report["claims"].insert(
                0, deepcopy(report["claims"][0])
            ),
            "duplicate",
        ),
        (
            "reviewed-count",
            lambda report: report["summary"].__setitem__("reviewed_claims", 0),
            "reviewed_claims",
        ),
        (
            "kind-count",
            lambda report: report["summary"].__setitem__("subtypes", 0),
            "subtypes",
        ),
    ],
)
def test_validator_rejects_each_closed_shape_semantic_mutation(
    valid_documents: EvidenceDocuments,
    name: str,
    mutation: object,
    message: str,
) -> None:
    del name
    report = build_coverage(valid_documents, "e" * 64)
    mutation(report)
    with pytest.raises(CoverageError, match=message):
        validate_coverage_report(report)


@pytest.mark.parametrize(
    "forbidden",
    [
        pytest.param("\x00", id="Cc-NUL"),
        pytest.param("\u200e", id="Cf-format"),
        pytest.param("\ud800", id="Cs-surrogate"),
        pytest.param("\ue000", id="Co-private-use"),
        pytest.param("\u0378", id="Cn-unassigned"),
    ],
)
def test_unknown_reason_rejects_every_unicode_control_category(
    valid_documents: EvidenceDocuments,
    forbidden: str,
) -> None:
    report = build_coverage(valid_documents, "f" * 64)
    _mutate_first_unknown(report, "unknown_reason", f"Before{forbidden}after")

    with pytest.raises(CoverageError, match="Unicode control"):
        validate_coverage_report(report)


def test_builder_rejects_duplicate_claim_keys(valid_documents: EvidenceDocuments) -> None:
    category = valid_documents.categories[0]
    changed = replace(
        valid_documents,
        categories=(
            replace(category, subtypes=category.subtypes + (category.subtypes[0],)),
            *valid_documents.categories[1:],
        ),
    )
    with pytest.raises(CoverageError, match="duplicate"):
        build_coverage(changed, "f" * 64)


@pytest.mark.parametrize("bad_hash", ["", "A" * 64, "a" * 63, True, None])
def test_builder_rejects_noncanonical_content_hash(
    valid_documents: EvidenceDocuments, bad_hash: object
) -> None:
    with pytest.raises(CoverageError, match="knowledge_content_sha256"):
        build_coverage(valid_documents, bad_hash)  # type: ignore[arg-type]


def _sort_claims(report: dict[str, object]) -> None:
    report["claims"].sort(
        key=lambda claim: (
            claim["category_id"], claim["claim_kind"], claim["claim_id"]
        )
    )


def _reviewed_association(report: dict[str, object]) -> dict[str, object]:
    return next(
        claim
        for claim in report["claims"]
        if claim["source_state"] == "reviewed"
        and claim["claim_kind"] == "component_association"
    )


def _unknown_claim(report: dict[str, object]) -> dict[str, object]:
    return next(
        claim for claim in report["claims"] if claim["source_state"] == "unknown"
    )


def _changed_coverage_fields(
    before: dict[str, object], after: dict[str, object]
) -> frozenset[tuple[str, str]]:
    changed: set[tuple[str, str]] = set()
    for field in ("schema_version", "bundle_version", "knowledge_content_sha256"):
        if before[field] != after[field]:
            changed.add(("top", field))
    if before["summary"] != after["summary"]:
        changed.add(("top", "summary"))
    if before["claims"] != after["claims"]:
        changed.add(("top", "claims"))
    for field in SUMMARY_FIELDS:
        if before["summary"][field] != after["summary"][field]:
            changed.add(("summary", field))
    for field in CLAIM_FIELDS:
        before_values = sorted(
            json.dumps(claim[field], sort_keys=True) for claim in before["claims"]
        )
        after_values = sorted(
            json.dumps(claim[field], sort_keys=True) for claim in after["claims"]
        )
        if before_values != after_values:
            changed.add(("claim", field))
    return frozenset(changed)


def _valid_coverage_mutations() -> tuple[
    tuple[str, frozenset[tuple[str, str]], object], ...
]:
    top_claims = {("top", "claims")}
    top_summary = {("top", "summary")}
    all_claim_fields = {("claim", field) for field in CLAIM_FIELDS}

    def summary(field: str) -> object:
        return lambda report: report["summary"].__setitem__(
            field, report["summary"][field] + 1
        )

    def reviewed_field(field: str, value: object) -> object:
        return lambda report: _reviewed_association(report).__setitem__(field, value)

    def unknown_reason(report: dict[str, object]) -> None:
        claim = _unknown_claim(report)
        claim["unknown_reason"] += " Updated."

    def claim_category(report: dict[str, object]) -> None:
        claim = _reviewed_association(report)
        claim["category_id"] = RELEASED_CATEGORY_IDS[1]
        _sort_claims(report)

    def claim_kind(report: dict[str, object]) -> None:
        claim = _reviewed_association(report)
        claim["claim_kind"] = "variant"
        _sort_claims(report)

    def claim_id(report: dict[str, object]) -> None:
        claim = _reviewed_association(report)
        claim["claim_id"] += "_changed"
        _sort_claims(report)

    def reviewed_to_unknown(report: dict[str, object]) -> None:
        claim = _reviewed_association(report)
        claim.update(
            evidence_level=None,
            source_state="unknown",
            source_ids=[],
            unknown_reason="Awaiting reviewed evidence.",
        )
        report["summary"]["reviewed_claims"] -= 1
        report["summary"]["unknown_claims"] += 1

    def add_claim(report: dict[str, object], kind: str, summary_field: str | None) -> None:
        report["claims"].append(
            {
                "category_id": RELEASED_CATEGORY_IDS[0],
                "claim_kind": kind,
                "claim_id": f"added_{kind}",
                "evidence_level": "B",
                "source_state": "reviewed",
                "source_ids": ["added_source"],
                "unknown_reason": None,
            }
        )
        report["summary"]["reviewed_claims"] += 1
        if summary_field is not None:
            report["summary"][summary_field] += 1
        _sort_claims(report)

    cases: list[tuple[str, frozenset[tuple[str, str]], object]] = [
        (
            "bundle-version",
            frozenset({("top", "bundle_version")}),
            lambda report: report.__setitem__("bundle_version", "3.0.1"),
        ),
        (
            "content-hash",
            frozenset({("top", "knowledge_content_sha256")}),
            lambda report: report.__setitem__("knowledge_content_sha256", "2" * 64),
        ),
        (
            "claim-category",
            frozenset(top_claims | {("claim", "category_id")}),
            claim_category,
        ),
        (
            "claim-kind",
            frozenset(top_claims | {("claim", "claim_kind")}),
            claim_kind,
        ),
        (
            "claim-id",
            frozenset(top_claims | {("claim", "claim_id")}),
            claim_id,
        ),
        (
            "reviewed-evidence",
            frozenset(top_claims | {("claim", "evidence_level")}),
            reviewed_field("evidence_level", "C"),
        ),
        (
            "reviewed-sources",
            frozenset(top_claims | {("claim", "source_ids")}),
            reviewed_field("source_ids", ["replacement_source"]),
        ),
        (
            "unknown-reason",
            frozenset(top_claims | {("claim", "unknown_reason")}),
            unknown_reason,
        ),
        (
            "reviewed-to-unknown",
            frozenset(
                top_claims
                | top_summary
                | {
                    ("claim", "evidence_level"),
                    ("claim", "source_state"),
                    ("claim", "source_ids"),
                    ("claim", "unknown_reason"),
                    ("summary", "reviewed_claims"),
                    ("summary", "unknown_claims"),
                }
            ),
            reviewed_to_unknown,
        ),
    ]
    for field in ("categories", "component_templates", "modern_overlays", "legacy_overlays"):
        cases.append(
            (
                f"summary-{field}",
                frozenset(top_summary | {("summary", field)}),
                summary(field),
            )
        )
    for kind, summary_field in (
        ("identity", "canonical_identities"),
        ("subtype", "subtypes"),
        ("specific_lifecycle", "lifecycle_records"),
        ("industry_average", "industry_averages"),
        ("hazard", "hazard_records"),
        ("component_association", None),
    ):
        fields = top_claims | top_summary | all_claim_fields | {
            ("summary", "reviewed_claims")
        }
        if summary_field is not None:
            fields.add(("summary", summary_field))
        cases.append(
            (
                f"add-{kind}",
                frozenset(fields),
                lambda report, claim_kind=kind, counter=summary_field: add_claim(
                    report, claim_kind, counter
                ),
            )
        )
    return tuple(cases)


def test_every_mutable_coverage_field_has_an_exact_valid_mutation_and_changes_bytes(
    valid_documents: EvidenceDocuments,
) -> None:
    baseline = build_coverage(valid_documents, "1" * 64)
    baseline_bytes = coverage_json_bytes(baseline)
    observed_targets: set[tuple[str, str]] = set()

    for name, expected_targets, mutation in _valid_coverage_mutations():
        changed = deepcopy(baseline)
        mutation(changed)
        validate_coverage_report(changed)
        assert _changed_coverage_fields(baseline, changed) == expected_targets, name
        assert coverage_json_bytes(changed) != baseline_bytes, name
        observed_targets.update(expected_targets)

    assert observed_targets == (
        {("top", "bundle_version"), ("top", "knowledge_content_sha256")}
        | {("top", "summary"), ("top", "claims")}
        | {("summary", field) for field in SUMMARY_FIELDS}
        | {("claim", field) for field in CLAIM_FIELDS}
    )


def test_schema_is_draft_2020_12_recursively_closed_and_pins_state_coupling() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "packaging/evidence-coverage.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    summary = schema["properties"]["summary"]
    claims = schema["properties"]["claims"]
    claim = claims["items"]

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert list(schema["required"]) == [
        "schema_version",
        "bundle_version",
        "knowledge_content_sha256",
        "summary",
        "claims",
    ]
    assert set(schema["properties"]) == set(schema["required"])
    assert schema["properties"]["schema_version"] == {"const": 1}
    assert summary["additionalProperties"] is False
    assert list(summary["required"]) == list(SUMMARY_FIELDS)
    assert set(summary["properties"]) == set(SUMMARY_FIELDS)
    assert all(
        value == {"type": "integer", "minimum": 0}
        for value in summary["properties"].values()
    )
    assert claim["additionalProperties"] is False
    assert list(claim["required"]) == list(CLAIM_FIELDS)
    assert set(claim["properties"]) == set(CLAIM_FIELDS)
    assert claim["properties"]["category_id"]["enum"] == list(
        RELEASED_CATEGORY_IDS
    )
    assert claim["properties"]["claim_kind"]["enum"] == list(CLAIM_KINDS)
    assert len(claim["oneOf"]) == 2


def test_canonical_bytes_have_one_lf_and_a_stable_fixture_digest(
    valid_documents: EvidenceDocuments,
) -> None:
    report = expected_coverage_report(valid_documents, "0" * 64)
    expected = expected_coverage_bytes(report)

    assert expected.endswith(b"\n")
    assert not expected.endswith(b"\n\n")
    assert coverage_json_bytes(report) == expected
    assert hashlib.sha256(expected).hexdigest() == (
        "35ea0681b991cd15419471fb7fa50d00f30972e4b1786a87976ac093426375b5"
    )


def _demote_reviewed_claim(
    report: dict[str, object], category_id: str, claim_kind: str
) -> None:
    claim = next(
        item
        for item in report["claims"]
        if item["category_id"] == category_id
        and item["claim_kind"] == claim_kind
        and item["source_state"] == "reviewed"
    )
    claim.update(
        evidence_level=None,
        source_state="unknown",
        source_ids=[],
        unknown_reason="Floor evidence intentionally absent.",
    )
    report["summary"]["reviewed_claims"] -= 1
    report["summary"]["unknown_claims"] += 1
    summary_field = {
        "identity": "canonical_identities",
        "subtype": "subtypes",
        "specific_lifecycle": "lifecycle_records",
        "industry_average": "industry_averages",
    }[claim_kind]
    report["summary"][summary_field] -= 1


@pytest.mark.parametrize("category_id", RELEASED_CATEGORY_IDS)
@pytest.mark.parametrize(
    ("claim_kind", "message"),
    [
        ("identity", "requires at least ten reviewed identities"),
        ("subtype", "requires at least four reviewed subtypes"),
        (
            "specific_lifecycle",
            "requires at least three reviewed specific lifecycle records",
        ),
        ("industry_average", "requires one industry average"),
    ],
)
def test_release_floor_rejects_each_category_claim_floor_in_isolation(
    valid_documents: EvidenceDocuments, category_id: str, claim_kind: str, message: str
) -> None:
    report = build_coverage(valid_documents, "a" * 64)
    _demote_reviewed_claim(report, category_id, claim_kind)
    validate_coverage_report(report)
    before = deepcopy(report)

    with pytest.raises(CoverageError, match=rf"{category_id} {message}"):
        coverage_module.validate_release_floor(report)

    assert report == before


@pytest.mark.parametrize(
    ("summary_field", "under_floor", "message"),
    [
        ("categories", 4, "requires exactly five categories"),
        ("component_templates", 14, "requires at least 15 component templates"),
        ("modern_overlays", 4, "requires at least five modern overlays"),
        ("legacy_overlays", 4, "requires at least five legacy overlays"),
    ],
)
def test_release_floor_rejects_each_global_floor_in_isolation(
    valid_documents: EvidenceDocuments,
    summary_field: str,
    under_floor: int,
    message: str,
) -> None:
    report = build_coverage(valid_documents, "b" * 64)
    report["summary"][summary_field] = under_floor
    validate_coverage_report(report)
    before = deepcopy(report)

    with pytest.raises(CoverageError, match=message):
        coverage_module.validate_release_floor(report)

    assert report == before


def _replace_category(
    documents: EvidenceDocuments, category_id: str, **changes: object
) -> EvidenceDocuments:
    return replace(
        documents,
        categories=tuple(
            replace(category, **changes)
            if category.category.category_id == category_id
            else category
            for category in documents.categories
        ),
    )


def _document_floor_mutation(
    documents: EvidenceDocuments, category_id: str, floor: str
) -> EvidenceDocuments:
    category = next(
        item
        for item in documents.categories
        if item.category.category_id == category_id
    )
    if floor == "manufacturers":
        manufacturer_id = category.identities[0].manufacturer_id
        return _replace_category(
            documents,
            category_id,
            identities=tuple(
                item
                for item in category.identities
                if item.manufacturer_id == manufacturer_id
            ),
        )
    if floor == "subtypes":
        return _replace_category(
            documents, category_id, subtypes=category.subtypes[:-1]
        )
    if floor == "current":
        return _replace_category(
            documents,
            category_id,
            subtypes=tuple(
                replace(item, market_state=MarketState.DISCONTINUED)
                for item in category.subtypes
            ),
        )
    if floor == "old":
        return _replace_category(
            documents,
            category_id,
            subtypes=tuple(
                replace(item, market_state=MarketState.CURRENT)
                for item in category.subtypes
            ),
        )
    template_kind = {
        "standard": TemplateKind.STANDARD,
        "modern": TemplateKind.MODERN_OVERLAY,
        "legacy": TemplateKind.LEGACY_OVERLAY,
    }.get(floor)
    if template_kind is not None:
        return _replace_category(
            documents,
            category_id,
            component_templates=tuple(
                item
                for item in category.component_templates
                if item.template_kind is not template_kind
            ),
        )
    if floor == "battery_bearing":
        return _replace_category(
            documents,
            category_id,
            variants=tuple(
                item
                for item in category.variants
                if item.battery_architecture is BatteryArchitecture.BATTERY_FREE
            ),
        )
    if floor == "battery_free":
        return _replace_category(
            documents,
            category_id,
            variants=tuple(
                item
                for item in category.variants
                if item.battery_architecture is BatteryArchitecture.BATTERY_BEARING
            ),
        )
    raise AssertionError(f"unknown test floor {floor}")


@pytest.mark.parametrize("category_id", RELEASED_CATEGORY_IDS)
@pytest.mark.parametrize(
    ("floor", "message"),
    [
        ("manufacturers", "requires at least two manufacturers"),
        ("subtypes", "requires at least four subtypes"),
        ("current", "requires one current subtype"),
        ("old", "requires one discontinued-or-legacy subtype"),
        ("standard", "requires exactly one standard category template"),
        ("modern", "requires one modern overlay"),
        ("legacy", "requires one legacy overlay"),
    ],
)
def test_release_floor_inputs_reject_each_category_requirement_in_isolation(
    valid_documents: EvidenceDocuments, category_id: str, floor: str, message: str
) -> None:
    changed = _document_floor_mutation(valid_documents, category_id, floor)
    before = deepcopy(changed)

    with pytest.raises(CoverageError, match=rf"{category_id} {message}"):
        coverage_module.validate_release_floor_inputs(changed)

    assert changed == before


@pytest.mark.parametrize(
    "category_id",
    ("0301_computer_mouse", "0301_keyboard", "0401_headphones"),
)
@pytest.mark.parametrize("missing", ("battery_bearing", "battery_free"))
def test_release_floor_inputs_require_both_battery_variant_architectures(
    valid_documents: EvidenceDocuments, category_id: str, missing: str
) -> None:
    changed = _document_floor_mutation(valid_documents, category_id, missing)
    before = deepcopy(changed)

    with pytest.raises(
        CoverageError,
        match=rf"{category_id} requires battery-bearing and battery-free variants",
    ):
        coverage_module.validate_release_floor_inputs(changed)

    assert changed == before


def test_floor_validation_cannot_mutate_task3_full_report_bytes(
    valid_documents: EvidenceDocuments,
) -> None:
    report = build_coverage(valid_documents, "a" * 64)
    before_documents = deepcopy(valid_documents)
    before_object = deepcopy(report)
    before_bytes = coverage_json_bytes(report)

    coverage_module.validate_release_floor_inputs(valid_documents)
    coverage_module.validate_release_floor(report)

    assert valid_documents == before_documents
    assert report == before_object
    assert coverage_json_bytes(report) == before_bytes


def test_task3_full_report_schema_and_golden_semantics_are_unchanged(
    valid_documents: EvidenceDocuments,
) -> None:
    expected = expected_coverage_report(valid_documents, "a" * 64)
    report = build_coverage(valid_documents, "a" * 64)
    assert report == expected
    assert coverage_json_bytes(report) == expected_coverage_bytes(expected)


def _claim_key(claim: Mapping[str, object]) -> dict[str, object]:
    return {
        "category_id": claim["category_id"],
        "claim_kind": claim["claim_kind"],
        "claim_id": claim["claim_id"],
    }


def _known_limitations(report: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {"claim_key": _claim_key(claim), "reason": claim["unknown_reason"]}
        for claim in report["claims"]
        if claim["source_state"] == "unknown"
    ]


def test_initial_change_lists_every_current_claim_as_added(
    valid_documents: EvidenceDocuments,
) -> None:
    current = build_coverage(valid_documents, "c" * 64)
    before = deepcopy(current)

    change = coverage_module.compare_coverage(None, current)

    assert change == {
        "schema_version": 1,
        "from_bundle_version": None,
        "to_bundle_version": "3.0.0",
        "added": [_claim_key(claim) for claim in current["claims"]],
        "removed": [],
        "changed": [],
        "known_limitations": _known_limitations(current),
    }
    assert current == before


def _add_reviewed_association(report: dict[str, object]) -> None:
    report["claims"].append(
        {
            "category_id": "0301_computer_mouse",
            "claim_kind": "component_association",
            "claim_id": "added_association",
            "evidence_level": "C",
            "source_state": "reviewed",
            "source_ids": ["added_source"],
            "unknown_reason": None,
        }
    )
    report["claims"].sort(
        key=lambda item: (
            item["category_id"], item["claim_kind"], item["claim_id"]
        )
    )
    report["summary"]["reviewed_claims"] += 1


def test_comparison_classifies_added_removed_changed_and_current_limitations(
    valid_documents: EvidenceDocuments,
) -> None:
    previous = build_coverage(valid_documents, "1" * 64)
    _add_reviewed_association(previous)
    current = build_coverage(valid_documents, "2" * 64)
    evidence_changed = next(
        claim
        for claim in current["claims"]
        if claim["claim_id"] == "0301_computer_mouse_association_legacy_0"
    )
    evidence_changed["evidence_level"] = "C"
    became_reviewed = next(
        claim
        for claim in current["claims"]
        if claim["claim_id"]
        == "0301_computer_mouse_association_modern_1_unknown"
    )
    became_reviewed.update(
        evidence_level="D",
        source_state="reviewed",
        source_ids=["0301_computer_mouse_claim_source"],
        unknown_reason=None,
    )
    current["summary"]["reviewed_claims"] += 1
    current["summary"]["unknown_claims"] -= 1
    validate_coverage_report(previous)
    validate_coverage_report(current)
    before_previous = deepcopy(previous)
    before_current = deepcopy(current)

    change = coverage_module.compare_coverage(previous, current)

    assert change["from_bundle_version"] == "3.0.0"
    assert change["to_bundle_version"] == "3.0.0"
    assert change["added"] == []
    assert change["removed"] == [
        {
            "category_id": "0301_computer_mouse",
            "claim_kind": "component_association",
            "claim_id": "added_association",
        }
    ]
    assert change["changed"] == [
        {
            "claim_key": {
                "category_id": "0301_computer_mouse",
                "claim_kind": "component_association",
                "claim_id": "0301_computer_mouse_association_legacy_0",
            },
            "before_source_state": "reviewed",
            "after_source_state": "reviewed",
            "before_evidence_level": "B",
            "after_evidence_level": "C",
        },
        {
            "claim_key": {
                "category_id": "0301_computer_mouse",
                "claim_kind": "component_association",
                "claim_id": "0301_computer_mouse_association_modern_1_unknown",
            },
            "before_source_state": "unknown",
            "after_source_state": "reviewed",
            "before_evidence_level": None,
            "after_evidence_level": "D",
        },
    ]
    assert change["known_limitations"] == _known_limitations(current)
    assert previous == before_previous
    assert current == before_current


def test_comparison_rejects_same_content_hash_with_different_canonical_report(
    valid_documents: EvidenceDocuments,
) -> None:
    previous = build_coverage(valid_documents, "3" * 64)
    current = deepcopy(previous)
    current["bundle_version"] = "3.0.1"

    with pytest.raises(CoverageError, match="same knowledge content hash"):
        coverage_module.compare_coverage(previous, current)


def test_change_schema_is_draft_2020_12_and_closes_every_artifact_object() -> None:
    schema_path = ROOT / "packaging/evidence-coverage-change.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    properties = schema["properties"]
    claim_key_locations = (
        properties["added"]["items"],
        properties["removed"]["items"],
        properties["changed"]["items"]["properties"]["claim_key"],
        properties["known_limitations"]["items"]["properties"]["claim_key"],
    )

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert list(schema["required"]) == [
        "schema_version",
        "from_bundle_version",
        "to_bundle_version",
        "added",
        "removed",
        "changed",
        "known_limitations",
    ]
    assert set(properties) == set(schema["required"])
    assert properties["schema_version"] == {"const": 1}
    assert properties["changed"]["items"]["additionalProperties"] is False
    assert properties["known_limitations"]["items"]["additionalProperties"] is False
    for claim_key in claim_key_locations:
        assert claim_key["additionalProperties"] is False
        assert claim_key["properties"]["category_id"]["enum"] == list(
            RELEASED_CATEGORY_IDS
        )
        assert claim_key["properties"]["claim_kind"]["enum"] == list(CLAIM_KINDS)


def _run_change_cli(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    launcher = (
        "import runpy,sys,types;"
        "sys.modules['readline']=types.ModuleType('readline');"
        "script=sys.argv.pop(1);sys.argv[0]=script;"
        "runpy.run_path(script,run_name='__main__')"
    )
    return subprocess.run(
        [
            str(PYTHON),
            "-c",
            launcher,
            str(ROOT / "scripts/compare_evidence_coverage.py"),
            *arguments,
        ],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_change_cli_writes_canonical_initial_artifact_to_exact_target(
    valid_documents: EvidenceDocuments, tmp_path: Path
) -> None:
    current = build_coverage(valid_documents, "4" * 64)
    current_path = tmp_path / "current.json"
    output = tmp_path / "nested-name.change.json"
    current_path.write_bytes(coverage_json_bytes(current))
    expected = {
        "schema_version": 1,
        "from_bundle_version": None,
        "to_bundle_version": "3.0.0",
        "added": [_claim_key(claim) for claim in current["claims"]],
        "removed": [],
        "changed": [],
        "known_limitations": _known_limitations(current),
    }
    expected_bytes = json.dumps(
        expected,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"

    result = _run_change_cli(
        "--current", str(current_path), "--initial", "--out", str(output), cwd=tmp_path
    )

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert output.read_bytes() == expected_bytes
    assert current_path.read_bytes() == coverage_json_bytes(current)
    assert sorted(
        path.name for path in tmp_path.iterdir() if path.name != "source"
    ) == [
        "current.json",
        "nested-name.change.json",
    ]


def test_change_cli_requires_exactly_one_comparison_mode(tmp_path: Path) -> None:
    neither = _run_change_cli(
        "--current", "current.json", "--out", "change.json", cwd=tmp_path
    )
    both = _run_change_cli(
        "--current",
        "current.json",
        "--previous",
        "previous.json",
        "--initial",
        "--out",
        "change.json",
        cwd=tmp_path,
    )

    assert neither.returncode == 2
    assert neither.stdout == ""
    assert "one of the arguments --previous --initial is required" in neither.stderr
    assert both.returncode == 2
    assert both.stdout == ""
    assert "argument --initial: not allowed with argument --previous" in both.stderr


def test_change_cli_rejects_noncanonical_input_before_preserving_output(
    valid_documents: EvidenceDocuments, tmp_path: Path
) -> None:
    current = build_coverage(valid_documents, "5" * 64)
    current_path = tmp_path / "current.json"
    output = tmp_path / "change.json"
    noncanonical = json.dumps(current, indent=2).encode("utf-8") + b"\n"
    old_output = b"previous accepted output\n"
    current_path.write_bytes(noncanonical)
    output.write_bytes(old_output)

    result = _run_change_cli(
        "--current", str(current_path), "--initial", "--out", str(output), cwd=tmp_path
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"error: coverage report is not canonical: {current_path}\n"
    assert current_path.read_bytes() == noncanonical
    assert output.read_bytes() == old_output


def test_change_cli_output_replace_failure_preserves_output_and_inputs(
    valid_documents: EvidenceDocuments,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    change_module = importlib.import_module("scripts.compare_evidence_coverage")
    previous = build_coverage(valid_documents, "6" * 64)
    current = build_coverage(valid_documents, "7" * 64)
    previous_path = tmp_path / "previous.json"
    current_path = tmp_path / "current.json"
    output = tmp_path / "change.json"
    previous_bytes = coverage_json_bytes(previous)
    current_bytes = coverage_json_bytes(current)
    old_output = b"previous accepted output\n"
    previous_path.write_bytes(previous_bytes)
    current_path.write_bytes(current_bytes)
    output.write_bytes(old_output)

    def fail_replace(source: object, target: object) -> None:
        del source, target
        raise OSError("intentional replace failure")

    monkeypatch.setattr(change_module.os, "replace", fail_replace)
    result = change_module.main(
        [
            "--current",
            str(current_path),
            "--previous",
            str(previous_path),
            "--out",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "error: cannot write coverage change: intentional replace failure\n"
    assert previous_path.read_bytes() == previous_bytes
    assert current_path.read_bytes() == current_bytes
    assert output.read_bytes() == old_output
    assert sorted(
        path.name for path in tmp_path.iterdir() if path.name != "source"
    ) == [
        "change.json",
        "current.json",
        "previous.json",
    ]


@pytest.mark.parametrize("aliased_input", ("current", "previous"))
def test_change_cli_rejects_output_alias_of_either_input(
    valid_documents: EvidenceDocuments,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    aliased_input: str,
) -> None:
    change_module = importlib.import_module("scripts.compare_evidence_coverage")
    previous_path = tmp_path / "previous.json"
    current_path = tmp_path / "current.json"
    previous_bytes = coverage_json_bytes(
        build_coverage(valid_documents, "9" * 64)
    )
    current_bytes = coverage_json_bytes(
        build_coverage(valid_documents, "a" * 64)
    )
    previous_path.write_bytes(previous_bytes)
    current_path.write_bytes(current_bytes)
    output = current_path if aliased_input == "current" else previous_path

    result = change_module.main(
        [
            "--current",
            str(current_path),
            "--previous",
            str(previous_path),
            "--out",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "error: output must not alias an input report\n"
    assert previous_path.read_bytes() == previous_bytes
    assert current_path.read_bytes() == current_bytes


def test_change_cli_parent_fsync_failure_keeps_complete_committed_output(
    valid_documents: EvidenceDocuments,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    change_module = importlib.import_module("scripts.compare_evidence_coverage")
    current = build_coverage(valid_documents, "b" * 64)
    current_path = tmp_path / "current.json"
    output = tmp_path / "change.json"
    current_bytes = coverage_json_bytes(current)
    current_path.write_bytes(current_bytes)
    output.write_bytes(b"previous accepted output\n")
    expected = {
        "schema_version": 1,
        "from_bundle_version": None,
        "to_bundle_version": "3.0.0",
        "added": [_claim_key(claim) for claim in current["claims"]],
        "removed": [],
        "changed": [],
        "known_limitations": _known_limitations(current),
    }
    expected_bytes = json.dumps(
        expected,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    real_fsync = os.fsync

    def fail_parent_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("intentional parent fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(change_module.os, "fsync", fail_parent_fsync)
    result = change_module.main(
        ["--current", str(current_path), "--initial", "--out", str(output)]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == (
        "error: cannot write coverage change: intentional parent fsync failure\n"
    )
    assert current_path.read_bytes() == current_bytes
    assert output.read_bytes() == expected_bytes
    assert sorted(
        path.name for path in tmp_path.iterdir() if path.name != "source"
    ) == [
        "change.json",
        "current.json",
    ]


def test_change_cli_fsyncs_regular_output_and_parent_directory(
    valid_documents: EvidenceDocuments,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    change_module = importlib.import_module("scripts.compare_evidence_coverage")
    current_path = tmp_path / "current.json"
    output = tmp_path / "change.json"
    current_path.write_bytes(
        coverage_json_bytes(build_coverage(valid_documents, "8" * 64))
    )
    real_fsync = os.fsync
    synced_modes: list[int] = []

    def observe_fsync(descriptor: int) -> None:
        synced_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(change_module.os, "fsync", observe_fsync)
    result = change_module.main(
        ["--current", str(current_path), "--initial", "--out", str(output)]
    )

    captured = capsys.readouterr()
    assert (result, captured.out, captured.err) == (0, "", "")
    assert sum(stat.S_ISREG(mode) for mode in synced_modes) == 1
    assert sum(stat.S_ISDIR(mode) for mode in synced_modes) == 1
