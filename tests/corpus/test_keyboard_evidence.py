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
from server.evidence_resolver import EvidenceResolver
from server.evidence_types import (
    AssociationStatus,
    BatteryArchitecture,
    CanonicalIdentityScope,
    ComponentAssociationSnapshot,
    EvidenceLevel,
    HazardSeverity,
    IdentityKind,
    LifecycleEndpointKind,
    ScopeKind,
    SourceSnapshot,
)
from server.knowledge_store import _ComponentTemplateLayer


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


class _LoadedKeyboardComponentStore:
    """Adapt loaded corpus records to the resolver's component-layer boundary."""

    def __init__(self, records):
        self._records = records

    def component_layers(self, scope):
        scope_ids = {
            ScopeKind.CATEGORY: scope.category_id,
            ScopeKind.SUBTYPE: scope.subtype_id,
            ScopeKind.FAMILY: scope.family_id,
            ScopeKind.MODEL: scope.model_id,
        }
        scope_order = {
            ScopeKind.CATEGORY: 0,
            ScopeKind.SUBTYPE: 1,
            ScopeKind.FAMILY: 2,
            ScopeKind.MODEL: 3,
        }
        definitions = {
            item.component_id: item for item in self._records.component_definitions
        }
        sources = {
            item.source_id: SourceSnapshot(
                item.source_id,
                item.title,
                item.publisher,
                item.canonical_url,
                item.publication_or_revision_date,
                item.accessed_on,
                item.license_or_use_basis,
                item.reviewed_by,
                item.reviewed_on,
            )
            for item in self._records.sources
        }
        associations_by_template = {}
        for item in self._records.component_associations:
            associations_by_template.setdefault(item.template_id, []).append(item)

        selected = sorted(
            (
                template
                for template in self._records.component_templates
                if scope_ids[template.scope.kind] == template.scope.id
            ),
            key=lambda template: (
                scope_order[template.scope.kind],
                template.application_order,
                template.template_id,
            ),
        )
        layers = []
        for template in selected:
            associations = tuple(
                ComponentAssociationSnapshot(
                    item.association_id,
                    item.template_id,
                    item.component_id,
                    definitions[item.component_id].display_name,
                    item.status,
                    template.scope.kind,
                    template.scope.id,
                    item.applicability,
                    item.notes,
                    item.evidence_level,
                    tuple(sources[source_id] for source_id in item.source_ids),
                )
                for item in sorted(
                    associations_by_template[template.template_id],
                    key=lambda association: association.position,
                )
            )
            layers.append(_ComponentTemplateLayer(template.template_id, associations))
        return tuple(layers)


def _identity_scope(identity):
    return CanonicalIdentityScope(
        category_id=identity.category_id,
        subtype_id=identity.subtype_id,
        family_id=identity.family_id,
        model_id=identity.model_id,
        variant_ids=identity.variant_ids,
    )


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
    assert set(sources) == {
        "ibm_model_m_buckling_spring_2026",
        "keyboard_health_canada_battery_safety_2024",
        "keyboard_osha_small_lithium_devices_2019",
        "logitech_k780_technical_specifications_2025",
        "logitech_mx_keys_s_specification_2023",
        "razer_blackwidow_v4_launch_2023",
        "razer_blackwidow_v4_pro_launch_2023",
        "razer_blackwidow_v4_support_2026",
    }
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
    osha = sources["keyboard_osha_small_lithium_devices_2019"]
    assert osha.title == (
        "Preventing Fire and/or Explosion Injury from Small and Wearable "
        "Lithium Battery Powered Devices"
    )
    assert osha.publisher == "Occupational Safety and Health Administration"
    assert osha.canonical_url == "https://obis.osha.gov/dts/shib/shib011819.html"
    assert osha.publication_or_revision_date == date(2019, 6, 20)
    osha_basis = osha.license_or_use_basis.casefold()
    assert "first-party html" in osha_basis
    assert "workplace" in osha_basis
    assert "advisory" in osha_basis
    assert "not" in osha_basis and "regulation" in osha_basis
    assert "chemistry" in osha_basis
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

    assert len(keyboard_records.component_associations) == 18
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


def test_keyboard_k780_resolves_structured_battery_chemistry_unknown(
    keyboard_records,
):
    identities = {item.identity_id: item for item in keyboard_records.identities}
    resolver = EvidenceResolver(_LoadedKeyboardComponentStore(keyboard_records))

    k780 = resolver.resolve_components(_identity_scope(identities["logitech_k780"]))
    k780_components = {item.component_id: item for item in k780.components}
    assert k780.applied_template_ids == ("keyboard_standard",)
    assert "battery_chemistry" in k780_components

    k780_chemistry = k780_components["battery_chemistry"]
    assert k780_chemistry.association_id == (
        "keyboard_standard_battery_chemistry_unknown"
    )
    assert k780_chemistry.status is AssociationStatus.UNKNOWN
    assert k780_chemistry.evidence_level is None
    assert k780_chemistry.sources == ()
    applicability = k780_chemistry.applicability.casefold()
    assert "battery-bearing" in applicability
    assert "does not assert" in applicability
    assert "battery-free" in applicability

    coverage = next(
        item
        for item in keyboard_records.unknowns
        if item.claim_kind is UnknownClaimKind.COMPONENT_ASSOCIATION
        and item.claim_id == k780_chemistry.association_id
    )
    assert coverage.reason == k780_chemistry.applicability
    assert coverage.evidence_request == k780_chemistry.notes[0]
    assert coverage.evidence_level is None
    assert coverage.source_ids == ()

    mx_keys = resolver.resolve_components(
        _identity_scope(identities["logitech_mx_keys_s"])
    )
    mx_components = {item.component_id: item for item in mx_keys.components}
    assert mx_keys.applied_template_ids == (
        "keyboard_standard",
        "keyboard_modern_wireless",
    )
    assert mx_components["battery_chemistry"].association_id == (
        "keyboard_modern_wireless_battery_chemistry_unknown"
    )
    assert mx_components["battery_chemistry"].status is AssociationStatus.UNKNOWN
    assert mx_components["battery_chemistry"].evidence_level is None
    assert mx_components["battery_chemistry"].sources == ()


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
        "keyboard_standard_battery_chemistry_unknown",
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
    assert rechargeable.source_ids == (
        "epa_used_li_ion_2026",
        "keyboard_osha_small_lithium_devices_2019",
    )
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


def test_keyboard_damaged_battery_actions_match_imported_source_scope(
    keyboard_records,
):
    hazard = next(
        item
        for item in keyboard_records.hazards
        if item.hazard_id == "keyboard_damaged_lithium_ion_battery"
    )
    immediate_text = " ".join(hazard.immediate_actions).casefold()
    all_actions = " ".join(
        (
            *hazard.immediate_actions,
            *hazard.follow_up_actions,
            *hazard.handling_guidance,
            *hazard.disposal_guidance,
        )
    ).casefold()

    assert "remove" in immediate_text and "from service" in immediate_text
    assert "away from flammable materials" in immediate_text
    assert "physical damage" in immediate_text
    assert all(
        unsupported not in all_actions
        for unsupported in (
            "bending",
            "fire resistant",
            "fire-resistant",
            "prompt transfer",
            "sand",
            "stop using and charging",
        )
    )


def test_keyboard_damaged_battery_destinations_are_locally_qualified(
    keyboard_records,
):
    hazard = next(
        item
        for item in keyboard_records.hazards
        if item.hazard_id == "keyboard_damaged_lithium_ion_battery"
    )
    destination_actions = tuple(
        action
        for action in (
            *hazard.immediate_actions,
            *hazard.follow_up_actions,
            *hazard.handling_guidance,
            *hazard.disposal_guidance,
        )
        if any(
            marker in action.casefold()
            for marker in ("destination", "collection point", "recycler", "program")
        )
    )

    assert destination_actions
    for action in destination_actions:
        action_text = action.casefold()
        assert "damaged" in action_text
        assert "confirm" in action_text
        assert "accept" in action_text
        assert "instructions" in action_text
    assert any(
        "manufacturer" in action.casefold()
        and "handling" in action.casefold()
        and "damaged" in action.casefold()
        for action in hazard.follow_up_actions
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
    assert len(keyboard_records.unknowns) == 18
