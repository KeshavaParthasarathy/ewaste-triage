from dataclasses import MISSING, FrozenInstanceError, fields, is_dataclass
from datetime import date

import pytest

import server.evidence_types as evidence


EXPECTED_ENUMS = {
    evidence.EvidenceLevel: (("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")),
    evidence.ResolutionTier: (
        ("EXACT_MODEL", "exact_model"),
        ("FAMILY", "family"),
        ("SUBTYPE", "subtype"),
        ("INDUSTRY_AVERAGE", "industry_average"),
    ),
    evidence.ScopeKind: (
        ("CATEGORY", "category"),
        ("SUBTYPE", "subtype"),
        ("FAMILY", "family"),
        ("MODEL", "model"),
    ),
    evidence.IdentityKind: (("FAMILY", "family"), ("MODEL", "model")),
    evidence.MarketState: (
        ("CURRENT", "current"),
        ("DISCONTINUED", "discontinued"),
        ("LEGACY", "legacy"),
    ),
    evidence.BatteryArchitecture: (
        ("BATTERY_FREE", "battery_free"),
        ("BATTERY_BEARING", "battery_bearing"),
    ),
    evidence.LifecycleEndpointKind: (
        ("TOTAL_LIFE", "total_life"),
        ("CAPACITY_THRESHOLD", "capacity_threshold"),
        ("OPERATING_ENDURANCE", "operating_endurance"),
    ),
    evidence.AssociationStatus: (
        ("COMMONLY_ASSOCIATED", "commonly_associated"),
        ("CONDITIONAL", "conditional"),
        ("LEGACY_SPECIFIC", "legacy_specific"),
        ("EXACT_MODEL_CONFIRMED", "exact_model_confirmed"),
        ("USER_CONFIRMED", "user_confirmed"),
        ("NOT_PRESENT", "not_present"),
        ("UNKNOWN", "unknown"),
    ),
    evidence.HazardSeverity: (
        ("ADVISORY", "advisory"),
        ("CAUTION", "caution"),
        ("URGENT", "urgent"),
    ),
    evidence.SourceState: (("REVIEWED", "reviewed"), ("UNKNOWN", "unknown")),
    evidence.RecommendationValue: (
        ("REUSE", "reuse"),
        ("REPAIR", "repair"),
        ("PARTS_RECOVERY", "parts_recovery"),
        ("SPECIALIST_HANDLING", "specialist_handling"),
        ("CERTIFIED_RECYCLING", "certified_recycling"),
        ("MORE_INFORMATION_NEEDED", "more_information_needed"),
    ),
}

EXPECTED_RECORDS = {
    evidence.CanonicalIdentityScope: (
        ("category_id", str, MISSING),
        ("subtype_id", str | None, None),
        ("family_id", str | None, None),
        ("model_id", str | None, None),
        ("variant_ids", tuple[str, ...], ()),
        ("model_year", int | None, None),
        ("applicable_on", date | None, None),
    ),
    evidence.LifecycleRequest: (
        ("subject", str, MISSING),
        ("endpoint", str, MISSING),
        ("metric", str, MISSING),
        ("unit", str, MISSING),
    ),
    evidence.CategorySnapshot: (("category_id", str, MISSING), ("display_name", str, MISSING)),
    evidence.SourceSnapshot: (
        ("source_id", str, MISSING),
        ("title", str, MISSING),
        ("publisher", str, MISSING),
        ("canonical_url", str, MISSING),
        ("publication_or_revision_date", date, MISSING),
        ("accessed_on", date, MISSING),
        ("license_or_use_basis", str, MISSING),
        ("reviewed_by", str, MISSING),
        ("reviewed_on", date, MISSING),
    ),
    evidence.IdentityRecordSnapshot: (
        ("identity_id", str, MISSING),
        ("identity_kind", evidence.IdentityKind, MISSING),
        ("category_id", str, MISSING),
        ("subtype_id", str, MISSING),
        ("manufacturer_id", str, MISSING),
        ("manufacturer_name", str, MISSING),
        ("family_id", str, MISSING),
        ("family_name", str, MISSING),
        ("model_id", str | None, MISSING),
        ("model_name", str | None, MISSING),
        ("display_name", str, MISSING),
        ("aliases", tuple[str, ...], MISSING),
        ("distinguishing_tokens", tuple[str, ...], MISSING),
        ("model_year_from", int | None, MISSING),
        ("model_year_to", int | None, MISSING),
        ("applicable_from", date | None, MISSING),
        ("applicable_to", date | None, MISSING),
        ("variant_ids", tuple[str, ...], MISSING),
        ("market_state", evidence.MarketState, MISSING),
        ("battery_architecture", evidence.BatteryArchitecture, MISSING),
        ("sources", tuple[evidence.SourceSnapshot, ...], MISSING),
    ),
    evidence.LifecycleRecordSnapshot: (
        ("record_id", str, MISSING),
        ("resolution_tier", evidence.ResolutionTier, MISSING),
        ("scope_kind", evidence.ScopeKind, MISSING),
        ("scope_id", str, MISSING),
        ("subject", str, MISSING),
        ("endpoint", str, MISSING),
        ("endpoint_kind", evidence.LifecycleEndpointKind, MISSING),
        ("metric", str, MISSING),
        ("unit", str, MISSING),
        ("lower_bound", float, MISSING),
        ("upper_bound", float, MISSING),
        ("endpoint_qualification", str, MISSING),
        ("applicable_from", date | None, MISSING),
        ("applicable_to", date | None, MISSING),
        ("model_year_from", int | None, MISSING),
        ("model_year_to", int | None, MISSING),
        ("required_variant_ids", tuple[str, ...], MISSING),
        ("excluded_variant_ids", tuple[str, ...], MISSING),
        ("precedence", int, MISSING),
        ("evidence_level", evidence.EvidenceLevel, MISSING),
        ("assumptions", tuple[str, ...], MISSING),
        ("population_definition", str | None, MISSING),
        ("publication_period", str | None, MISSING),
        ("methodology", str | None, MISSING),
        ("uncertainty", str | None, MISSING),
        ("limitations", tuple[str, ...], MISSING),
        ("sources", tuple[evidence.SourceSnapshot, ...], MISSING),
    ),
    evidence.ResolutionStep: (
        ("tier", evidence.ResolutionTier, MISSING),
        ("considered_record_ids", tuple[str, ...], MISSING),
        ("rejected", tuple[tuple[str, str], ...], MISSING),
        ("selected_record_id", str | None, MISSING),
        ("outcome", str, MISSING),
    ),
    evidence.LifecycleResolution: (
        ("record", evidence.LifecycleRecordSnapshot | None, MISSING),
        ("tier", evidence.ResolutionTier | None, MISSING),
        ("trace", tuple[evidence.ResolutionStep, ...], MISSING),
        ("unknown_reason", str | None, MISSING),
    ),
    evidence.ComponentAssociationSnapshot: (
        ("association_id", str, MISSING),
        ("template_id", str, MISSING),
        ("component_id", str, MISSING),
        ("display_name", str, MISSING),
        ("status", evidence.AssociationStatus, MISSING),
        ("scope_kind", evidence.ScopeKind, MISSING),
        ("scope_id", str, MISSING),
        ("applicability", str, MISSING),
        ("notes", tuple[str, ...], MISSING),
        ("evidence_level", evidence.EvidenceLevel | None, MISSING),
        ("sources", tuple[evidence.SourceSnapshot, ...], MISSING),
    ),
    evidence.ComponentResolution: (
        ("components", tuple[evidence.ComponentAssociationSnapshot, ...], MISSING),
        ("applied_template_ids", tuple[str, ...], MISSING),
    ),
    evidence.HazardSnapshot: (
        ("hazard_id", str, MISSING),
        ("component_id", str, MISSING),
        ("scope_kind", evidence.ScopeKind, MISSING),
        ("scope_id", str, MISSING),
        ("applicability", str, MISSING),
        ("trigger_observation_keys", tuple[str, ...], MISSING),
        ("severity", evidence.HazardSeverity, MISSING),
        ("immediate_actions", tuple[str, ...], MISSING),
        ("follow_up_actions", tuple[str, ...], MISSING),
        ("handling_guidance", tuple[str, ...], MISSING),
        ("disposal_guidance", tuple[str, ...], MISSING),
        ("evidence_level", evidence.EvidenceLevel, MISSING),
        ("sources", tuple[evidence.SourceSnapshot, ...], MISSING),
    ),
    evidence.HazardResolution: (("hazards", tuple[evidence.HazardSnapshot, ...], MISSING),),
    evidence.PolicyRuleSnapshot: (
        ("rule_id", str, MISSING),
        ("priority", int, MISSING),
        ("outcome", evidence.RecommendationValue, MISSING),
        ("when_all", tuple[str, ...], MISSING),
        ("when_any", tuple[str, ...], MISSING),
        ("rationale", str, MISSING),
        ("evidence_level", evidence.EvidenceLevel, MISSING),
        ("sources", tuple[evidence.SourceSnapshot, ...], MISSING),
    ),
    evidence.PolicyBundleSnapshot: (
        ("revision", str, MISSING),
        ("rules", tuple[evidence.PolicyRuleSnapshot, ...], MISSING),
    ),
    evidence.BundleStamp: (
        ("schema_version", int, MISSING),
        ("bundle_version", str, MISSING),
        ("identity_catalog_version", str, MISSING),
        ("policy_revision", str, MISSING),
        ("content_sha256", str, MISSING),
    ),
    evidence.ResolvedEvidence: (
        ("scope", evidence.CanonicalIdentityScope, MISSING),
        ("lifecycle", evidence.LifecycleResolution, MISSING),
        ("components", evidence.ComponentResolution, MISSING),
        ("hazards", evidence.HazardResolution, MISSING),
        ("policy", evidence.PolicyBundleSnapshot, MISSING),
        ("bundle", evidence.BundleStamp, MISSING),
    ),
    evidence.KnowledgeManifest: (
        ("schema_version", int, MISSING),
        ("bundle_version", str, MISSING),
        ("identity_catalog_version", str, MISSING),
        ("policy_revision", str, MISSING),
        ("content_sha256", str, MISSING),
        ("coverage_sha256", str, MISSING),
    ),
}


def test_bundle_stamp_is_exact_and_immutable():
    stamp = evidence.BundleStamp(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64)
    assert stamp == evidence.BundleStamp(
        schema_version=3,
        bundle_version="3.0.0",
        identity_catalog_version="1.0.0",
        policy_revision="2.0.0",
        content_sha256="a" * 64,
    )
    with pytest.raises(FrozenInstanceError):
        stamp.bundle_version = "3.0.1"


def test_manifest_projects_the_only_assessment_bundle_stamp():
    manifest = evidence.KnowledgeManifest(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64, "b" * 64)
    assert manifest.stamp == evidence.BundleStamp(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64)


def test_scope_and_closed_values_match_the_approved_contract():
    scope = evidence.CanonicalIdentityScope(
        category_id="0306_mobile_phone",
        subtype_id="phone_slate_smartphone",
        family_id="apple_iphone_15_family",
        model_id="apple_iphone_15",
        variant_ids=("battery_integrated",),
        model_year=2023,
        applicable_on=date(2026, 9, 7),
    )
    assert scope.model_id == "apple_iphone_15"
    assert {item.value for item in evidence.EvidenceLevel} == {"A", "B", "C", "D"}
    assert [item.value for item in evidence.ResolutionTier] == [
        "exact_model", "family", "subtype", "industry_average"
    ]
    assert {item.value for item in evidence.RecommendationValue} == {
        "reuse", "repair", "parts_recovery", "specialist_handling",
        "certified_recycling", "more_information_needed",
    }


def test_released_category_ids_are_ordered_and_closed():
    assert evidence.RELEASED_CATEGORY_IDS == (
        "0301_computer_mouse",
        "0301_keyboard",
        "0303_laptop",
        "0306_mobile_phone",
        "0401_headphones",
    )


def test_all_closed_enums_have_exact_members_values_and_no_aliases():
    assert len(EXPECTED_ENUMS) == 11
    for enum, expected_members in EXPECTED_ENUMS.items():
        assert tuple(enum.__members__.items()) == tuple(
            (name, enum(value)) for name, value in expected_members
        )
        assert tuple((member.name, member.value) for member in enum) == expected_members
        assert len(enum.__members__) == len(enum)


def test_all_records_have_exact_frozen_field_contracts():
    assert len(EXPECTED_RECORDS) == 17
    for record, expected_fields in EXPECTED_RECORDS.items():
        assert is_dataclass(record)
        assert record.__dataclass_params__.frozen is True
        assert tuple(record.__annotations__.items()) == tuple(
            (name, annotation) for name, annotation, _ in expected_fields
        )
        actual_fields = fields(record)
        assert tuple(field.name for field in actual_fields) == tuple(
            name for name, _, _ in expected_fields
        )
        assert tuple(field.type for field in actual_fields) == tuple(
            annotation for _, annotation, _ in expected_fields
        )
        assert tuple(field.default for field in actual_fields) == tuple(
            default for _, _, default in expected_fields
        )
        assert all(field.default_factory is MISSING for field in actual_fields)


def test_canonical_scope_defaults_are_exact_immutable_tuples():
    scope = evidence.CanonicalIdentityScope("0303_laptop")
    assert scope == evidence.CanonicalIdentityScope(
        category_id="0303_laptop",
        subtype_id=None,
        family_id=None,
        model_id=None,
        variant_ids=(),
        model_year=None,
        applicable_on=None,
    )
    assert isinstance(scope.variant_ids, tuple)


def make_all_records():
    source = evidence.SourceSnapshot(
        "source", "Title", "Publisher", "https://example.invalid/source", date(2026, 1, 1),
        date(2026, 1, 2), "reviewed use", "reviewer", date(2026, 1, 3),
    )
    scope = evidence.CanonicalIdentityScope("0303_laptop")
    lifecycle = evidence.LifecycleRecordSnapshot(
        "life", evidence.ResolutionTier.EXACT_MODEL, evidence.ScopeKind.MODEL, "model",
        "device", "service life", evidence.LifecycleEndpointKind.TOTAL_LIFE, "years",
        "years", 1.0, 2.0, "total life", None, None, None, None, (), (), 1,
        evidence.EvidenceLevel.A, (), None, None, None, None, (), (source,),
    )
    step = evidence.ResolutionStep(
        evidence.ResolutionTier.EXACT_MODEL, (), (), "life", "selected"
    )
    lifecycle_resolution = evidence.LifecycleResolution(
        lifecycle, evidence.ResolutionTier.EXACT_MODEL, (step,), None
    )
    component = evidence.ComponentAssociationSnapshot(
        "association", "template", "battery", "Battery",
        evidence.AssociationStatus.EXACT_MODEL_CONFIRMED, evidence.ScopeKind.MODEL,
        "model", "applies", (), evidence.EvidenceLevel.A, (source,),
    )
    components = evidence.ComponentResolution((component,), ("template",))
    hazard = evidence.HazardSnapshot(
        "hazard", "battery", evidence.ScopeKind.MODEL, "model", "applies", (),
        evidence.HazardSeverity.CAUTION, ("action",), ("follow up",), ("handle",),
        ("dispose",), evidence.EvidenceLevel.D, (source,),
    )
    hazards = evidence.HazardResolution((hazard,))
    rule = evidence.PolicyRuleSnapshot(
        "rule", 1, evidence.RecommendationValue.REPAIR, (), (), "rationale",
        evidence.EvidenceLevel.A, (source,),
    )
    policy = evidence.PolicyBundleSnapshot("1.0.0", (rule,))
    stamp = evidence.BundleStamp(3, "3.0.0", "1.0.0", "1.0.0", "a" * 64)
    manifest = evidence.KnowledgeManifest(
        3, "3.0.0", "1.0.0", "1.0.0", "a" * 64, "b" * 64
    )
    return (
        scope,
        evidence.LifecycleRequest("device", "service life", "years", "years"),
        evidence.CategorySnapshot("0303_laptop", "Laptop"),
        source,
        evidence.IdentityRecordSnapshot(
            "identity", evidence.IdentityKind.MODEL, "0303_laptop", "notebook",
            "manufacturer", "Manufacturer", "family", "Family", "model", "Model",
            "Display", (), (), None, None, None, None, (), evidence.MarketState.CURRENT,
            evidence.BatteryArchitecture.BATTERY_BEARING, (source,),
        ),
        lifecycle,
        step,
        lifecycle_resolution,
        component,
        components,
        hazard,
        hazards,
        rule,
        policy,
        stamp,
        evidence.ResolvedEvidence(scope, lifecycle_resolution, components, hazards, policy, stamp),
        manifest,
    )


def test_every_record_rejects_field_mutation():
    records = make_all_records()
    assert len(records) == 17
    for record in records:
        with pytest.raises(FrozenInstanceError):
            setattr(record, fields(record)[0].name, None)


def test_knowledge_manifest_exposes_stamp_as_the_only_property_projection():
    assert [
        name
        for name, value in evidence.KnowledgeManifest.__dict__.items()
        if isinstance(value, property)
    ] == ["stamp"]
    assert all(
        not any(isinstance(value, property) for value in record.__dict__.values())
        for record in EXPECTED_RECORDS
        if record is not evidence.KnowledgeManifest
    )


@pytest.mark.parametrize("outcome", ("no_candidates", "filtered", "selected", "conflict"))
def test_resolution_step_accepts_only_approved_outcomes(outcome):
    step = evidence.ResolutionStep(
        evidence.ResolutionTier.EXACT_MODEL, (), (), None, outcome
    )
    assert step.outcome == outcome


@pytest.mark.parametrize("outcome", ("", "fallback", "merged", "selected "))
def test_resolution_step_rejects_outcomes_outside_the_closed_vocabulary(outcome):
    with pytest.raises(ValueError, match="resolution outcome"):
        evidence.ResolutionStep(
            evidence.ResolutionTier.EXACT_MODEL, (), (), None, outcome
        )
