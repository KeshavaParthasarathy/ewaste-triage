from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from server.evidence_types import (
    BundleStamp,
    CanonicalIdentityScope,
    EvidenceLevel,
    KnowledgeManifest,
    RELEASED_CATEGORY_IDS,
    RecommendationValue,
    ResolutionTier,
)


def test_bundle_stamp_is_exact_and_immutable():
    stamp = BundleStamp(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64)
    assert stamp == BundleStamp(
        schema_version=3,
        bundle_version="3.0.0",
        identity_catalog_version="1.0.0",
        policy_revision="2.0.0",
        content_sha256="a" * 64,
    )
    with pytest.raises(FrozenInstanceError):
        stamp.bundle_version = "3.0.1"


def test_manifest_projects_the_only_assessment_bundle_stamp():
    manifest = KnowledgeManifest(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64, "b" * 64)
    assert manifest.stamp == BundleStamp(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64)


def test_scope_and_closed_values_match_the_approved_contract():
    scope = CanonicalIdentityScope(
        category_id="0306_mobile_phone",
        subtype_id="phone_slate_smartphone",
        family_id="apple_iphone_15_family",
        model_id="apple_iphone_15",
        variant_ids=("battery_integrated",),
        model_year=2023,
        applicable_on=date(2026, 9, 7),
    )
    assert scope.model_id == "apple_iphone_15"
    assert {item.value for item in EvidenceLevel} == {"A", "B", "C", "D"}
    assert [item.value for item in ResolutionTier] == [
        "exact_model", "family", "subtype", "industry_average"
    ]
    assert {item.value for item in RecommendationValue} == {
        "reuse", "repair", "parts_recovery", "specialist_handling",
        "certified_recycling", "more_information_needed",
    }


def test_released_category_ids_are_ordered_and_closed():
    assert RELEASED_CATEGORY_IDS == (
        "0301_computer_mouse",
        "0301_keyboard",
        "0303_laptop",
        "0306_mobile_phone",
        "0401_headphones",
    )
