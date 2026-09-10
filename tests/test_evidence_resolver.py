"""Behavioral contract tests for deterministic reviewed-evidence resolution."""

from dataclasses import replace
from datetime import date
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.knowledge_compiler import compile_knowledge_bundle
from server.evidence_resolver import EvidenceResolver
from server.evidence_types import (
    AssociationStatus,
    BundleStamp,
    CanonicalIdentityScope,
    ComponentAssociationSnapshot,
    ComponentResolution,
    EvidenceLevel,
    HazardResolution,
    HazardSeverity,
    HazardSnapshot,
    KnowledgeManifest,
    LifecycleEndpointKind,
    LifecycleRecordSnapshot,
    LifecycleRequest,
    LifecycleResolution,
    PolicyBundleSnapshot,
    PolicyRuleSnapshot,
    RecommendationValue,
    ResolvedEvidence,
    ResolutionStep,
    ResolutionTier,
    ScopeKind,
    SourceSnapshot,
)
from server.knowledge_store import KnowledgeStore, _ComponentTemplateLayer
from tests.knowledge_helpers import make_valid_knowledge_source


PHONE = "0306_mobile_phone"
PHONE_SUBTYPE = "phone_smartphone"
PHONE_FAMILY = "phone_family"
PHONE_MODEL = "phone_model"
SERVICE_LIFE = LifecycleRequest("device", "service_life", "elapsed_time", "years")


def source(source_id: str) -> SourceSnapshot:
    return SourceSnapshot(
        source_id,
        f"Evidence for {source_id}",
        "Synthetic Evidence Publisher",
        f"https://example.invalid/{source_id}",
        date(2026, 1, 1),
        date(2026, 9, 7),
        "synthetic-test-fixture",
        "test-reviewer",
        date(2026, 9, 7),
    )


def lifecycle(
    record_id: str,
    tier: ResolutionTier,
    scope_kind: ScopeKind,
    scope_id: str,
    *,
    subject: str = "device",
    endpoint: str = "service_life",
    metric: str = "elapsed_time",
    unit: str = "years",
    precedence: int = 0,
    model_year_from: int | None = None,
    model_year_to: int | None = None,
    applicable_from: date | None = None,
    applicable_to: date | None = None,
    required_variant_ids: tuple[str, ...] = (),
    excluded_variant_ids: tuple[str, ...] = (),
) -> LifecycleRecordSnapshot:
    endpoint_kind = (
        LifecycleEndpointKind.TOTAL_LIFE
        if endpoint == "service_life"
        else LifecycleEndpointKind.CAPACITY_THRESHOLD
    )
    evidence_level = {
        ResolutionTier.EXACT_MODEL: EvidenceLevel.A,
        ResolutionTier.FAMILY: EvidenceLevel.B,
        ResolutionTier.SUBTYPE: EvidenceLevel.B,
        ResolutionTier.INDUSTRY_AVERAGE: EvidenceLevel.C,
    }[tier]
    is_average = tier is ResolutionTier.INDUSTRY_AVERAGE
    return LifecycleRecordSnapshot(
        record_id,
        tier,
        scope_kind,
        scope_id,
        subject,
        endpoint,
        endpoint_kind,
        metric,
        unit,
        3.0,
        7.0,
        f"Qualification for {record_id}.",
        applicable_from,
        applicable_to,
        model_year_from,
        model_year_to,
        required_variant_ids,
        excluded_variant_ids,
        precedence,
        evidence_level,
        ("Comparable use",),
        "Broad population" if is_average else None,
        "2020-2025" if is_average else None,
        "Reviewed method" if is_average else None,
        "Population uncertainty" if is_average else None,
        ("Fixture limitation",),
        (source("eu_phone_ecodesign_2023_1670"),),
    )


def association(
    association_id: str,
    template_id: str,
    component_id: str,
    status: AssociationStatus,
    scope_kind: ScopeKind,
    scope_id: str,
) -> ComponentAssociationSnapshot:
    unknown = status is AssociationStatus.UNKNOWN
    return ComponentAssociationSnapshot(
        association_id,
        template_id,
        component_id,
        component_id.replace("_", " ").title(),
        status,
        scope_kind,
        scope_id,
        f"Applicability for {association_id}.",
        (f"Note for {association_id}.",),
        None if unknown else EvidenceLevel.C,
        () if unknown else (source("component_source"),),
    )


POLICY = PolicyBundleSnapshot(
    "2.0.0",
    (
        PolicyRuleSnapshot(
            "baseline_policy",
            0,
            RecommendationValue.REUSE,
            ("identity.state=canonical",),
            (),
            "Canonical evidence may reach reviewed policy.",
            EvidenceLevel.D,
            (source("policy_source"),),
        ),
    ),
)
MANIFEST = KnowledgeManifest(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64, "b" * 64)


class FakeStore:
    def __init__(self, *, lifecycle_records=(), layers=(), hazards=()):
        self.lifecycle_records = tuple(lifecycle_records)
        self.layers = tuple(layers)
        self.hazards = tuple(hazards)
        self.manifest = MANIFEST

    def lifecycle_candidates(self, scope):
        return self.lifecycle_records

    def component_layers(self, scope):
        return self.layers

    def hazard_candidates(self, scope):
        return self.hazards

    def policy_bundle(self):
        return POLICY


@pytest.fixture
def phone_scope():
    return CanonicalIdentityScope(
        PHONE,
        PHONE_SUBTYPE,
        PHONE_FAMILY,
        PHONE_MODEL,
        ("phone_variant_base",),
        2024,
        date(2024, 6, 1),
    )


@pytest.fixture
def phone_records():
    return (
        lifecycle(
            "phone_subtype_capacity_threshold",
            ResolutionTier.SUBTYPE,
            ScopeKind.SUBTYPE,
            PHONE_SUBTYPE,
            subject="battery",
            endpoint="capacity_threshold",
            metric="full_charge_cycles",
            unit="cycles",
        ),
        lifecycle(
            "phone_industry_service_life",
            ResolutionTier.INDUSTRY_AVERAGE,
            ScopeKind.CATEGORY,
            PHONE,
            precedence=4,
        ),
        lifecycle(
            "phone_exact_service_life",
            ResolutionTier.EXACT_MODEL,
            ScopeKind.MODEL,
            PHONE_MODEL,
            subject="battery",
            required_variant_ids=("phone_variant_pro",),
        ),
        lifecycle(
            "phone_family_service_life",
            ResolutionTier.FAMILY,
            ScopeKind.FAMILY,
            PHONE_FAMILY,
            precedence=2,
        ),
    )


@pytest.fixture
def resolver(phone_records):
    keyboard = association(
        "keyboard_chassis",
        "keyboard_standard",
        "chassis",
        AssociationStatus.COMMONLY_ASSOCIATED,
        ScopeKind.CATEGORY,
        "0301_keyboard",
    )
    phone_hazard = HazardSnapshot(
        "phone_damaged_li_ion",
        "battery",
        ScopeKind.CATEGORY,
        PHONE,
        "Applicable only when damage is reported.",
        ("observations.issue_flags.swelling_or_battery_damage",),
        HazardSeverity.URGENT,
        ("Stop using the item.",),
        ("Seek specialist handling.",),
        ("Avoid pressure or puncture.",),
        ("Use a certified recycler.",),
        EvidenceLevel.D,
        (source("epa_used_li_ion_2026"),),
    )
    return EvidenceResolver(
        FakeStore(
            lifecycle_records=phone_records,
            layers=(_ComponentTemplateLayer("keyboard_standard", (keyboard,)),),
            hazards=(phone_hazard,),
        )
    )


def test_compatible_family_beats_subtype_and_average(
    resolver, phone_scope, phone_records,
):
    result = resolver.resolve_lifecycle(phone_scope, SERVICE_LIFE)

    assert result == LifecycleResolution(
        record=next(
            record
            for record in phone_records
            if record.record_id == "phone_family_service_life"
        ),
        tier=ResolutionTier.FAMILY,
        trace=(
            ResolutionStep(
                ResolutionTier.EXACT_MODEL,
                ("phone_exact_service_life",),
                (("phone_exact_service_life", "subject mismatch"),),
                None,
                "filtered",
            ),
            ResolutionStep(
                ResolutionTier.FAMILY,
                ("phone_family_service_life",),
                (),
                "phone_family_service_life",
                "selected",
            ),
        ),
        unknown_reason=None,
    )


def test_incompatible_exact_record_is_filtered_before_specificity(
    resolver, phone_scope,
):
    result = resolver.resolve_lifecycle(
        phone_scope,
        LifecycleRequest("battery", "capacity_threshold", "full_charge_cycles", "cycles"),
    )

    assert result.record.record_id == "phone_subtype_capacity_threshold"
    assert result.trace == (
        ResolutionStep(
            ResolutionTier.EXACT_MODEL,
            ("phone_exact_service_life",),
            (("phone_exact_service_life", "endpoint mismatch"),),
            None,
            "filtered",
        ),
        ResolutionStep(
            ResolutionTier.FAMILY,
            ("phone_family_service_life",),
            (("phone_family_service_life", "subject mismatch"),),
            None,
            "filtered",
        ),
        ResolutionStep(
            ResolutionTier.SUBTYPE,
            ("phone_subtype_capacity_threshold",),
            (),
            "phone_subtype_capacity_threshold",
            "selected",
        ),
    )


def test_endpoint_is_checked_before_variant_compatibility(phone_scope):
    record = lifecycle(
        "exact",
        ResolutionTier.EXACT_MODEL,
        ScopeKind.MODEL,
        PHONE_MODEL,
        required_variant_ids=("missing",),
    )
    result = EvidenceResolver(FakeStore(lifecycle_records=(record,))).resolve_lifecycle(
        phone_scope,
        LifecycleRequest("device", "capacity_threshold", "elapsed_time", "years"),
    )
    assert result.trace[0].rejected == (("exact", "endpoint mismatch"),)


def test_equal_precedence_conflict_returns_unknown_without_lower_tier_fallback(
    phone_scope,
):
    family_a = lifecycle(
        "family_a", ResolutionTier.FAMILY, ScopeKind.FAMILY, PHONE_FAMILY, precedence=1,
    )
    family_b = lifecycle(
        "family_b", ResolutionTier.FAMILY, ScopeKind.FAMILY, PHONE_FAMILY, precedence=1,
    )
    family_later = lifecycle(
        "family_later", ResolutionTier.FAMILY, ScopeKind.FAMILY, PHONE_FAMILY, precedence=2,
    )
    average = lifecycle(
        "average", ResolutionTier.INDUSTRY_AVERAGE, ScopeKind.CATEGORY, PHONE,
    )
    result = EvidenceResolver(
        FakeStore(lifecycle_records=(average, family_b, family_later, family_a))
    ).resolve_lifecycle(phone_scope, SERVICE_LIFE)

    assert result == LifecycleResolution(
        None,
        None,
        (
            ResolutionStep(
                ResolutionTier.EXACT_MODEL, (), (), None, "no_candidates",
            ),
            ResolutionStep(
                ResolutionTier.FAMILY,
                ("family_a", "family_b", "family_later"),
                (),
                None,
                "conflict",
            ),
        ),
        "Conflicting reviewed records at the same evidence tier.",
    )


@pytest.fixture
def applicability_scope():
    return CanonicalIdentityScope(
        PHONE, PHONE_SUBTYPE, PHONE_FAMILY, PHONE_MODEL, (), 2022, date(2022, 6, 1),
    )


@pytest.fixture
def resolver_with_applicability():
    bounded = lifecycle(
        "bounded_specific",
        ResolutionTier.EXACT_MODEL,
        ScopeKind.MODEL,
        PHONE_MODEL,
        model_year_from=2020,
        model_year_to=2025,
        applicable_from=date(2020, 1, 1),
        applicable_to=date(2025, 12, 31),
    )
    fallback = lifecycle(
        "unconstrained_specific",
        ResolutionTier.EXACT_MODEL,
        ScopeKind.MODEL,
        PHONE_MODEL,
        precedence=1,
    )
    return EvidenceResolver(FakeStore(lifecycle_records=(fallback, bounded)))


@pytest.mark.parametrize(
    ("model_year", "applicable_on"),
    [(2020, date(2020, 1, 1)), (2025, date(2025, 12, 31))],
)
def test_year_and_date_bounds_are_inclusive(
    resolver_with_applicability, applicability_scope, model_year, applicable_on,
):
    scope = replace(
        applicability_scope, model_year=model_year, applicable_on=applicable_on,
    )
    result = resolver_with_applicability.resolve_lifecycle(scope, SERVICE_LIFE)
    assert result.record.record_id == "bounded_specific"


@pytest.mark.parametrize(
    ("missing_field", "reason"),
    [
        ("model_year", "model year unavailable"),
        ("applicable_on", "applicability date unavailable"),
    ],
)
def test_missing_singular_applicability_rejects_only_constrained_record(
    resolver_with_applicability, applicability_scope, missing_field, reason,
):
    scope = replace(applicability_scope, **{missing_field: None})
    result = resolver_with_applicability.resolve_lifecycle(scope, SERVICE_LIFE)
    assert result.record.record_id == "unconstrained_specific"
    assert result.trace[0].rejected == (("bounded_specific", reason),)


@pytest.mark.parametrize(
    ("scope_change", "reason"),
    [
        ({"model_year": 2019}, "model year out of range"),
        ({"model_year": 2026}, "model year out of range"),
        ({"applicable_on": date(2019, 12, 31)}, "applicability date out of range"),
        ({"applicable_on": date(2026, 1, 1)}, "applicability date out of range"),
    ],
)
def test_out_of_range_values_have_closed_trace_reasons(
    resolver_with_applicability, applicability_scope, scope_change, reason,
):
    result = resolver_with_applicability.resolve_lifecycle(
        replace(applicability_scope, **scope_change), SERVICE_LIFE,
    )
    assert result.record.record_id == "unconstrained_specific"
    assert result.trace[0].rejected == (("bounded_specific", reason),)


@pytest.fixture
def resolver_with_variant_filters():
    specific = lifecycle(
        "variant_specific",
        ResolutionTier.EXACT_MODEL,
        ScopeKind.MODEL,
        PHONE_MODEL,
        required_variant_ids=("variant_a",),
        excluded_variant_ids=("variant_x",),
    )
    fallback = lifecycle(
        "unconstrained_specific",
        ResolutionTier.EXACT_MODEL,
        ScopeKind.MODEL,
        PHONE_MODEL,
        precedence=1,
    )
    return EvidenceResolver(FakeStore(lifecycle_records=(fallback, specific)))


def test_required_and_excluded_variants_are_deterministic(
    resolver_with_variant_filters, applicability_scope,
):
    eligible = replace(applicability_scope, variant_ids=("variant_a", "variant_b"))
    assert resolver_with_variant_filters.resolve_lifecycle(
        eligible, SERVICE_LIFE,
    ).record.record_id == "variant_specific"
    for variants, reason in [
        (("variant_b",), "required variant missing"),
        (("variant_a", "variant_x"), "excluded variant present"),
    ]:
        result = resolver_with_variant_filters.resolve_lifecycle(
            replace(applicability_scope, variant_ids=variants), SERVICE_LIFE,
        )
        assert result.record.record_id == "unconstrained_specific"
        assert result.trace[0].rejected == (("variant_specific", reason),)


@pytest.mark.parametrize(
    ("record_change", "scope_change", "lifecycle_request", "reason"),
    [
        ({"scope_id": "other_model"}, {}, SERVICE_LIFE, "scope mismatch"),
        ({"subject": "battery"}, {}, SERVICE_LIFE, "subject mismatch"),
        ({"endpoint": "capacity_threshold"}, {}, SERVICE_LIFE, "endpoint mismatch"),
        ({"metric": "full_charge_cycles"}, {}, SERVICE_LIFE, "metric mismatch"),
        ({"unit": "cycles"}, {}, SERVICE_LIFE, "unit mismatch"),
    ],
)
def test_hierarchy_and_request_mismatches_have_closed_trace_reasons(
    phone_scope, record_change, scope_change, lifecycle_request, reason,
):
    candidate = replace(
        lifecycle("specific", ResolutionTier.EXACT_MODEL, ScopeKind.MODEL, PHONE_MODEL),
        **record_change,
    )
    result = EvidenceResolver(FakeStore(lifecycle_records=(candidate,))).resolve_lifecycle(
        replace(phone_scope, **scope_change), lifecycle_request,
    )
    assert result.trace[0] == ResolutionStep(
        ResolutionTier.EXACT_MODEL,
        ("specific",),
        (("specific", reason),),
        None,
        "filtered",
    )


def test_no_compatible_record_returns_deterministic_unknown(phone_scope):
    result = EvidenceResolver(FakeStore()).resolve_lifecycle(phone_scope, SERVICE_LIFE)
    assert result == LifecycleResolution(
        None,
        None,
        tuple(
            ResolutionStep(tier, (), (), None, "no_candidates")
            for tier in (
                ResolutionTier.EXACT_MODEL,
                ResolutionTier.FAMILY,
                ResolutionTier.SUBTYPE,
                ResolutionTier.INDUSTRY_AVERAGE,
            )
        ),
        "No compatible reviewed lifecycle record.",
    )


def test_category_only_scope_uses_only_average_and_base_components():
    scope = CanonicalIdentityScope("0301_keyboard")
    average = lifecycle(
        "keyboard_average",
        ResolutionTier.INDUSTRY_AVERAGE,
        ScopeKind.CATEGORY,
        "0301_keyboard",
    )
    base = association(
        "keyboard_chassis",
        "keyboard_standard",
        "chassis",
        AssociationStatus.COMMONLY_ASSOCIATED,
        ScopeKind.CATEGORY,
        "0301_keyboard",
    )
    resolver = EvidenceResolver(
        FakeStore(
            lifecycle_records=(
                lifecycle(
                    "other_specific",
                    ResolutionTier.EXACT_MODEL,
                    ScopeKind.MODEL,
                    "other_model",
                ),
                average,
            ),
            layers=(_ComponentTemplateLayer("keyboard_standard", (base,)),),
        )
    )

    assert scope == CanonicalIdentityScope(
        category_id="0301_keyboard",
        subtype_id=None,
        family_id=None,
        model_id=None,
        variant_ids=(),
        model_year=None,
        applicable_on=None,
    )
    resolved = resolver.resolve(scope, SERVICE_LIFE)
    assert resolved.lifecycle.tier is ResolutionTier.INDUSTRY_AVERAGE
    assert resolved.components == ComponentResolution((base,), ("keyboard_standard",))


@pytest.fixture
def component_slot_scope():
    return CanonicalIdentityScope("category", "subtype", "family", "model")


@pytest.fixture
def resolver_with_component_slot_layers():
    layers = (
        _ComponentTemplateLayer(
            "base",
            tuple(
                association(
                    f"base_{component}",
                    "base",
                    component,
                    AssociationStatus.COMMONLY_ASSOCIATED,
                    ScopeKind.CATEGORY,
                    "category",
                )
                for component in ("chassis", "battery", "storage")
            ),
        ),
        _ComponentTemplateLayer(
            "subtype_overlay",
            (
                association(
                    "subtype_battery",
                    "subtype_overlay",
                    "battery",
                    AssociationStatus.CONDITIONAL,
                    ScopeKind.SUBTYPE,
                    "subtype",
                ),
                association(
                    "subtype_radio",
                    "subtype_overlay",
                    "radio",
                    AssociationStatus.COMMONLY_ASSOCIATED,
                    ScopeKind.SUBTYPE,
                    "subtype",
                ),
            ),
        ),
        _ComponentTemplateLayer(
            "family_overlay",
            (
                association(
                    "family_battery",
                    "family_overlay",
                    "battery",
                    AssociationStatus.LEGACY_SPECIFIC,
                    ScopeKind.FAMILY,
                    "family",
                ),
            ),
        ),
        _ComponentTemplateLayer(
            "model_overlay",
            (
                association(
                    "model_chassis_not_present",
                    "model_overlay",
                    "chassis",
                    AssociationStatus.NOT_PRESENT,
                    ScopeKind.MODEL,
                    "model",
                ),
                association(
                    "model_battery_unknown",
                    "model_overlay",
                    "battery",
                    AssociationStatus.UNKNOWN,
                    ScopeKind.MODEL,
                    "model",
                ),
                association(
                    "model_camera",
                    "model_overlay",
                    "camera",
                    AssociationStatus.EXACT_MODEL_CONFIRMED,
                    ScopeKind.MODEL,
                    "model",
                ),
            ),
        ),
    )
    return EvidenceResolver(FakeStore(layers=layers))


def test_component_replacements_retain_slots_and_new_components_append(
    resolver_with_component_slot_layers, component_slot_scope,
):
    first = resolver_with_component_slot_layers.resolve_components(component_slot_scope)
    second = resolver_with_component_slot_layers.resolve_components(component_slot_scope)

    assert first == second
    assert first.applied_template_ids == (
        "base", "subtype_overlay", "family_overlay", "model_overlay",
    )
    assert tuple(item.component_id for item in first.components) == (
        "chassis", "battery", "storage", "radio", "camera",
    )
    assert tuple(item.association_id for item in first.components) == (
        "model_chassis_not_present",
        "model_battery_unknown",
        "base_storage",
        "subtype_radio",
        "model_camera",
    )
    assert first.components[0].status is AssociationStatus.NOT_PRESENT
    assert first.components[1].status is AssociationStatus.UNKNOWN


def test_empty_component_templates_remain_in_applied_template_ids(component_slot_scope):
    component = association(
        "base_chassis",
        "base",
        "chassis",
        AssociationStatus.COMMONLY_ASSOCIATED,
        ScopeKind.CATEGORY,
        "category",
    )
    layers = (
        _ComponentTemplateLayer("base", (component,)),
        _ComponentTemplateLayer("empty_subtype", ()),
        _ComponentTemplateLayer("empty_family", ()),
        _ComponentTemplateLayer("empty_model", ()),
    )
    result = EvidenceResolver(FakeStore(layers=layers)).resolve_components(
        component_slot_scope,
    )
    assert result == ComponentResolution(
        (component,), ("base", "empty_subtype", "empty_family", "empty_model"),
    )


def test_hazard_resolution_preserves_claim_specific_order_and_sources(phone_scope):
    category_hazard = HazardSnapshot(
        "phone_damaged_li_ion",
        "battery",
        ScopeKind.CATEGORY,
        PHONE,
        "Applicable only when damage is reported.",
        ("observations.issue_flags.swelling_or_battery_damage",),
        HazardSeverity.URGENT,
        ("Stop using the item.",),
        ("Seek specialist handling.",),
        ("Avoid pressure or puncture.",),
        ("Use a certified recycler.",),
        EvidenceLevel.D,
        (source("epa_used_li_ion_2026"),),
    )
    model_hazard = replace(
        category_hazard,
        hazard_id="phone_model_battery_handling",
        scope_kind=ScopeKind.MODEL,
        scope_id=PHONE_MODEL,
        evidence_level=EvidenceLevel.A,
        sources=(source("manufacturer_battery_guide"),),
    )
    unrelated = replace(
        category_hazard,
        hazard_id="unrelated",
        scope_kind=ScopeKind.FAMILY,
        scope_id="other_family",
    )
    resolver = EvidenceResolver(
        FakeStore(hazards=(model_hazard, category_hazard, unrelated))
    )

    result = resolver.resolve_hazards(phone_scope)
    assert result == HazardResolution((model_hazard, category_hazard))
    battery = next(item for item in result.hazards if item.hazard_id == "phone_damaged_li_ion")
    assert tuple(item.source_id for item in battery.sources) == ("epa_used_li_ion_2026",)
    assert "eu_phone_ecodesign_2023_1670" not in {
        item.source_id for item in battery.sources
    }


def test_resolve_attaches_uninterpreted_policy_and_bundle_stamp(phone_scope):
    record = lifecycle(
        "phone_exact", ResolutionTier.EXACT_MODEL, ScopeKind.MODEL, PHONE_MODEL,
    )
    hazard = HazardSnapshot(
        "hazard",
        "battery",
        ScopeKind.CATEGORY,
        PHONE,
        "Only if triggered later.",
        ("observations.issue_flags.overheating",),
        HazardSeverity.CAUTION,
        ("Stop use.",),
        (),
        (),
        (),
        EvidenceLevel.D,
        (source("hazard_source"),),
    )
    store = FakeStore(lifecycle_records=(record,), hazards=(hazard,))
    result = EvidenceResolver(store).resolve(phone_scope, SERVICE_LIFE)

    assert result == ResolvedEvidence(
        phone_scope,
        LifecycleResolution(
            record,
            ResolutionTier.EXACT_MODEL,
            (
                ResolutionStep(
                    ResolutionTier.EXACT_MODEL,
                    ("phone_exact",),
                    (),
                    "phone_exact",
                    "selected",
                ),
            ),
            None,
        ),
        ComponentResolution((), ()),
        HazardResolution((hazard,)),
        POLICY,
        BundleStamp(3, "3.0.0", "1.0.0", "2.0.0", "a" * 64),
    )


@pytest.fixture(scope="module")
def compiled_bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("resolver_bundle").resolve()
    source_dir = make_valid_knowledge_source(root / "source")
    out = root / "bundle"
    compile_knowledge_bundle(source_dir, out)
    return out


def test_real_store_integration_resolves_lifecycle_components_hazards_and_policy(
    compiled_bundle: Path,
):
    category = "0303_laptop"
    model = category + "_model_01"
    with KnowledgeStore(compiled_bundle / "knowledge.sqlite") as store:
        scope = store.identity_scope(model)
        result = EvidenceResolver(store).resolve(scope, SERVICE_LIFE)

        assert result.scope == scope
        assert result.lifecycle.record.record_id == category + "_lifecycle_0_model_service"
        assert result.lifecycle.tier is ResolutionTier.EXACT_MODEL
        assert tuple(item.association_id for item in result.components.components) == (
            category + "_association_standard_0",
            category + "_association_modern_0",
            category + "_association_modern_1_unknown",
        )
        assert tuple(item.hazard_id for item in result.hazards.hazards) == (
            category + "_damaged_battery_hazard",
        )
        assert result.policy.revision == "2.0.0"
        assert result.bundle == store.manifest.stamp


def test_runtime_resolver_imports_only_accepted_evidence_modules():
    code = '''import builtins
real = builtins.__import__
def guard(name, *args, **kwargs):
    forbidden = ("flask", "server.lifecycle", "server.assessment", "server.history")
    if name == "yaml" or name.startswith("scripts") or any(name.startswith(item) for item in forbidden):
        raise AssertionError(name)
    return real(name, *args, **kwargs)
builtins.__import__ = guard
from server.evidence_resolver import EvidenceResolver
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
