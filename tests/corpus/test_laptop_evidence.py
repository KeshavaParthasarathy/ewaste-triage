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
CATEGORY_ID = "0303_laptop"
REVIEWER = "OpenAI Codex automated source review"

EXPECTED_LAPTOP_IDENTITIES = {
    "acer_aspire_5_a515_58m",
    "apple_macbook_air_m2_2022",
    "apple_powerbook_g4_12_inch",
    "asus_zenbook_14_ux3402",
    "dell_xps_13_9315",
    "framework_laptop_13_amd_7040",
    "hp_elitebook_840_g10",
    "lenovo_thinkpad_t14_gen_4",
    "microsoft_surface_laptop_5",
    "toshiba_satellite_110cs",
}

EXPECTED_REVIEWED_IDENTITIES = {
    "apple_macbook_air_m2_2022",
    "apple_powerbook_g4_12_inch",
    "asus_zenbook_14_ux3402",
    "dell_xps_13_9315",
    "framework_laptop_13_amd_7040",
    "hp_elitebook_840_g10",
    "lenovo_thinkpad_t14_gen_4",
    "microsoft_surface_laptop_5",
    "toshiba_satellite_110cs",
}

EXPECTED_UNKNOWN_IDENTITIES = {
    "acer_aspire_5_a515_58m",
}

EXPECTED_LAPTOP_SUBTYPES = {
    "laptop_gaming",
    "laptop_legacy_notebook",
    "laptop_modern_ultrabook",
    "laptop_modular",
    "laptop_two_in_one",
}

EXPECTED_CAPACITY_THRESHOLD_IDS = {
    "apple_macbook_air_m2_battery_capacity_threshold",
    "framework_laptop_13_battery_capacity_threshold",
    "lenovo_thinkpad_t14_battery_capacity_threshold",
}


@pytest.fixture(scope="module")
def laptop_records():
    return load_category_evidence_documents(REFERENCE, CATEGORY_ID)


class _LoadedLaptopComponentStore:
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


def test_laptop_development_roster_separates_reviewed_and_unknown_identities(
    laptop_records,
):
    reviewed = {item.identity_id for item in laptop_records.identities}
    unknown = {
        item.claim_id
        for item in laptop_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
    }

    assert reviewed.isdisjoint(unknown)
    assert reviewed | unknown == EXPECTED_LAPTOP_IDENTITIES
    assert reviewed == EXPECTED_REVIEWED_IDENTITIES
    assert unknown == EXPECTED_UNKNOWN_IDENTITIES
    assert len(laptop_records.identities) == 9
    assert len({item.manufacturer_id for item in laptop_records.identities}) >= 2
    acer = next(
        item
        for item in laptop_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
        and item.claim_id == "acer_aspire_5_a515_58m"
    )
    assert "a515-58m" in acer.reason.casefold()
    assert "dated" in acer.evidence_request.casefold()
    assert acer.evidence_level is None
    assert acer.source_ids == ()


def test_laptop_subtype_union_is_exact_and_battery_bearing(laptop_records):
    reviewed = {item.subtype_id: item for item in laptop_records.subtypes}
    unknown = {
        item.claim_id: item
        for item in laptop_records.unknowns
        if item.claim_kind is UnknownClaimKind.SUBTYPE
    }

    assert set(reviewed).isdisjoint(unknown)
    assert set(reviewed) | set(unknown) == EXPECTED_LAPTOP_SUBTYPES
    assert set(reviewed) == EXPECTED_LAPTOP_SUBTYPES
    assert unknown == {}
    assert all(
        item.battery_architecture is BatteryArchitecture.BATTERY_BEARING
        for item in reviewed.values()
    )
    assert reviewed["laptop_legacy_notebook"].market_state is MarketState.LEGACY
    assert reviewed["laptop_gaming"].source_ids == (
        "laptop_acer_nitro_gaming_notebooks_2019",
    )
    assert reviewed["laptop_two_in_one"].source_ids == (
        "laptop_acer_nitro_5_spin_2017",
    )


def test_laptop_sources_have_honest_dated_automated_reviews(laptop_records):
    assert laptop_records.sources
    assert {item.accessed_on for item in laptop_records.sources} == {
        date(2026, 9, 10)
    }
    assert {item.reviewed_on for item in laptop_records.sources} == {
        date(2026, 9, 10)
    }
    assert {item.reviewed_by for item in laptop_records.sources} == {REVIEWER}
    assert all(
        item.publication_or_revision_date <= item.reviewed_on
        for item in laptop_records.sources
    )
    assert all(
        urlsplit(item.canonical_url).hostname
        and not urlsplit(item.canonical_url).hostname.endswith("example.invalid")
        for item in laptop_records.sources
    )

    sources = {item.source_id: item for item in laptop_records.sources}
    assert {
        source_id: sources[source_id].publication_or_revision_date
        for source_id in {
            "laptop_apple_macbook_air_cycle_count_2026",
            "laptop_apple_powerbook_g4_12_15_service_2007",
            "laptop_acer_nitro_5_spin_2017",
            "laptop_acer_nitro_gaming_notebooks_2019",
            "laptop_framework_amd_7040_launch_2023",
            "laptop_hp_elitebook_840_g10_quickspecs_2025",
            "laptop_lenovo_t14_gen4_amd_psref_2024",
            "laptop_lenovo_t14_gen4_intel_psref_2025",
            "laptop_swiss_service_lifetime_2017",
            "laptop_toshiba_110cs_specification_1996",
        }
    } == {
        "laptop_apple_macbook_air_cycle_count_2026": date(2026, 3, 24),
        "laptop_apple_powerbook_g4_12_15_service_2007": date(2007, 8, 1),
        "laptop_acer_nitro_5_spin_2017": date(2017, 8, 21),
        "laptop_acer_nitro_gaming_notebooks_2019": date(2019, 4, 11),
        "laptop_framework_amd_7040_launch_2023": date(2023, 3, 23),
        "laptop_hp_elitebook_840_g10_quickspecs_2025": date(2025, 5, 23),
        "laptop_lenovo_t14_gen4_amd_psref_2024": date(2024, 8, 7),
        "laptop_lenovo_t14_gen4_intel_psref_2025": date(2025, 5, 14),
        "laptop_swiss_service_lifetime_2017": date(2017, 2, 24),
        "laptop_toshiba_110cs_specification_1996": date(1996, 8, 5),
    }


def test_laptop_identity_scopes_preserve_models_families_and_true_variants(
    laptop_records,
):
    identities = {item.identity_id: item for item in laptop_records.identities}

    macbook = identities["apple_macbook_air_m2_2022"]
    assert macbook.identity_kind is IdentityKind.MODEL
    assert macbook.model_id == macbook.identity_id
    assert macbook.variant_ids == ("laptop_integrated_logic_board",)
    assert macbook.model_year_from == macbook.model_year_to == 2022

    framework = identities["framework_laptop_13_amd_7040"]
    assert framework.identity_kind is IdentityKind.MODEL
    assert framework.model_id == framework.identity_id
    assert framework.variant_ids == ("laptop_modular_expansion_cards",)
    assert "61wh" not in " ".join(framework.variant_ids).casefold()

    hp = identities["hp_elitebook_840_g10"]
    assert hp.identity_kind is IdentityKind.MODEL
    assert hp.model_id == hp.identity_id
    assert hp.source_ids == (
        "laptop_hp_elitebook_840_g10_quickspecs_2025",
    )

    powerbook = identities["apple_powerbook_g4_12_inch"]
    assert powerbook.identity_kind is IdentityKind.FAMILY
    assert powerbook.family_id == powerbook.identity_id
    assert powerbook.model_id is None
    assert powerbook.model_name is None
    assert powerbook.variant_ids == ("laptop_removable_battery_bay",)
    tokens = " ".join(powerbook.distinguishing_tokens).casefold()
    assert all(
        revision in tokens for revision in ("original", "dvi", "1.33 ghz", "1.5 ghz")
    )

    toshiba = identities["toshiba_satellite_110cs"]
    assert toshiba.identity_kind is IdentityKind.MODEL
    assert toshiba.model_id == toshiba.identity_id
    assert "pa1224u-s2a" in " ".join(toshiba.distinguishing_tokens).casefold()
    assert "110ct" not in " ".join(
        (toshiba.display_name, *toshiba.aliases, *toshiba.distinguishing_tokens)
    ).casefold()


def test_laptop_capacity_targets_are_reviewed_or_real_unknowns(laptop_records):
    reviewed = {
        item.record_id: item for item in laptop_records.specific_lifecycles
    }
    unknown = {
        item.claim_id: item
        for item in laptop_records.unknowns
        if item.claim_kind is UnknownClaimKind.SPECIFIC_LIFECYCLE
    }

    assert set(reviewed).isdisjoint(unknown)
    assert set(reviewed) | set(unknown) == EXPECTED_CAPACITY_THRESHOLD_IDS
    assert set(reviewed) == {"apple_macbook_air_m2_battery_capacity_threshold"}
    assert set(unknown) == {
        "framework_laptop_13_battery_capacity_threshold",
        "lenovo_thinkpad_t14_battery_capacity_threshold",
    }

    apple = reviewed["apple_macbook_air_m2_battery_capacity_threshold"]
    assert apple.scope.kind is ScopeKind.MODEL
    assert apple.scope.id == "apple_macbook_air_m2_2022"
    assert apple.subject == "battery"
    assert apple.endpoint == "capacity_threshold"
    assert apple.endpoint_kind is LifecycleEndpointKind.CAPACITY_THRESHOLD
    assert apple.metric == "full_charge_cycles"
    assert apple.unit == "cycles"
    assert (apple.lower_bound, apple.upper_bound) == (1000.0, 1000.0)
    assert apple.evidence_level is EvidenceLevel.A
    qualification = apple.endpoint_qualification.casefold()
    assert "80%" in qualification
    assert "maximum cycle count" in qualification
    assert "designed" in qualification
    assert "guaranteed minimum" not in qualification

    framework = unknown["framework_laptop_13_battery_capacity_threshold"]
    assert "optional" in framework.reason.casefold()
    assert "61wh" in framework.reason.casefold()
    assert "configuration" in framework.evidence_request.casefold()
    lenovo = unknown["lenovo_thinkpad_t14_battery_capacity_threshold"]
    assert "rapid charge" in lenovo.reason.casefold()
    assert "cycles" in lenovo.reason.casefold()
    assert all(item.evidence_level is None for item in unknown.values())
    assert all(item.source_ids == () for item in unknown.values())


def test_laptop_broad_service_life_is_qualified_historical_iqr(laptop_records):
    assert len(laptop_records.industry_averages) == 1
    record = laptop_records.industry_averages[0]

    assert record.record_id == "laptop_industry_service_life"
    assert record.scope.kind is ScopeKind.CATEGORY
    assert record.scope.id == CATEGORY_ID
    assert record.subject == "device"
    assert record.endpoint == "service_life"
    assert record.endpoint_kind is LifecycleEndpointKind.TOTAL_LIFE
    assert record.metric == "elapsed_time"
    assert record.unit == "years"
    assert (record.lower_bound, record.upper_bound) == (3.0, 7.0)
    assert record.evidence_level is EvidenceLevel.C
    assert record.required_variant_ids == ()
    assert record.excluded_variant_ids == ()
    assert record.applicable_from is None
    assert record.applicable_to is None
    assert record.model_year_from is None
    assert record.model_year_to is None
    assert record.source_ids == ("laptop_swiss_service_lifetime_2017",)

    qualification = record.endpoint_qualification.casefold()
    assert "historical completed first-service" in qualification
    assert "approximately 3-7 years" in qualification
    assert "weighted interquartile" in qualification
    assert "graph-read" in qualification
    assert "physical" in qualification
    assert "forecast" in qualification
    assert "306" in record.population_definition
    assert "1987-2006" in record.population_definition
    assert "Switzerland" in record.population_definition
    assert "Liechtenstein" in record.population_definition
    assert "2014" in record.publication_period
    assert "2015-2016" in record.publication_period
    assert "Figure 1" in record.methodology
    assert "Table S12" in record.methodology
    assert "S-10" in record.methodology
    assert "one-year" in record.methodology
    assert "Broad estimate" in record.uncertainty
    assert "Low confidence" in record.uncertainty
    limitations = " ".join(record.limitations).casefold()
    assert "convenience" in limitations
    assert "recall" in limitations
    assert "storage" in limitations
    assert "exactly half" in limitations
    assert "reference-only" in limitations
    assert "industry_average_reference_only" in limitations


def test_laptop_component_templates_cover_required_layers(laptop_records):
    templates = {item.template_id: item for item in laptop_records.component_templates}
    associations: dict[str, list] = {}
    for item in laptop_records.component_associations:
        associations.setdefault(item.template_id, []).append(item)

    assert set(templates) == {
        "laptop_legacy_serviceable",
        "laptop_modern_integrated",
        "laptop_standard",
    }
    assert all(
        len(items) == len({item.component_id for item in items})
        for items in associations.values()
    )
    assert templates["laptop_standard"].template_kind is TemplateKind.STANDARD
    assert templates["laptop_standard"].scope == type(
        templates["laptop_standard"].scope
    )(ScopeKind.CATEGORY, CATEGORY_ID)
    assert templates["laptop_modern_integrated"].template_kind is (
        TemplateKind.MODERN_OVERLAY
    )
    assert templates["laptop_modern_integrated"].scope == type(
        templates["laptop_modern_integrated"].scope
    )(ScopeKind.MODEL, "apple_macbook_air_m2_2022")
    assert templates["laptop_legacy_serviceable"].template_kind is (
        TemplateKind.LEGACY_OVERLAY
    )
    assert templates["laptop_legacy_serviceable"].scope == type(
        templates["laptop_legacy_serviceable"].scope
    )(ScopeKind.FAMILY, "apple_powerbook_g4_12_inch")

    standard_components = {
        item.component_id for item in associations["laptop_standard"]
    }
    assert standard_components >= {
        "adapter",
        "battery",
        "cooling_assembly",
        "display_assembly",
        "enclosure",
        "input_assembly",
        "logic_board",
        "memory",
        "ports",
        "speakers",
        "storage",
    }
    modern = {item.component_id for item in associations["laptop_modern_integrated"]}
    assert modern == {
        "memory",
        "memory_serviceability",
        "storage",
        "storage_serviceability",
    }
    legacy = {item.component_id for item in associations["laptop_legacy_serviceable"]}
    assert legacy >= {"display_backlight", "memory", "storage"}


def test_laptop_resolved_layers_preserve_integrated_serviceable_and_unknown_scopes(
    laptop_records,
):
    identities = {item.identity_id: item for item in laptop_records.identities}
    resolver = EvidenceResolver(_LoadedLaptopComponentStore(laptop_records))

    macbook = resolver.resolve_components(
        _identity_scope(identities["apple_macbook_air_m2_2022"])
    )
    macbook_components = {item.component_id: item for item in macbook.components}
    assert macbook.applied_template_ids == (
        "laptop_standard",
        "laptop_modern_integrated",
    )
    assert macbook_components["memory"].status is AssociationStatus.EXACT_MODEL_CONFIRMED
    assert macbook_components["storage"].status is AssociationStatus.EXACT_MODEL_CONFIRMED
    assert (
        macbook_components["memory_serviceability"].status
        is AssociationStatus.EXACT_MODEL_CONFIRMED
    )
    assert (
        macbook_components["storage_serviceability"].status
        is AssociationStatus.EXACT_MODEL_CONFIRMED
    )
    assert macbook_components["battery_chemistry"].status is AssociationStatus.UNKNOWN

    powerbook = resolver.resolve_components(
        _identity_scope(identities["apple_powerbook_g4_12_inch"])
    )
    powerbook_components = {item.component_id: item for item in powerbook.components}
    assert powerbook.applied_template_ids == (
        "laptop_standard",
        "laptop_legacy_serviceable",
    )
    assert powerbook_components["memory"].status is AssociationStatus.LEGACY_SPECIFIC
    assert powerbook_components["storage"].status is AssociationStatus.LEGACY_SPECIFIC
    assert (
        powerbook_components["memory_serviceability"].status
        is AssociationStatus.LEGACY_SPECIFIC
    )
    assert (
        powerbook_components["storage_serviceability"].status
        is AssociationStatus.LEGACY_SPECIFIC
    )
    assert "if installed" in powerbook_components["memory"].applicability.casefold()
    assert powerbook_components["battery_chemistry"].status is AssociationStatus.UNKNOWN
    assert powerbook_components["display_backlight"].status is AssociationStatus.UNKNOWN

    for identity_id in sorted(
        set(identities)
        - {"apple_macbook_air_m2_2022", "apple_powerbook_g4_12_inch"}
    ):
        result = resolver.resolve_components(_identity_scope(identities[identity_id]))
        components = {item.component_id: item for item in result.components}
        assert components["battery_chemistry"].status is AssociationStatus.UNKNOWN
        assert components["battery_chemistry"].evidence_level is None
        assert components["battery_chemistry"].sources == ()
        assert components["memory_serviceability"].status is AssociationStatus.UNKNOWN
        assert components["storage_serviceability"].status is AssociationStatus.UNKNOWN


def test_laptop_component_unknowns_are_structured_and_covered(laptop_records):
    associations = {
        item.association_id: item for item in laptop_records.component_associations
    }
    authored_unknowns = {
        item.claim_id: item
        for item in laptop_records.unknowns
        if item.claim_kind is UnknownClaimKind.COMPONENT_ASSOCIATION
    }
    actual_unknowns = {
        item.association_id
        for item in laptop_records.component_associations
        if item.status is AssociationStatus.UNKNOWN
    }
    required = {
        "laptop_legacy_serviceable_display_backlight_unknown",
        "laptop_standard_battery_chemistry_unknown",
        "laptop_standard_display_material_unknown",
        "laptop_standard_enclosure_material_unknown",
        "laptop_standard_logic_board_material_unknown",
        "laptop_standard_memory_serviceability_unknown",
        "laptop_standard_storage_serviceability_unknown",
    }

    assert set(authored_unknowns) == actual_unknowns == required
    for association_id in required:
        association = associations[association_id]
        coverage = authored_unknowns[association_id]
        assert association.evidence_level is None
        assert association.source_ids == ()
        assert coverage.reason == association.applicability
        assert coverage.evidence_request == association.notes[0]
        assert coverage.evidence_level is None
        assert coverage.source_ids == ()


def test_laptop_hazards_keep_precautionary_and_unknown_legacy_boundaries(
    laptop_records,
):
    hazards = {item.hazard_id: item for item in laptop_records.hazards}
    hazard_unknowns = {
        item.claim_id: item
        for item in laptop_records.unknowns
        if item.claim_kind is UnknownClaimKind.HAZARD
    }

    assert set(hazards) == {"laptop_damaged_lithium_ion_battery"}
    assert set(hazard_unknowns) == {"laptop_legacy_backlight_breakage"}
    hazard = hazards["laptop_damaged_lithium_ion_battery"]
    assert hazard.scope == type(hazard.scope)(ScopeKind.CATEGORY, CATEGORY_ID)
    assert hazard.component_id == "battery"
    assert hazard.severity is HazardSeverity.URGENT
    assert hazard.trigger_observation_keys == (
        "observations.issue_flags.overheating",
        "observations.issue_flags.swelling_or_battery_damage",
    )
    assert hazard.source_ids == ("laptop_epa_used_li_ion_2026",)
    applicability = hazard.applicability.casefold()
    assert "activates precautionary guidance" in applicability
    assert "if the installed battery is lithium-ion" in applicability
    assert "do not establish chemistry" in applicability
    assert "trigger only when" not in applicability
    actions = (
        *hazard.immediate_actions,
        *hazard.follow_up_actions,
        *hazard.handling_guidance,
        *hazard.disposal_guidance,
    )
    for action in actions:
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
    legacy = hazard_unknowns["laptop_legacy_backlight_breakage"]
    assert "mercury" in legacy.reason.casefold()
    assert "undated" in legacy.reason.casefold()
    assert legacy.evidence_level is None
    assert legacy.source_ids == ()


def test_laptop_packet_does_not_claim_release_completion(laptop_records):
    unknowns_by_kind = {
        kind: {
            item.claim_id
            for item in laptop_records.unknowns
            if item.claim_kind is kind
        }
        for kind in UnknownClaimKind
    }

    assert len(laptop_records.identities) == 9
    assert len(laptop_records.specific_lifecycles) == 1
    assert len(laptop_records.industry_averages) == 1
    assert unknowns_by_kind[UnknownClaimKind.IDENTITY] == EXPECTED_UNKNOWN_IDENTITIES
    assert unknowns_by_kind[UnknownClaimKind.SUBTYPE] == set()
    assert unknowns_by_kind[UnknownClaimKind.SPECIFIC_LIFECYCLE] == {
        "framework_laptop_13_battery_capacity_threshold",
        "lenovo_thinkpad_t14_battery_capacity_threshold",
    }
    assert unknowns_by_kind[UnknownClaimKind.HAZARD] == {
        "laptop_legacy_backlight_breakage"
    }


def test_laptop_ids_are_disjoint_from_shared_and_accepted_siblings(laptop_records):
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

    laptop_ids = {
        "sources": {item.source_id for item in laptop_records.sources},
        "subtypes": {item.subtype_id for item in laptop_records.subtypes},
        "variants": {item.variant_id for item in laptop_records.variants},
        "identities": {item.identity_id for item in laptop_records.identities},
        "lifecycles": {
            item.record_id
            for item in (
                *laptop_records.specific_lifecycles,
                *laptop_records.industry_averages,
            )
        },
        "templates": {
            item.template_id for item in laptop_records.component_templates
        },
        "associations": {
            item.association_id for item in laptop_records.component_associations
        },
        "hazards": {item.hazard_id for item in laptop_records.hazards},
    }
    for namespace, ids in laptop_ids.items():
        assert ids.isdisjoint(sibling_ids[namespace]), namespace
