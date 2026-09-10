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
    LifecycleEndpointKind,
    ScopeKind,
)


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "reference"
CATEGORY_ID = "0301_computer_mouse"
REVIEWER = "OpenAI Codex automated source review"

EXPECTED_MOUSE_IDENTITIES = {
    "apple_magic_mouse_usb_c",
    "dell_ms116",
    "hp_x3000_g3",
    "logitech_g502_hero",
    "logitech_m185",
    "logitech_mx_master_3s",
    "microsoft_arc_mouse",
    "microsoft_basic_optical_mouse",
    "microsoft_intellimouse_1_1",
    "razer_deathadder_v3",
}


@pytest.fixture(scope="module")
def mouse_records():
    return load_category_evidence_documents(REFERENCE, CATEGORY_ID)


def test_mouse_development_roster_separates_reviewed_and_unknown_identities(
    mouse_records,
):
    reviewed = {item.identity_id for item in mouse_records.identities}
    unknown = {
        item.claim_id
        for item in mouse_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
    }

    assert reviewed.isdisjoint(unknown)
    assert reviewed | unknown == EXPECTED_MOUSE_IDENTITIES
    assert len(reviewed) == 7
    assert unknown == {
        "hp_x3000_g3",
        "microsoft_arc_mouse",
        "microsoft_intellimouse_1_1",
    }
    assert "hp_x3000_g3" not in reviewed
    assert "microsoft_arc_mouse" not in reviewed
    assert "microsoft_intellimouse_1_1" not in reviewed
    assert len({item.manufacturer_id for item in mouse_records.identities}) >= 2


def test_mouse_reviewed_subtypes_and_intended_legacy_gap_are_explicit(mouse_records):
    subtypes = {item.subtype_id: item for item in mouse_records.subtypes}
    variants = {item.variant_id: item for item in mouse_records.variants}
    unknown_subtypes = {
        item.claim_id: item
        for item in mouse_records.unknowns
        if item.claim_kind is UnknownClaimKind.SUBTYPE
    }

    assert set(subtypes) == {
        "mouse_wired_optical",
        "mouse_wireless_rechargeable",
        "mouse_wireless_replaceable_battery",
    }
    assert set(unknown_subtypes) == {"mouse_ball_legacy"}
    assert set(subtypes) | set(unknown_subtypes) == {
        "mouse_ball_legacy",
        "mouse_wired_optical",
        "mouse_wireless_rechargeable",
        "mouse_wireless_replaceable_battery",
    }
    assert set(variants) == {
        "mouse_rechargeable_usb_c",
        "mouse_replaceable_primary_cell",
        "mouse_wired_tethered",
    }
    assert {
        item.battery_architecture for item in subtypes.values()
    } == {
        BatteryArchitecture.BATTERY_FREE,
        BatteryArchitecture.BATTERY_BEARING,
    }
    assert {
        (item.subtype_id, item.battery_architecture) for item in variants.values()
    } >= {
        (
            "mouse_wireless_rechargeable",
            BatteryArchitecture.BATTERY_BEARING,
        ),
        (
            "mouse_wireless_replaceable_battery",
            BatteryArchitecture.BATTERY_BEARING,
        ),
    }
    assert {
        item.battery_architecture for item in variants.values()
    } == {
        BatteryArchitecture.BATTERY_FREE,
        BatteryArchitecture.BATTERY_BEARING,
    }
    legacy_unknown = unknown_subtypes["mouse_ball_legacy"]
    assert legacy_unknown.evidence_level is None
    assert legacy_unknown.source_ids == ()
    assert "power architecture" in legacy_unknown.reason
    assert "legacy overlay" in legacy_unknown.evidence_request


def test_mouse_sources_have_honest_dated_automated_reviews(mouse_records):
    assert mouse_records.sources
    assert {item.accessed_on for item in mouse_records.sources} == {
        date(2026, 9, 10)
    }
    assert {item.reviewed_on for item in mouse_records.sources} == {
        date(2026, 9, 10)
    }
    assert {item.reviewed_by for item in mouse_records.sources} == {REVIEWER}
    assert all(
        item.publication_or_revision_date <= item.reviewed_on
        for item in mouse_records.sources
    )
    assert all(
        urlsplit(item.canonical_url).hostname
        and not urlsplit(item.canonical_url).hostname.endswith("example.invalid")
        for item in mouse_records.sources
    )
    known_source_ids = {item.source_id for item in mouse_records.sources}
    sources = {item.source_id: item for item in mouse_records.sources}
    assert "dell_ms116_regulatory_2018" not in sources
    assert "dell_ms116_support_2025" not in sources
    dell = sources["dell_ms116_technical_specifications_2025"]
    assert dell.title == "Dell Wired Mouse MS116 Technical Specifications"
    assert dell.canonical_url == (
        "https://dl.dell.com/content/manual16876931-"
        "dell-wired-mouse-ms116-technical-specifications.pdf?language=en-us"
    )
    assert {
        source_id: sources[source_id].publication_or_revision_date
        for source_id in {
            "dell_ms116_technical_specifications_2025",
            "logitech_m185_runtime_2019",
            "logitech_mx_master_3s_setup_2024",
            "razer_deathadder_v3_launch_2023",
        }
    } == {
        "dell_ms116_technical_specifications_2025": date(2025, 2, 26),
        "logitech_m185_runtime_2019": date(2019, 7, 16),
        "logitech_mx_master_3s_setup_2024": date(2024, 7, 29),
        "razer_deathadder_v3_launch_2023": date(2023, 2, 21),
    }
    for identity in mouse_records.identities:
        assert set(identity.source_ids) <= known_source_ids


def test_mouse_endurance_records_preserve_exact_scope_and_qualified_maxima(
    mouse_records,
):
    records = {item.record_id: item for item in mouse_records.specific_lifecycles}

    assert set(records) == {
        "logitech_m185_cell_runtime",
        "logitech_mx_master_3s_charge_runtime",
        "razer_deathadder_v3_optical_switch_click_endurance",
    }
    expected = {
        "logitech_m185_cell_runtime": (
            ScopeKind.FAMILY,
            EvidenceLevel.B,
            "logitech_m185",
            "replaceable_cell",
            "cell_runtime",
            "elapsed_time",
            "months",
            12.0,
            ("mouse_replaceable_primary_cell",),
        ),
        "logitech_mx_master_3s_charge_runtime": (
            ScopeKind.MODEL,
            EvidenceLevel.A,
            "logitech_mx_master_3s",
            "device",
            "charge_runtime",
            "elapsed_time",
            "days",
            70.0,
            ("mouse_rechargeable_usb_c",),
        ),
        "razer_deathadder_v3_optical_switch_click_endurance": (
            ScopeKind.MODEL,
            EvidenceLevel.A,
            "razer_deathadder_v3",
            "optical_switch",
            "click_endurance",
            "actuation_count",
            "clicks",
            90_000_000.0,
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
        assert record.evidence_level is evidence_level

    assert "razer_deathadder_v3_pro_charge_runtime" not in records
    assert all(
        not (
            item.subject == "device"
            and item.endpoint_kind is LifecycleEndpointKind.TOTAL_LIFE
        )
        for item in records.values()
    )


def test_mouse_broad_service_life_is_a_real_unknown_not_a_numeric_record(
    mouse_records,
):
    average_unknowns = {
        item.claim_id
        for item in mouse_records.unknowns
        if item.claim_kind is UnknownClaimKind.INDUSTRY_AVERAGE
    }

    assert mouse_records.industry_averages == ()
    assert average_unknowns == {"mouse_industry_service_life"}


def test_mouse_component_layers_cover_required_architectures(mouse_records):
    templates = {item.template_id: item for item in mouse_records.component_templates}
    associations = {}
    for item in mouse_records.component_associations:
        associations.setdefault(item.template_id, []).append(item)

    assert set(templates) == {"mouse_modern_wireless", "mouse_standard"}
    assert templates["mouse_standard"].template_kind is TemplateKind.STANDARD
    assert templates["mouse_standard"].scope == type(
        templates["mouse_standard"].scope
    )(ScopeKind.CATEGORY, CATEGORY_ID)
    assert templates["mouse_modern_wireless"].template_kind is (
        TemplateKind.MODERN_OVERLAY
    )
    assert templates["mouse_modern_wireless"].scope == type(
        templates["mouse_modern_wireless"].scope
    )(ScopeKind.SUBTYPE, "mouse_wireless_rechargeable")
    assert all(
        item.template_id != "mouse_legacy_ball"
        for item in mouse_records.component_associations
    )

    standard_components = {
        item.component_id for item in associations["mouse_standard"]
    }
    assert standard_components >= {
        "connectivity",
        "controller_pcb",
        "enclosure",
        "power_source",
        "roller_mechanism",
        "scroll_wheel",
        "switches",
        "tracking_mechanism",
    }
    modern_components = {
        item.component_id for item in associations["mouse_modern_wireless"]
    }
    assert modern_components >= {"power_source", "wireless_module"}


def test_mouse_components_keep_materials_chemistry_and_rollers_unknown(
    mouse_records,
):
    by_id = {
        item.association_id: item for item in mouse_records.component_associations
    }
    unknown_associations = {
        item.claim_id
        for item in mouse_records.unknowns
        if item.claim_kind is UnknownClaimKind.COMPONENT_ASSOCIATION
    }
    required_unknowns = {
        "mouse_legacy_ball_roller_details_unknown",
        "mouse_modern_wireless_battery_chemistry_unknown",
        "mouse_standard_controller_pcb_material_unknown",
        "mouse_standard_controller_pcb_unknown",
        "mouse_standard_enclosure_material_unknown",
    }

    assert required_unknowns <= set(by_id)
    assert required_unknowns == unknown_associations
    assert required_unknowns == {
        item.association_id
        for item in mouse_records.component_associations
        if item.status is AssociationStatus.UNKNOWN
    }
    for association_id in required_unknowns:
        association = by_id[association_id]
        assert association.status is AssociationStatus.UNKNOWN
        assert association.evidence_level is None
        assert association.source_ids == ()
    assert by_id["mouse_legacy_ball_roller_details_unknown"].template_id == (
        "mouse_standard"
    )


def test_mouse_hazards_are_source_specific_and_conditionally_triggered(mouse_records):
    hazards = {item.hazard_id: item for item in mouse_records.hazards}

    assert set(hazards) == {
        "mouse_damaged_lithium_ion_battery",
        "mouse_leaking_primary_cell",
    }
    rechargeable = hazards["mouse_damaged_lithium_ion_battery"]
    primary = hazards["mouse_leaking_primary_cell"]
    assert rechargeable.scope == type(rechargeable.scope)(
        ScopeKind.SUBTYPE, "mouse_wireless_rechargeable"
    )
    assert primary.scope == type(primary.scope)(
        ScopeKind.SUBTYPE, "mouse_wireless_replaceable_battery"
    )
    assert rechargeable.severity is HazardSeverity.URGENT
    assert primary.severity is HazardSeverity.CAUTION
    assert "observations.issue_flags.swelling_or_battery_damage" in (
        rechargeable.trigger_observation_keys
    )
    assert "observations.issue_flags.swelling_or_battery_damage" in (
        primary.trigger_observation_keys
    )
    assert rechargeable.source_ids == ("epa_used_li_ion_2026",)
    assert primary.source_ids == ("health_canada_battery_safety_2024",)
    assert "independently establishes lithium-ion" in rechargeable.applicability
    assert "Subtype architecture alone" in primary.applicability


def test_mouse_packet_does_not_claim_release_completion(mouse_records):
    identity_unknowns = {
        item.claim_id
        for item in mouse_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
    }
    average_unknowns = {
        item.claim_id
        for item in mouse_records.unknowns
        if item.claim_kind is UnknownClaimKind.INDUSTRY_AVERAGE
    }
    subtype_unknowns = {
        item.claim_id
        for item in mouse_records.unknowns
        if item.claim_kind is UnknownClaimKind.SUBTYPE
    }

    assert len(mouse_records.identities) < 10
    assert identity_unknowns
    assert average_unknowns
    assert subtype_unknowns == {"mouse_ball_legacy"}
