from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from scripts.knowledge_schema import (
    TemplateKind,
    UnknownClaimKind,
    load_category_evidence_documents,
    load_shared_evidence_documents,
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
    MarketState,
    ScopeKind,
    SourceSnapshot,
)
from server.knowledge_store import _ComponentTemplateLayer


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "reference"
CATEGORY_ID = "0306_mobile_phone"
REVIEWER = "OpenAI Codex automated source review"

EXPECTED_PHONE_IDENTITIES = {
    "apple_iphone_15",
    "apple_iphone_se_3",
    "blackberry_bold_9900",
    "fairphone_5",
    "google_pixel_8",
    "motorola_razr_40_ultra",
    "motorola_razr_v3",
    "nokia_3310_2017",
    "samsung_galaxy_s24",
    "samsung_galaxy_s5",
}

EXPECTED_PHONE_SUBTYPES = {
    "phone_feature_legacy",
    "phone_foldable_smartphone",
    "phone_keyboard_legacy",
    "phone_modular_smartphone",
    "phone_slate_smartphone",
}

EXPECTED_PHONE_VARIANTS = {
    "phone_apple_integrated_adhesive_battery",
    "phone_bold_physical_keyboard_removable_battery",
    "phone_fairphone_modular_removable_battery",
    "phone_motorola_v3_clamshell_keypad_removable_battery",
    "phone_razr40_foldable_hinge",
    "phone_s5_removable_battery",
}

EXPECTED_CAPACITY_THRESHOLD_IDS = {
    "apple_iphone_15_battery_capacity_threshold",
    "eu_phone_battery_800_cycles_80_percent",
    "fairphone_5_battery_capacity_threshold",
}

EXPECTED_PHONE_TEMPLATES = {
    "phone_bold_removable_battery",
    "phone_fairphone_modular_removable",
    "phone_galaxy_s5_removable",
    "phone_iphone_se3_integrated",
    "phone_legacy_removable_battery",
    "phone_modern_integrated",
    "phone_razr40_foldable",
    "phone_standard",
}

EXPECTED_COMPONENT_UNKNOWNS = {
    "phone_standard_battery_chemistry_unknown",
    "phone_standard_battery_construction_unknown",
    "phone_standard_display_material_unknown",
    "phone_standard_enclosure_material_unknown",
    "phone_standard_logic_board_material_unknown",
}


@pytest.fixture(scope="module")
def phone_records():
    return load_category_evidence_documents(REFERENCE, CATEGORY_ID)


class _LoadedPhoneComponentStore:
    """Adapt actual loaded rows to the resolver component-layer boundary."""

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


def test_phone_category_is_published():
    """Deleting the phone category must fail before loader-based assertions run."""

    assert (REFERENCE / "categories" / CATEGORY_ID).is_dir()


def test_phone_development_roster_is_exact_and_fully_reviewed(phone_records):
    reviewed = {item.identity_id for item in phone_records.identities}
    unknown = {
        item.claim_id
        for item in phone_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
    }

    assert reviewed.isdisjoint(unknown)
    assert reviewed | unknown == EXPECTED_PHONE_IDENTITIES
    assert reviewed == EXPECTED_PHONE_IDENTITIES
    assert unknown == set()
    assert len(phone_records.identities) == 10
    assert len({item.manufacturer_id for item in phone_records.identities}) >= 2


def test_phone_subtype_union_is_exact_and_battery_bearing(phone_records):
    reviewed = {item.subtype_id: item for item in phone_records.subtypes}
    unknown = {
        item.claim_id: item
        for item in phone_records.unknowns
        if item.claim_kind is UnknownClaimKind.SUBTYPE
    }

    assert set(reviewed).isdisjoint(unknown)
    assert set(reviewed) | set(unknown) == EXPECTED_PHONE_SUBTYPES
    assert set(reviewed) == EXPECTED_PHONE_SUBTYPES
    assert unknown == {}
    assert all(
        item.battery_architecture is BatteryArchitecture.BATTERY_BEARING
        for item in reviewed.values()
    )
    assert reviewed["phone_feature_legacy"].market_state is MarketState.LEGACY
    assert reviewed["phone_keyboard_legacy"].market_state is MarketState.LEGACY


def test_phone_sources_have_honest_dated_automated_reviews(phone_records):
    sources = {item.source_id: item for item in phone_records.sources}
    expected_dates = {
        "phone_apple_iphone_15_battery_2024": date(2024, 9, 16),
        "phone_apple_iphone_15_battery_performance_2025": date(2025, 12, 5),
        "phone_apple_iphone_15_launch_2023": date(2023, 9, 12),
        "phone_apple_iphone_se_3_battery_2024": date(2024, 9, 16),
        "phone_apple_iphone_se_3_launch_2022": date(2022, 3, 8),
        "phone_epa_used_li_ion_2026": date(2026, 3, 20),
        "phone_fairphone_5_launch_2023": date(2023, 8, 30),
        "phone_google_pixel_8_intro_2023": date(2023, 10, 4),
        "phone_hmd_nokia_3310_launch_2017": date(2017, 2, 26),
        "phone_motorola_razr_40_ultra_launch_2023": date(2023, 6, 1),
        "phone_motorola_razr_v3_launch_2004": date(2004, 7, 27),
        "phone_motorola_v3_service_manual_2004": date(2004, 7, 30),
        "phone_rim_bold_9900_launch_2011": date(2011, 5, 2),
        "phone_samsung_broken_screen_2023": date(2023, 5, 31),
        "phone_samsung_galaxy_s24_launch_2024": date(2024, 1, 18),
        "phone_samsung_galaxy_s5_launch_2014": date(2014, 2, 25),
        "phone_samsung_galaxy_s5_teardown_2014": date(2014, 4, 29),
    }

    assert set(sources) == set(expected_dates)
    assert {
        source_id: sources[source_id].publication_or_revision_date
        for source_id in expected_dates
    } == expected_dates
    assert {item.accessed_on for item in sources.values()} == {date(2026, 9, 10)}
    assert {item.reviewed_on for item in sources.values()} == {date(2026, 9, 10)}
    assert {item.reviewed_by for item in sources.values()} == {REVIEWER}
    assert all(
        item.publication_or_revision_date <= item.reviewed_on
        for item in sources.values()
    )
    assert all(
        urlsplit(item.canonical_url).hostname
        and not urlsplit(item.canonical_url).hostname.endswith("example.invalid")
        for item in sources.values()
    )
    assert all(source_id.startswith("phone_") for source_id in sources)


def test_phone_identity_scopes_preserve_models_generations_and_true_variants(
    phone_records,
):
    identities = {item.identity_id: item for item in phone_records.identities}

    assert all(item.identity_kind is IdentityKind.MODEL for item in identities.values())
    assert all(item.model_id == item.identity_id for item in identities.values())
    assert {
        item.variant_id for item in phone_records.variants
    } == EXPECTED_PHONE_VARIANTS

    assert identities["apple_iphone_15"].variant_ids == (
        "phone_apple_integrated_adhesive_battery",
    )
    assert identities["apple_iphone_se_3"].variant_ids == (
        "phone_apple_integrated_adhesive_battery",
    )
    assert identities["samsung_galaxy_s24"].variant_ids == ()
    assert identities["google_pixel_8"].variant_ids == ()
    assert identities["fairphone_5"].variant_ids == (
        "phone_fairphone_modular_removable_battery",
    )
    assert identities["motorola_razr_40_ultra"].variant_ids == (
        "phone_razr40_foldable_hinge",
    )
    assert identities["samsung_galaxy_s5"].variant_ids == (
        "phone_s5_removable_battery",
    )
    assert identities["nokia_3310_2017"].variant_ids == ()
    assert identities["motorola_razr_v3"].variant_ids == (
        "phone_motorola_v3_clamshell_keypad_removable_battery",
    )
    assert identities["blackberry_bold_9900"].variant_ids == (
        "phone_bold_physical_keyboard_removable_battery",
    )

    razr40 = identities["motorola_razr_40_ultra"]
    assert "motorola razr+" in {alias.casefold() for alias in razr40.aliases}
    assert "razr 40" not in {alias.casefold() for alias in razr40.aliases}
    assert "40 ultra" in " ".join(razr40.distinguishing_tokens).casefold()

    se3 = identities["apple_iphone_se_3"]
    assert "3rd generation" in " ".join(
        (se3.display_name, *se3.aliases, *se3.distinguishing_tokens)
    ).casefold()
    nokia = identities["nokia_3310_2017"]
    assert nokia.model_year_from == nokia.model_year_to == 2017
    assert "3g" not in " ".join(
        (nokia.display_name, *nokia.aliases, *nokia.distinguishing_tokens)
    ).casefold()
    v3 = identities["motorola_razr_v3"]
    v3_tokens = " ".join(v3.distinguishing_tokens).casefold()
    assert "gsm" in v3_tokens and "gprs" in v3_tokens
    assert all(revision not in v3_tokens for revision in ("v3i", "v3x", "v3xx"))
    bold = identities["blackberry_bold_9900"]
    assert "9930" not in " ".join(
        (bold.display_name, *bold.aliases, *bold.distinguishing_tokens)
    ).casefold()


def test_phone_identity_source_bindings_do_not_borrow_other_model_facts(
    phone_records,
):
    identities = {item.identity_id: item for item in phone_records.identities}

    assert identities["apple_iphone_15"].source_ids == (
        "phone_apple_iphone_15_battery_2024",
        "phone_apple_iphone_15_launch_2023",
    )
    assert identities["apple_iphone_se_3"].source_ids == (
        "phone_apple_iphone_se_3_battery_2024",
        "phone_apple_iphone_se_3_launch_2022",
    )
    assert identities["samsung_galaxy_s24"].source_ids == (
        "phone_samsung_galaxy_s24_launch_2024",
    )
    assert identities["google_pixel_8"].source_ids == (
        "phone_google_pixel_8_intro_2023",
    )
    assert identities["fairphone_5"].source_ids == (
        "phone_fairphone_5_launch_2023",
    )
    assert identities["motorola_razr_40_ultra"].source_ids == (
        "phone_motorola_razr_40_ultra_launch_2023",
    )
    assert identities["samsung_galaxy_s5"].source_ids == (
        "phone_samsung_galaxy_s5_launch_2014",
        "phone_samsung_galaxy_s5_teardown_2014",
    )
    assert identities["nokia_3310_2017"].source_ids == (
        "phone_hmd_nokia_3310_launch_2017",
    )
    assert identities["motorola_razr_v3"].source_ids == (
        "phone_motorola_razr_v3_launch_2004",
        "phone_motorola_v3_service_manual_2004",
    )
    assert identities["blackberry_bold_9900"].source_ids == (
        "phone_rim_bold_9900_launch_2011",
    )


def test_phone_capacity_targets_are_one_reviewed_endpoint_and_two_unknowns(
    phone_records,
):
    reviewed = {
        item.record_id: item for item in phone_records.specific_lifecycles
    }
    unknown = {
        item.claim_id: item
        for item in phone_records.unknowns
        if item.claim_kind is UnknownClaimKind.SPECIFIC_LIFECYCLE
    }

    assert set(reviewed).isdisjoint(unknown)
    assert set(reviewed) | set(unknown) == EXPECTED_CAPACITY_THRESHOLD_IDS
    assert set(reviewed) == {"apple_iphone_15_battery_capacity_threshold"}
    assert set(unknown) == {
        "eu_phone_battery_800_cycles_80_percent",
        "fairphone_5_battery_capacity_threshold",
    }

    apple = reviewed["apple_iphone_15_battery_capacity_threshold"]
    assert apple.scope.kind is ScopeKind.MODEL
    assert apple.scope.id == "apple_iphone_15"
    assert apple.subject == "battery"
    assert apple.endpoint == "capacity_threshold"
    assert apple.endpoint_kind is LifecycleEndpointKind.CAPACITY_THRESHOLD
    assert apple.metric == "full_charge_cycles"
    assert apple.unit == "cycles"
    assert (apple.lower_bound, apple.upper_bound) == (1000.0, 1000.0)
    assert apple.evidence_level is EvidenceLevel.A
    assert apple.source_ids == (
        "phone_apple_iphone_15_battery_performance_2025",
    )
    qualification = apple.endpoint_qualification.casefold()
    assert "80 percent" in qualification
    assert "original capacity" in qualification
    assert "ideal conditions" in qualification
    assert "designed" in qualification
    assert "total life" in qualification
    assert "guaranteed" in qualification

    eu = unknown["eu_phone_battery_800_cycles_80_percent"]
    eu_text = f"{eu.reason} {eu.evidence_request}".casefold()
    assert "800" in eu_text and "80" in eu_text
    assert "qualifying smartphone" in eu_text
    assert "placed on the eu market" in eu_text
    assert "2025-06-20" in eu_text
    assert "assessment date" in eu_text
    assert "conformity" in eu_text
    fairphone = unknown["fairphone_5_battery_capacity_threshold"]
    fairphone_text = f"{fairphone.reason} {fairphone.evidence_request}".casefold()
    assert "1,300" in fairphone_text
    assert "4,080 mah" in fairphone_text
    assert "publication" in fairphone_text
    assert "configuration" in fairphone_text
    assert all(item.evidence_level is None for item in unknown.values())
    assert all(item.source_ids == () for item in unknown.values())


def test_phone_broad_service_life_remains_an_honest_unknown(phone_records):
    unknown = {
        item.claim_id: item
        for item in phone_records.unknowns
        if item.claim_kind is UnknownClaimKind.INDUSTRY_AVERAGE
    }

    assert phone_records.industry_averages == ()
    assert set(unknown) == {"phone_industry_service_life"}
    record = unknown["phone_industry_service_life"]
    text = f"{record.reason} {record.evidence_request}".casefold()
    assert "completed first" in text
    assert "748" in text and "784" in text
    assert "weighted" in text
    assert "publication" in text
    assert "service" in text
    assert record.evidence_level is None
    assert record.source_ids == ()


def test_phone_component_templates_cover_standard_and_exact_overlays(phone_records):
    templates = {item.template_id: item for item in phone_records.component_templates}
    associations: dict[str, list] = {}
    for item in phone_records.component_associations:
        associations.setdefault(item.template_id, []).append(item)

    assert set(templates) == EXPECTED_PHONE_TEMPLATES
    assert all(
        len(items) == len({item.component_id for item in items})
        for items in associations.values()
    )
    standard = templates["phone_standard"]
    assert standard.template_kind is TemplateKind.STANDARD
    assert standard.scope == type(standard.scope)(ScopeKind.CATEGORY, CATEGORY_ID)
    assert templates["phone_modern_integrated"].scope == type(standard.scope)(
        ScopeKind.MODEL, "apple_iphone_15"
    )
    assert templates["phone_legacy_removable_battery"].template_kind is (
        TemplateKind.LEGACY_OVERLAY
    )
    assert templates["phone_legacy_removable_battery"].scope == type(standard.scope)(
        ScopeKind.MODEL, "motorola_razr_v3"
    )

    standard_components = {
        item.component_id for item in associations["phone_standard"]
    }
    assert standard_components >= {
        "battery",
        "battery_chemistry",
        "battery_construction",
        "camera",
        "display_assembly",
        "enclosure",
        "logic_board",
        "microphones",
        "ports",
        "speakers",
        "storage",
        "vibration_device",
    }
    assert {
        item.component_id for item in associations["phone_razr40_foldable"]
    } == {"display_assembly", "hinge"}
    assert {
        item.component_id for item in associations["phone_bold_removable_battery"]
    } == {"battery_construction", "physical_keyboard"}


def test_phone_resolved_components_preserve_construction_and_chemistry_gaps(
    phone_records,
):
    identities = {item.identity_id: item for item in phone_records.identities}
    resolver = EvidenceResolver(_LoadedPhoneComponentStore(phone_records))

    construction_reviewed = {
        "apple_iphone_15",
        "apple_iphone_se_3",
        "blackberry_bold_9900",
        "fairphone_5",
        "motorola_razr_v3",
        "samsung_galaxy_s5",
    }
    construction_unknown = EXPECTED_PHONE_IDENTITIES - construction_reviewed

    for identity_id in sorted(EXPECTED_PHONE_IDENTITIES):
        result = resolver.resolve_components(_identity_scope(identities[identity_id]))
        components = {item.component_id: item for item in result.components}
        assert result.applied_template_ids[0] == "phone_standard"
        if identity_id in construction_reviewed:
            assert components["battery_construction"].status is not (
                AssociationStatus.UNKNOWN
            )
            assert components["battery_construction"].sources
        else:
            assert components["battery_construction"].status is (
                AssociationStatus.UNKNOWN
            )
            assert components["battery_construction"].evidence_level is None
            assert components["battery_construction"].sources == ()

        assert components["battery_chemistry"].status is AssociationStatus.UNKNOWN
        assert components["battery_chemistry"].evidence_level is None
        assert components["battery_chemistry"].sources == ()

    assert construction_unknown == {
        "google_pixel_8",
        "motorola_razr_40_ultra",
        "nokia_3310_2017",
        "samsung_galaxy_s24",
    }

    v3 = resolver.resolve_components(_identity_scope(identities["motorola_razr_v3"]))
    v3_components = {item.component_id: item for item in v3.components}
    assert v3_components["original_battery_chemistry"].status is (
        AssociationStatus.LEGACY_SPECIFIC
    )
    assert "original" in v3_components[
        "original_battery_chemistry"
    ].applicability.casefold()
    assert v3_components["battery_chemistry"].status is AssociationStatus.UNKNOWN


def test_phone_overlay_semantics_do_not_authorize_user_disassembly(phone_records):
    by_id = {
        item.association_id: item for item in phone_records.component_associations
    }

    for association_id in {
        "phone_modern_integrated_battery_construction",
        "phone_iphone_se3_integrated_battery_construction",
    }:
        association = by_id[association_id]
        text = f"{association.applicability} {' '.join(association.notes)}".casefold()
        assert "adhesive" in text
        assert "technician" in text
        assert "user-removable" in text

    fairphone = by_id["phone_fairphone_modular_removable_battery_construction"]
    fairphone_text = f"{fairphone.applicability} {' '.join(fairphone.notes)}".casefold()
    assert "modular" in fairphone_text
    assert "replaceable" in fairphone_text
    assert "current installed chemistry" in fairphone_text

    s5 = by_id["phone_galaxy_s5_removable_battery_construction"]
    assert "changeable" in s5.applicability.casefold()
    assert "chemistry" in " ".join(s5.notes).casefold()


def test_phone_component_unknowns_are_structured_and_covered(phone_records):
    associations = {
        item.association_id: item for item in phone_records.component_associations
    }
    authored_unknowns = {
        item.claim_id: item
        for item in phone_records.unknowns
        if item.claim_kind is UnknownClaimKind.COMPONENT_ASSOCIATION
    }
    actual_unknowns = {
        item.association_id
        for item in phone_records.component_associations
        if item.status is AssociationStatus.UNKNOWN
    }

    assert set(authored_unknowns) == actual_unknowns == EXPECTED_COMPONENT_UNKNOWNS
    for association_id in EXPECTED_COMPONENT_UNKNOWNS:
        association = associations[association_id]
        coverage = authored_unknowns[association_id]
        assert association.evidence_level is None
        assert association.source_ids == ()
        assert coverage.reason == association.applicability
        assert coverage.evidence_request == association.notes[0]
        assert coverage.evidence_level is None
        assert coverage.source_ids == ()


def test_phone_hazards_are_precautionary_and_condition_qualified(phone_records):
    hazards = {item.hazard_id: item for item in phone_records.hazards}

    assert set(hazards) == {
        "phone_broken_exterior_handling",
        "phone_damaged_lithium_ion_battery",
    }
    battery = hazards["phone_damaged_lithium_ion_battery"]
    assert battery.scope == type(battery.scope)(ScopeKind.CATEGORY, CATEGORY_ID)
    assert battery.component_id == "battery"
    assert battery.severity is HazardSeverity.URGENT
    assert battery.trigger_observation_keys == (
        "observations.issue_flags.overheating",
        "observations.issue_flags.swelling_or_battery_damage",
    )
    assert battery.source_ids == ("phone_epa_used_li_ion_2026",)
    battery_applicability = battery.applicability.casefold()
    assert "activates precautionary guidance" in battery_applicability
    assert "if the installed battery is lithium-ion" in battery_applicability
    assert "do not establish chemistry" in battery_applicability
    assert "trigger only when" not in battery_applicability
    battery_actions = (
        *battery.immediate_actions,
        *battery.follow_up_actions,
        *battery.handling_guidance,
        *battery.disposal_guidance,
    )
    for action in battery_actions:
        if "lithium-ion" in action.casefold():
            assert action.casefold().startswith("if ")

    exterior = hazards["phone_broken_exterior_handling"]
    assert exterior.scope == type(exterior.scope)(ScopeKind.CATEGORY, CATEGORY_ID)
    assert exterior.component_id == "enclosure"
    assert exterior.severity is HazardSeverity.CAUTION
    assert exterior.evidence_level is EvidenceLevel.D
    assert exterior.trigger_observation_keys == (
        "observations.issue_flags.swelling_or_battery_damage",
    )
    assert exterior.source_ids == ("phone_samsung_broken_screen_2023",)
    exterior_text = exterior.applicability.casefold()
    assert "activates precautionary" in exterior_text
    assert "does not establish" in exterior_text
    assert "broken exterior" in exterior_text
    assert "structured" in exterior_text
    exterior_actions = (
        *exterior.immediate_actions,
        *exterior.follow_up_actions,
        *exterior.handling_guidance,
        *exterior.disposal_guidance,
    )
    for action in exterior_actions:
        if any(term in action.casefold() for term in ("broken", "cracked", "shard")):
            assert action.casefold().startswith("if ")


def test_phone_packet_exposes_actual_release_gaps(phone_records):
    unknowns_by_kind = {
        kind: {
            item.claim_id
            for item in phone_records.unknowns
            if item.claim_kind is kind
        }
        for kind in UnknownClaimKind
    }

    assert len(phone_records.identities) == 10
    assert len(phone_records.specific_lifecycles) == 1
    assert len(phone_records.industry_averages) == 0
    assert unknowns_by_kind[UnknownClaimKind.IDENTITY] == set()
    assert unknowns_by_kind[UnknownClaimKind.SUBTYPE] == set()
    assert unknowns_by_kind[UnknownClaimKind.SPECIFIC_LIFECYCLE] == {
        "eu_phone_battery_800_cycles_80_percent",
        "fairphone_5_battery_capacity_threshold",
    }
    assert unknowns_by_kind[UnknownClaimKind.INDUSTRY_AVERAGE] == {
        "phone_industry_service_life"
    }
    assert unknowns_by_kind[UnknownClaimKind.COMPONENT_ASSOCIATION] == (
        EXPECTED_COMPONENT_UNKNOWNS
    )
    assert unknowns_by_kind[UnknownClaimKind.HAZARD] == set()


def test_phone_ids_are_disjoint_from_shared_and_accepted_siblings(phone_records):
    shared = load_shared_evidence_documents(REFERENCE)
    sibling_ids = {
        "sources": {item.source_id for item in shared.sources},
        "subtypes": set(),
        "variants": set(),
        "identities": set(),
        "lifecycles": set(),
        "templates": set(),
        "associations": set(),
        "hazards": set(),
    }
    for category_dir in sorted((REFERENCE / "categories").iterdir()):
        if not category_dir.is_dir() or category_dir.name == CATEGORY_ID:
            continue
        records = load_category_evidence_documents(REFERENCE, category_dir.name)
        sibling_ids["sources"].update(item.source_id for item in records.sources)
        sibling_ids["subtypes"].update(item.subtype_id for item in records.subtypes)
        sibling_ids["variants"].update(item.variant_id for item in records.variants)
        sibling_ids["identities"].update(item.identity_id for item in records.identities)
        sibling_ids["lifecycles"].update(
            item.record_id
            for item in (*records.specific_lifecycles, *records.industry_averages)
        )
        sibling_ids["templates"].update(
            item.template_id for item in records.component_templates
        )
        sibling_ids["associations"].update(
            item.association_id for item in records.component_associations
        )
        sibling_ids["hazards"].update(item.hazard_id for item in records.hazards)

    phone_ids = {
        "sources": {item.source_id for item in phone_records.sources},
        "subtypes": {item.subtype_id for item in phone_records.subtypes},
        "variants": {item.variant_id for item in phone_records.variants},
        "identities": {item.identity_id for item in phone_records.identities},
        "lifecycles": {
            item.record_id
            for item in (
                *phone_records.specific_lifecycles,
                *phone_records.industry_averages,
            )
        },
        "templates": {
            item.template_id for item in phone_records.component_templates
        },
        "associations": {
            item.association_id for item in phone_records.component_associations
        },
        "hazards": {item.hazard_id for item in phone_records.hazards},
    }
    for namespace, ids in phone_ids.items():
        assert ids.isdisjoint(sibling_ids[namespace]), namespace
