from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.knowledge_schema import PolicyRecord, load_shared_evidence_documents
from server.evidence_types import RecommendationValue, RELEASED_CATEGORY_IDS


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "reference"

EXPECTED_POLICY_IDS = {
    "urgent_hazard_specialist",
    "unknown_identity_more_information",
    "missing_required_observation",
    "nonworking_repair",
    "recoverable_parts",
    "supported_reuse",
    "end_of_reference_recycle",
}

REVIEWER = "OpenAI Codex automated source review"
USE_BASIS = (
    "Factual paraphrase and citation/link to a publicly accessible official page; "
    "no source-document redistribution."
)

COMPLETE_WORKING_WITHIN = frozenset(
    {
        "identity.state=canonical",
        "observations.age_months=present",
        "observations.full_charge_cycles=missing",
        "observations.operational_state=working",
        "observations.issue_flags.overheating=false",
        "observations.issue_flags.odor=false",
        "observations.issue_flags.swelling_or_battery_damage=false",
        "observations.issue_flags.recall=false",
        "visible_condition.grade=good",
        "visible_condition.image_sufficiency=insufficient",
        "lifecycle.resolution=resolved",
        "lifecycle.required_usage=present",
        "lifecycle.position=within_reference",
        "component_decisions.any_present=false",
        "hazards.triggered_severity=none",
    }
)


def _replace_family(
    predicates: frozenset[str], family: str, replacement: str
) -> frozenset[str]:
    return frozenset(
        {predicate for predicate in predicates if not predicate.startswith(f"{family}=")}
        | {replacement}
    )


def _winner(rules: tuple[PolicyRecord, ...], true_predicates: frozenset[str]):
    matching = [
        rule
        for rule in rules
        if set(rule.when_all) <= true_predicates
        and (not rule.when_any or not set(rule.when_any).isdisjoint(true_predicates))
    ]
    assert matching, "the policy must fail closed through its authored fallback"
    return min(matching, key=lambda rule: rule.priority)


def test_bundle_metadata_is_exact():
    shared = load_shared_evidence_documents(REFERENCE)

    assert shared.bundle.schema_version == 3
    assert shared.bundle.bundle_version == "3.0.0"
    assert shared.bundle.identity_catalog_version == "1.0.0"
    assert shared.bundle.policy_revision == "2.0.0"
    assert tuple(shared.bundle.category_ids) == RELEASED_CATEGORY_IDS


def test_shared_sources_use_reopened_official_pages_and_honest_review_metadata():
    shared = load_shared_evidence_documents(REFERENCE)
    actual = {
        source.source_id: (
            source.title,
            source.publisher,
            source.canonical_url,
            source.publication_or_revision_date,
        )
        for source in shared.sources
    }

    assert actual == {
        "apple_mac_battery_cycles_2026": (
            "Determine battery cycle count for Mac laptops",
            "Apple Support",
            "https://support.apple.com/en-au/102888",
            date(2026, 3, 24),
        ),
        "epa_electronics_management_2026": (
            "Electronics Basic Information, Research, and Initiatives",
            "United States Environmental Protection Agency",
            "https://www.epa.gov/electronics-batteries-management/electronics-basic-information-research-and-initiatives",
            date(2026, 3, 10),
        ),
        "epa_used_li_ion_2026": (
            "Used Lithium-Ion Batteries",
            "United States Environmental Protection Agency",
            "https://www.epa.gov/recycle/used-lithium-ion-batteries",
            date(2026, 3, 20),
        ),
        "eu_phone_ecodesign_2023_1670": (
            "Consolidated text: Commission Regulation (EU) 2023/1670 of 16 June 2023 laying down ecodesign requirements for smartphones, mobile phones other than smartphones, cordless phones and slate tablets pursuant to Directive 2009/125/EC of the European Parliament and of the Council and amending Commission Regulation (EU) 2023/826 (Text with EEA relevance)",
            "EUR-Lex",
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02023R1670-20250620",
            date(2025, 6, 20),
        ),
        "eu_rohs_current": (
            "Consolidated text: Directive 2011/65/EU of the European Parliament and of the Council of 8 June 2011 on the restriction of the use of certain hazardous substances in electrical and electronic equipment (recast) (Text with EEA relevance)",
            "EUR-Lex",
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02011L0065-20260701",
            date(2026, 7, 1),
        ),
    }
    assert {source.accessed_on for source in shared.sources} == {date(2026, 9, 10)}
    assert {source.reviewed_on for source in shared.sources} == {date(2026, 9, 10)}
    assert {source.reviewed_by for source in shared.sources} == {REVIEWER}
    assert {source.license_or_use_basis for source in shared.sources} == {USE_BASIS}


def test_policy_values_and_safety_priority_are_closed():
    shared = load_shared_evidence_documents(REFERENCE)
    rules = {rule.rule_id: rule for rule in shared.policies}

    assert set(rules) == EXPECTED_POLICY_IDS
    assert len({rule.priority for rule in shared.policies}) == len(shared.policies)
    assert tuple(rule.priority for rule in shared.policies) == tuple(
        sorted(rule.priority for rule in shared.policies)
    )
    assert rules["urgent_hazard_specialist"].priority < rules["supported_reuse"].priority
    assert (
        rules["urgent_hazard_specialist"].outcome
        is RecommendationValue.SPECIALIST_HANDLING
    )
    assert (
        rules["unknown_identity_more_information"].outcome
        is RecommendationValue.MORE_INFORMATION_NEEDED
    )
    assert rules["nonworking_repair"].outcome is RecommendationValue.REPAIR
    assert rules["supported_reuse"].outcome is RecommendationValue.REUSE
    assert (
        rules["recoverable_parts"].outcome
        is RecommendationValue.MORE_INFORMATION_NEEDED
    )
    assert (
        rules["end_of_reference_recycle"].outcome
        is RecommendationValue.MORE_INFORMATION_NEEDED
    )


@pytest.mark.parametrize(
    ("expected_rule_id", "expected_outcome", "predicates"),
    [
        (
            "urgent_hazard_specialist",
            RecommendationValue.SPECIALIST_HANDLING,
            _replace_family(
                COMPLETE_WORKING_WITHIN,
                "hazards.triggered_severity",
                "hazards.triggered_severity=urgent",
            ),
        ),
        (
            "unknown_identity_more_information",
            RecommendationValue.MORE_INFORMATION_NEEDED,
            frozenset(
                {
                    "identity.state=unknown",
                    "observations.operational_state=working",
                    "observations.issue_flags.overheating=true",
                    "visible_condition.grade=good",
                }
            ),
        ),
        (
            "missing_required_observation",
            RecommendationValue.MORE_INFORMATION_NEEDED,
            _replace_family(
                _replace_family(
                    COMPLETE_WORKING_WITHIN,
                    "lifecycle.required_usage",
                    "lifecycle.required_usage=missing",
                ),
                "observations.operational_state",
                "observations.operational_state=not_working",
            ),
        ),
        (
            "nonworking_repair",
            RecommendationValue.REPAIR,
            _replace_family(
                COMPLETE_WORKING_WITHIN,
                "observations.operational_state",
                "observations.operational_state=not_working",
            ),
        ),
        (
            "recoverable_parts",
            RecommendationValue.MORE_INFORMATION_NEEDED,
            _replace_family(
                _replace_family(
                    COMPLETE_WORKING_WITHIN,
                    "visible_condition.grade",
                    "visible_condition.grade=poor",
                ),
                "component_decisions.any_present",
                "component_decisions.any_present=true",
            ),
        ),
        (
            "supported_reuse",
            RecommendationValue.REUSE,
            COMPLETE_WORKING_WITHIN,
        ),
        (
            "end_of_reference_recycle",
            RecommendationValue.MORE_INFORMATION_NEEDED,
            _replace_family(
                COMPLETE_WORKING_WITHIN,
                "lifecycle.position",
                "lifecycle.position=at_or_beyond_reference",
            ),
        ),
    ],
)
def test_every_authored_policy_rule_has_a_meaningful_winning_case(
    expected_rule_id, expected_outcome, predicates
):
    shared = load_shared_evidence_documents(REFERENCE)

    winner = _winner(shared.policies, predicates)

    assert winner.rule_id == expected_rule_id
    assert winner.outcome is expected_outcome


@pytest.mark.parametrize(
    ("case", "predicates"),
    [
        (
            "capacity or endurance threshold remains outside device-life policy",
            _replace_family(
                COMPLETE_WORKING_WITHIN,
                "lifecycle.position",
                "lifecycle.position=not_calculable",
            ),
        ),
        (
            "overlapping device-life interval remains indeterminate",
            _replace_family(
                COMPLETE_WORKING_WITHIN,
                "lifecycle.position",
                "lifecycle.position=not_calculable",
            ),
        ),
        (
            "positive flag without a resolved applicable hazard is not safety clearance",
            _replace_family(
                COMPLETE_WORKING_WITHIN,
                "observations.issue_flags.overheating",
                "observations.issue_flags.overheating=true",
            ),
        ),
        (
            "no present component decision does not prove component absence",
            _replace_family(
                COMPLETE_WORKING_WITHIN,
                "visible_condition.grade",
                "visible_condition.grade=poor",
            ),
        ),
        (
            "unknown operation cannot receive optimistic reuse",
            _replace_family(
                COMPLETE_WORKING_WITHIN,
                "observations.operational_state",
                "observations.operational_state=unknown",
            ),
        ),
    ],
)
def test_incomplete_or_insufficient_evidence_fails_closed(case, predicates):
    del case
    shared = load_shared_evidence_documents(REFERENCE)

    winner = _winner(shared.policies, predicates)

    assert winner.rule_id == "missing_required_observation"
    assert winner.outcome is RecommendationValue.MORE_INFORMATION_NEEDED


def test_manual_known_grade_is_not_invalidated_by_image_sufficiency():
    shared = load_shared_evidence_documents(REFERENCE)

    insufficient = _winner(shared.policies, COMPLETE_WORKING_WITHIN)
    unknown_image_state = _winner(
        shared.policies,
        _replace_family(
            COMPLETE_WORKING_WITHIN,
            "visible_condition.image_sufficiency",
            "visible_condition.image_sufficiency=unknown",
        ),
    )

    assert insufficient.rule_id == "supported_reuse"
    assert unknown_image_state.rule_id == "supported_reuse"


def test_policy_uses_selected_lifecycle_usage_not_both_raw_usage_fields():
    shared = load_shared_evidence_documents(REFERENCE)
    positive_rule_ids = {
        "nonworking_repair",
        "recoverable_parts",
        "supported_reuse",
        "end_of_reference_recycle",
    }

    for rule in shared.policies:
        if rule.rule_id in positive_rule_ids:
            assert "lifecycle.required_usage=present" in rule.when_all
            assert not {
                "observations.age_months=present",
                "observations.full_charge_cycles=present",
            } <= set(rule.when_all)


def test_gap_rules_request_assessment_instead_of_declaring_disposition():
    shared = load_shared_evidence_documents(REFERENCE)
    rules = {rule.rule_id: rule for rule in shared.policies}

    parts = rules["recoverable_parts"]
    end_reference = rules["end_of_reference_recycle"]

    assert parts.outcome is RecommendationValue.MORE_INFORMATION_NEEDED
    assert "does not establish" in parts.rationale.casefold()
    assert "assessment" in parts.rationale.casefold()
    assert end_reference.outcome is RecommendationValue.MORE_INFORMATION_NEEDED
    assert "does not establish" in end_reference.rationale.casefold()
    assert "assessment" in end_reference.rationale.casefold()
