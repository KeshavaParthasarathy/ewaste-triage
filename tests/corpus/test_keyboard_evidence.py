from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from scripts.knowledge_schema import (
    TemplateKind,
    UnknownClaimKind,
    load_category_evidence_documents,
)
from server.evidence_types import (
    AssociationStatus,
    BatteryArchitecture,
    EvidenceLevel,
    HazardSeverity,
    IdentityKind,
    LifecycleEndpointKind,
    ScopeKind,
)


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "reference"
CATEGORY_ID = "0301_keyboard"
REVIEWER = "OpenAI Codex automated source review"

EXPECTED_KEYBOARD_IDENTITIES = {
    "apple_extended_keyboard_ii",
    "apple_magic_keyboard_usb_c",
    "dell_kb216",
    "ibm_model_m_1391401",
    "keychron_k2_v2",
    "logitech_k120",
    "logitech_k780",
    "logitech_mx_keys_s",
    "microsoft_wired_keyboard_600",
    "razer_blackwidow_v4",
}

EXPECTED_UNKNOWN_IDENTITIES = {
    "apple_extended_keyboard_ii",
    "apple_magic_keyboard_usb_c",
    "dell_kb216",
    "ibm_model_m_1391401",
    "keychron_k2_v2",
    "logitech_k120",
    "microsoft_wired_keyboard_600",
}


@pytest.fixture(scope="module")
def keyboard_records():
    return load_category_evidence_documents(REFERENCE, CATEGORY_ID)


def test_keyboard_development_roster_separates_reviewed_and_unknown_identities(
    keyboard_records,
):
    reviewed = {item.identity_id for item in keyboard_records.identities}
    unknown = {
        item.claim_id
        for item in keyboard_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
    }

    assert reviewed.isdisjoint(unknown)
    assert reviewed | unknown == EXPECTED_KEYBOARD_IDENTITIES
    assert reviewed == {
        "logitech_k780",
        "logitech_mx_keys_s",
        "razer_blackwidow_v4",
    }
    assert unknown == EXPECTED_UNKNOWN_IDENTITIES
    assert len({item.manufacturer_id for item in keyboard_records.identities}) >= 2


def test_keyboard_reviewed_subtypes_and_power_architecture_gaps_are_explicit(
    keyboard_records,
):
    subtypes = {item.subtype_id: item for item in keyboard_records.subtypes}
    variants = {item.variant_id: item for item in keyboard_records.variants}
    unknown_subtypes = {
        item.claim_id: item
        for item in keyboard_records.unknowns
        if item.claim_kind is UnknownClaimKind.SUBTYPE
    }

    assert set(subtypes) == {
        "keyboard_mechanical",
        "keyboard_wireless_rechargeable",
        "keyboard_wireless_replaceable_battery",
    }
    assert set(unknown_subtypes) == {
        "keyboard_buckling_spring_legacy",
        "keyboard_wired_membrane",
    }
    assert set(subtypes) | set(unknown_subtypes) == {
        "keyboard_buckling_spring_legacy",
        "keyboard_mechanical",
        "keyboard_wired_membrane",
        "keyboard_wireless_rechargeable",
        "keyboard_wireless_replaceable_battery",
    }
    assert set(variants) == {
        "keyboard_rechargeable_internal",
        "keyboard_replaceable_aaa",
        "keyboard_wired_tethered",
    }
    assert {
        item.battery_architecture for item in subtypes.values()
    } == {
        BatteryArchitecture.BATTERY_FREE,
        BatteryArchitecture.BATTERY_BEARING,
    }
    assert {
        (item.subtype_id, item.battery_architecture) for item in variants.values()
    } == {
        ("keyboard_mechanical", BatteryArchitecture.BATTERY_FREE),
        (
            "keyboard_wireless_rechargeable",
            BatteryArchitecture.BATTERY_BEARING,
        ),
        (
            "keyboard_wireless_replaceable_battery",
            BatteryArchitecture.BATTERY_BEARING,
        ),
    }
    membrane_unknown = unknown_subtypes["keyboard_wired_membrane"]
    assert membrane_unknown.evidence_level is None
    assert membrane_unknown.source_ids == ()
    assert "membrane" in membrane_unknown.reason.casefold()
    legacy_unknown = unknown_subtypes["keyboard_buckling_spring_legacy"]
    assert legacy_unknown.evidence_level is None
    assert legacy_unknown.source_ids == ()
    assert "power architecture" in legacy_unknown.reason.casefold()
    assert "legacy overlay" in legacy_unknown.evidence_request.casefold()


def test_keyboard_sources_have_honest_dated_automated_reviews(keyboard_records):
    assert keyboard_records.sources
    assert {item.accessed_on for item in keyboard_records.sources} == {
        date(2026, 9, 10)
    }
    assert {item.reviewed_on for item in keyboard_records.sources} == {
        date(2026, 9, 10)
    }
    assert {item.reviewed_by for item in keyboard_records.sources} == {REVIEWER}
    assert all(
        item.publication_or_revision_date <= item.reviewed_on
        for item in keyboard_records.sources
    )
    assert all(
        urlsplit(item.canonical_url).hostname
        and not urlsplit(item.canonical_url).hostname.endswith("example.invalid")
        for item in keyboard_records.sources
    )

    sources = {item.source_id: item for item in keyboard_records.sources}
    assert {
        source_id: sources[source_id].publication_or_revision_date
        for source_id in {
            "ibm_model_m_buckling_spring_2026",
            "logitech_k780_technical_specifications_2025",
            "logitech_mx_keys_s_specification_2023",
            "razer_blackwidow_v4_launch_2023",
            "razer_blackwidow_v4_pro_launch_2023",
        }
    } == {
        "ibm_model_m_buckling_spring_2026": date(2026, 8, 7),
        "logitech_k780_technical_specifications_2025": date(2025, 1, 13),
        "logitech_mx_keys_s_specification_2023": date(2023, 5, 25),
        "razer_blackwidow_v4_launch_2023": date(2023, 7, 18),
        "razer_blackwidow_v4_pro_launch_2023": date(2023, 2, 16),
    }
    known_source_ids = set(sources)
    for identity in keyboard_records.identities:
        assert set(identity.source_ids) <= known_source_ids


def test_keyboard_reviewed_identity_scopes_preserve_exact_models_and_family(
    keyboard_records,
):
    identities = {item.identity_id: item for item in keyboard_records.identities}

    mx_keys = identities["logitech_mx_keys_s"]
    assert mx_keys.identity_kind is IdentityKind.MODEL
    assert mx_keys.model_id == "logitech_mx_keys_s"
    assert mx_keys.subtype_id == "keyboard_wireless_rechargeable"
    assert mx_keys.variant_ids == ("keyboard_rechargeable_internal",)
    assert "y-r0073" in mx_keys.distinguishing_tokens
    assert mx_keys.evidence_level is EvidenceLevel.A

    k780 = identities["logitech_k780"]
    assert k780.identity_kind is IdentityKind.FAMILY
    assert k780.family_id == k780.identity_id
    assert k780.model_id is None
    assert k780.model_name is None
    assert k780.subtype_id == "keyboard_wireless_replaceable_battery"
    assert k780.variant_ids == ("keyboard_replaceable_aaa",)
    assert {"y-r0061", "y-r0105"} <= set(k780.distinguishing_tokens)
    assert k780.evidence_level is EvidenceLevel.B

    blackwidow = identities["razer_blackwidow_v4"]
    assert blackwidow.identity_kind is IdentityKind.MODEL
    assert blackwidow.model_id == "razer_blackwidow_v4"
    assert blackwidow.subtype_id == "keyboard_mechanical"
    assert blackwidow.variant_ids == ("keyboard_wired_tethered",)
    assert blackwidow.evidence_level is EvidenceLevel.A
    assert all(
        forbidden not in " ".join(
            (
                blackwidow.display_name,
                *blackwidow.aliases,
                *blackwidow.distinguishing_tokens,
            )
        ).casefold()
        for forbidden in ("v4 pro", "v4 x", "v4 75%")
    )


def test_keyboard_endurance_records_preserve_subject_scope_and_point_ceilings(
    keyboard_records,
):
    records = {item.record_id: item for item in keyboard_records.specific_lifecycles}

    assert set(records) == {
        "logitech_k780_cell_runtime",
        "logitech_mx_keys_s_charge_runtime",
        "razer_blackwidow_v4_switch_actuation_endurance",
    }
    expected = {
        "logitech_mx_keys_s_charge_runtime": (
            ScopeKind.MODEL,
            EvidenceLevel.A,
            "logitech_mx_keys_s",
            "device",
            "charge_runtime",
            "elapsed_time",
            "months",
            5.0,
            ("keyboard_rechargeable_internal",),
        ),
        "logitech_k780_cell_runtime": (
            ScopeKind.FAMILY,
            EvidenceLevel.B,
            "logitech_k780",
            "device",
            "cell_runtime",
            "elapsed_time",
            "months",
            24.0,
            ("keyboard_replaceable_aaa",),
        ),
        "razer_blackwidow_v4_switch_actuation_endurance": (
            ScopeKind.MODEL,
            EvidenceLevel.A,
            "razer_blackwidow_v4",
            "mechanical_switch",
            "switch_actuation_endurance",
            "actuation_count",
            "keystrokes",
            100_000_000.0,
            (),
        ),
    }
    for record_id, record in records.items():
        (
            scope_kind,
            evidence_level,
            scope_id,
            subject,
            endpoint,
            metric,
            unit,
            maximum,
            required_variants,
        ) = expected[record_id]
        assert record.scope.kind is scope_kind
        assert record.scope.id == scope_id
        assert record.subject == subject
        assert record.endpoint == endpoint
        assert record.endpoint_kind is LifecycleEndpointKind.OPERATING_ENDURANCE
        assert record.metric == metric
        assert record.unit == unit
        assert (record.lower_bound, record.upper_bound) == (maximum, maximum)
        assert record.required_variant_ids == required_variants
        assert "up to" in record.endpoint_qualification.casefold()
        assert "not a guaranteed minimum" in record.endpoint_qualification.casefold()
        assert record.evidence_level is evidence_level

    mx_qualification = records[
        "logitech_mx_keys_s_charge_runtime"
    ].endpoint_qualification.casefold()
    assert "backlight off" in mx_qualification
    assert "10 days" not in mx_qualification

    k780_assumptions = " ".join(
        records["logitech_k780_cell_runtime"].assumptions
    ).casefold()
    assert "y-r0061" in k780_assumptions
    assert "y-r0105" in k780_assumptions
    assert "18-month" in k780_assumptions

    razer = records["razer_blackwidow_v4_switch_actuation_endurance"]
    assert razer.source_ids == (
        "razer_blackwidow_v4_launch_2023",
        "razer_blackwidow_v4_pro_launch_2023",
    )
    razer_assumptions = " ".join(razer.assumptions).casefold()
    assert "same-generation component-identity inference" in razer_assumptions
    assert "not a color-only mapping" in razer_assumptions
    assert "whole keyboard" in razer_assumptions


def test_keyboard_broad_service_life_is_unknown_not_numeric(keyboard_records):
    average_unknowns = {
        item.claim_id
        for item in keyboard_records.unknowns
        if item.claim_kind is UnknownClaimKind.INDUSTRY_AVERAGE
    }

    assert keyboard_records.industry_averages == ()
    assert average_unknowns == {"keyboard_industry_service_life"}


def test_keyboard_component_layers_cover_standard_and_modern_architectures(
    keyboard_records,
):
    templates = {item.template_id: item for item in keyboard_records.component_templates}
    associations: dict[str, list] = {}
    for item in keyboard_records.component_associations:
        associations.setdefault(item.template_id, []).append(item)

    assert set(templates) == {
        "keyboard_modern_wireless",
        "keyboard_standard",
    }
    assert templates["keyboard_standard"].template_kind is TemplateKind.STANDARD
    assert templates["keyboard_standard"].scope == type(
        templates["keyboard_standard"].scope
    )(ScopeKind.CATEGORY, CATEGORY_ID)
    assert templates["keyboard_modern_wireless"].template_kind is (
        TemplateKind.MODERN_OVERLAY
    )
    assert templates["keyboard_modern_wireless"].scope == type(
        templates["keyboard_modern_wireless"].scope
    )(ScopeKind.SUBTYPE, "keyboard_wireless_rechargeable")
    assert all(
        item.template_kind is not TemplateKind.LEGACY_OVERLAY
        for item in templates.values()
    )

    standard_components = {
        item.component_id for item in associations["keyboard_standard"]
    }
    assert standard_components >= {
        "enclosure",
        "buckling_spring_mechanism",
        "keycaps",
        "matrix_controller",
        "power_source",
        "replaceable_cell_compartment",
        "switch_membrane_assembly",
        "wired_cable",
        "wireless_module",
    }
    modern_components = {
        item.component_id for item in associations["keyboard_modern_wireless"]
    }
    assert modern_components >= {"battery_chemistry", "power_source", "wireless_module"}
    buckling = next(
        item
        for item in associations["keyboard_standard"]
        if item.component_id == "buckling_spring_mechanism"
    )
    assert buckling.status is AssociationStatus.CONDITIONAL
    assert "does not establish" in buckling.applicability.casefold()


def test_keyboard_components_keep_hidden_materials_and_chemistry_unknown(
    keyboard_records,
):
    by_id = {
        item.association_id: item for item in keyboard_records.component_associations
    }
    unknown_associations = {
        item.claim_id
        for item in keyboard_records.unknowns
        if item.claim_kind is UnknownClaimKind.COMPONENT_ASSOCIATION
    }
    required_unknowns = {
        "keyboard_standard_buckling_spring_material_unknown",
        "keyboard_modern_wireless_battery_chemistry_unknown",
        "keyboard_standard_controller_material_unknown",
        "keyboard_standard_enclosure_material_unknown",
        "keyboard_standard_keycap_material_unknown",
        "keyboard_standard_matrix_controller_unknown",
        "keyboard_standard_switch_material_unknown",
    }

    assert required_unknowns == unknown_associations
    assert required_unknowns == {
        item.association_id
        for item in keyboard_records.component_associations
        if item.status is AssociationStatus.UNKNOWN
    }
    for association_id in required_unknowns:
        association = by_id[association_id]
        assert association.evidence_level is None
        assert association.source_ids == ()

    assert by_id["keyboard_standard_power_source"].status is (
        AssociationStatus.CONDITIONAL
    )
    assert by_id["keyboard_standard_replaceable_cell_compartment"].status is (
        AssociationStatus.CONDITIONAL
    )
    assert "replaceable" in by_id[
        "keyboard_standard_replaceable_cell_compartment"
    ].applicability.casefold()
    assert "rechargeable" in by_id[
        "keyboard_modern_wireless_power_source"
    ].applicability.casefold()


def test_keyboard_hazards_preserve_variant_and_precautionary_trigger_boundaries(
    keyboard_records,
):
    hazards = {item.hazard_id: item for item in keyboard_records.hazards}

    assert set(hazards) == {
        "keyboard_damaged_lithium_ion_battery",
        "keyboard_leaking_primary_cell",
    }
    rechargeable = hazards["keyboard_damaged_lithium_ion_battery"]
    primary = hazards["keyboard_leaking_primary_cell"]
    assert rechargeable.scope == type(rechargeable.scope)(
        ScopeKind.SUBTYPE, "keyboard_wireless_rechargeable"
    )
    assert primary.scope == type(primary.scope)(
        ScopeKind.SUBTYPE, "keyboard_wireless_replaceable_battery"
    )
    assert rechargeable.component_id == "power_source"
    assert primary.component_id == "power_source"
    assert rechargeable.severity is HazardSeverity.URGENT
    assert primary.severity is HazardSeverity.CAUTION
    assert rechargeable.trigger_observation_keys == (
        "observations.issue_flags.overheating",
        "observations.issue_flags.swelling_or_battery_damage",
    )
    assert primary.trigger_observation_keys == (
        "observations.issue_flags.swelling_or_battery_damage",
    )
    assert rechargeable.source_ids == ("epa_used_li_ion_2026",)
    assert primary.source_ids == ("keyboard_health_canada_battery_safety_2024",)

    rechargeable_applicability = rechargeable.applicability.casefold()
    assert "activates precautionary guidance" in rechargeable_applicability
    assert "if the installed battery is lithium-ion" in rechargeable_applicability
    assert "do not establish chemistry" in rechargeable_applicability
    assert "trigger only when" not in rechargeable_applicability

    primary_applicability = primary.applicability.casefold()
    assert "activates precautionary guidance" in primary_applicability
    assert "if the installed cell is leaking" in primary_applicability
    assert "if it is non-rechargeable" in primary_applicability
    assert "do not establish leakage" in primary_applicability
    assert "trigger only when" not in primary_applicability

    rechargeable_actions = (
        *rechargeable.immediate_actions,
        *rechargeable.follow_up_actions,
        *rechargeable.handling_guidance,
        *rechargeable.disposal_guidance,
    )
    for action in rechargeable_actions:
        action_text = action.casefold()
        if any(
            marker in action_text
            for marker in (
                "lithium-ion",
                "certified electronics recycler",
                "damaged batteries before transport",
            )
        ):
            assert action_text.startswith("if ")
    assert all(
        "the damaged battery" not in action.casefold()
        for action in rechargeable_actions
    )

    assert "if leakage is present" in primary.immediate_actions[0].casefold()
    assert "if leakage is present" in primary.follow_up_actions[1].casefold()
    assert "if the installed cell is non-rechargeable" in (
        primary.handling_guidance[0].casefold()
    )


def test_keyboard_packet_does_not_claim_release_completion(keyboard_records):
    identity_unknowns = {
        item.claim_id
        for item in keyboard_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
    }
    average_unknowns = {
        item.claim_id
        for item in keyboard_records.unknowns
        if item.claim_kind is UnknownClaimKind.INDUSTRY_AVERAGE
    }
    subtype_unknowns = {
        item.claim_id
        for item in keyboard_records.unknowns
        if item.claim_kind is UnknownClaimKind.SUBTYPE
    }

    assert len(keyboard_records.identities) == 3
    assert identity_unknowns == EXPECTED_UNKNOWN_IDENTITIES
    assert average_unknowns == {"keyboard_industry_service_life"}
    assert subtype_unknowns == {
        "keyboard_buckling_spring_legacy",
        "keyboard_wired_membrane",
    }
