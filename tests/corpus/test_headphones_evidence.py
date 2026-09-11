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
CATEGORY_ID = "0401_headphones"
REVIEWER = "OpenAI Codex automated source review"

EXPECTED_HEADPHONE_IDENTITIES = {
    "apple_airpods_pro_2_usb_c",
    "audio_technica_ath_m50x",
    "beats_studio_pro",
    "bose_quietcomfort_ultra_headphones",
    "jabra_elite_8_active",
    "koss_porta_pro",
    "logitech_g_pro_x_wired",
    "sennheiser_hd_600",
    "sony_mdr_7506",
    "sony_wh_1000xm5",
}

EXPECTED_REVIEWED_IDENTITIES = {
    "apple_airpods_pro_2_usb_c",
    "beats_studio_pro",
    "bose_quietcomfort_ultra_headphones",
    "jabra_elite_8_active",
    "sony_wh_1000xm5",
}

EXPECTED_UNKNOWN_IDENTITIES = EXPECTED_HEADPHONE_IDENTITIES - (
    EXPECTED_REVIEWED_IDENTITIES
)

EXPECTED_HEADPHONE_SUBTYPES = {
    "headphones_true_wireless",
    "headphones_wired_on_ear_legacy",
    "headphones_wired_over_ear",
    "headphones_wireless_over_ear",
}

EXPECTED_REVIEWED_SUBTYPES = {
    "headphones_true_wireless",
    "headphones_wireless_over_ear",
}

EXPECTED_UNKNOWN_SUBTYPES = EXPECTED_HEADPHONE_SUBTYPES - (
    EXPECTED_REVIEWED_SUBTYPES
)

EXPECTED_RUNTIME_ENDPOINTS = {
    "airpods_pro_2_listening_runtime",
    "bose_quietcomfort_ultra_charge_runtime",
    "sony_wh_1000xm5_charge_runtime",
}

EXPECTED_REVIEWED_RUNTIME_ENDPOINTS = {
    "bose_quietcomfort_ultra_charge_runtime",
    "sony_wh_1000xm5_charge_runtime",
}

EXPECTED_SOURCE_IDS = {
    "headphones_apple_airpods_pro_2_usb_c_launch_2023",
    "headphones_beats_studio_pro_launch_2023",
    "headphones_bose_quietcomfort_ultra_launch_2023",
    "headphones_epa_used_li_ion_2026",
    "headphones_jabra_elite_8_active_launch_2023",
    "headphones_osha_small_lithium_devices_2019",
    "headphones_sony_wh_1000xm5_help_guide_2025",
    "headphones_sony_wh_1000xm5_launch_2022",
    "headphones_swiss_service_lifetime_2017",
}

EXPECTED_COMPONENT_UNKNOWNS = {
    "headphones_modern_wireless_circuit_board_material_unknown",
    "headphones_modern_wireless_device_battery_chemistry_unknown",
    "headphones_standard_audio_driver_material_unknown",
    "headphones_standard_enclosure_material_unknown",
    "headphones_true_wireless_charging_case_battery_chemistry_unknown",
    "headphones_true_wireless_charging_case_material_unknown",
    "headphones_true_wireless_circuit_board_material_unknown",
    "headphones_true_wireless_device_battery_chemistry_unknown",
}


@pytest.fixture(scope="module")
def headphone_records():
    return load_category_evidence_documents(REFERENCE, CATEGORY_ID)


class _LoadedHeadphoneComponentStore:
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


def test_headphone_development_roster_separates_reviewed_and_unknown_identities(
    headphone_records,
):
    reviewed = {item.identity_id for item in headphone_records.identities}
    unknown = {
        item.claim_id
        for item in headphone_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
    }

    assert reviewed.isdisjoint(unknown)
    assert reviewed | unknown == EXPECTED_HEADPHONE_IDENTITIES
    assert reviewed == EXPECTED_REVIEWED_IDENTITIES
    assert unknown == EXPECTED_UNKNOWN_IDENTITIES
    assert len(headphone_records.identities) == 5

    unknowns = {
        item.claim_id: item
        for item in headphone_records.unknowns
        if item.claim_kind is UnknownClaimKind.IDENTITY
    }
    assert "battery" in unknowns["sennheiser_hd_600"].reason.casefold()
    assert "battery" in unknowns["audio_technica_ath_m50x"].reason.casefold()
    assert "battery" in unknowns["logitech_g_pro_x_wired"].reason.casefold()
    assert "classic" in unknowns["koss_porta_pro"].reason.casefold()
    assert "date" in unknowns["sony_mdr_7506"].reason.casefold()
    assert all(item.evidence_level is None for item in unknowns.values())
    assert all(item.source_ids == () for item in unknowns.values())


def test_headphone_subtype_union_preserves_battery_free_evidence_gaps(
    headphone_records,
):
    reviewed = {item.subtype_id: item for item in headphone_records.subtypes}
    unknown = {
        item.claim_id: item
        for item in headphone_records.unknowns
        if item.claim_kind is UnknownClaimKind.SUBTYPE
    }

    assert set(reviewed).isdisjoint(unknown)
    assert set(reviewed) | set(unknown) == EXPECTED_HEADPHONE_SUBTYPES
    assert set(reviewed) == EXPECTED_REVIEWED_SUBTYPES
    assert set(unknown) == EXPECTED_UNKNOWN_SUBTYPES
    assert all(
        item.market_state is MarketState.CURRENT for item in reviewed.values()
    )
    assert all(
        item.battery_architecture is BatteryArchitecture.BATTERY_BEARING
        for item in reviewed.values()
    )
    assert all(item.evidence_level is EvidenceLevel.B for item in reviewed.values())

    legacy = unknown["headphones_wired_on_ear_legacy"]
    assert "utility" in legacy.reason.casefold()
    assert "different" in legacy.reason.casefold()
    assert "market" in legacy.evidence_request.casefold()
    assert "battery" in legacy.evidence_request.casefold()
    wired = unknown["headphones_wired_over_ear"]
    assert "battery" in wired.reason.casefold()
    assert "dated" in wired.evidence_request.casefold()


def test_headphone_variants_are_whole_identity_battery_bearing_facts(
    headphone_records,
):
    variants = {item.variant_id: item for item in headphone_records.variants}
    identities = {item.identity_id: item for item in headphone_records.identities}

    assert set(variants) == {
        "headphones_true_wireless_with_charging_case",
        "headphones_wireless_rechargeable",
    }
    assert all(
        item.battery_architecture is BatteryArchitecture.BATTERY_BEARING
        for item in variants.values()
    )
    assert all(item.evidence_level is EvidenceLevel.B for item in variants.values())
    assert variants["headphones_true_wireless_with_charging_case"].subtype_id == (
        "headphones_true_wireless"
    )
    assert variants["headphones_wireless_rechargeable"].subtype_id == (
        "headphones_wireless_over_ear"
    )

    for identity_id in {"apple_airpods_pro_2_usb_c", "jabra_elite_8_active"}:
        assert identities[identity_id].variant_ids == (
            "headphones_true_wireless_with_charging_case",
        )
    for identity_id in {
        "beats_studio_pro",
        "bose_quietcomfort_ultra_headphones",
        "sony_wh_1000xm5",
    }:
        assert identities[identity_id].variant_ids == (
            "headphones_wireless_rechargeable",
        )
    assert not any(
        item.battery_architecture is BatteryArchitecture.BATTERY_FREE
        for item in variants.values()
    )
    assert not any(
        item.claim_kind is UnknownClaimKind.VARIANT
        for item in headphone_records.unknowns
    )


def test_headphone_sources_have_bounded_dated_automated_reviews(headphone_records):
    sources = {item.source_id: item for item in headphone_records.sources}

    assert set(sources) == EXPECTED_SOURCE_IDS
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

    expected_dates = {
        "headphones_apple_airpods_pro_2_usb_c_launch_2023": date(2023, 9, 12),
        "headphones_beats_studio_pro_launch_2023": date(2023, 7, 19),
        "headphones_bose_quietcomfort_ultra_launch_2023": date(2023, 9, 14),
        "headphones_epa_used_li_ion_2026": date(2026, 3, 20),
        "headphones_jabra_elite_8_active_launch_2023": date(2023, 8, 31),
        "headphones_osha_small_lithium_devices_2019": date(2019, 6, 20),
        "headphones_sony_wh_1000xm5_help_guide_2025": date(2025, 5, 25),
        "headphones_sony_wh_1000xm5_launch_2022": date(2022, 5, 12),
        "headphones_swiss_service_lifetime_2017": date(2017, 2, 24),
    }
    assert {
        source_id: source.publication_or_revision_date
        for source_id, source in sources.items()
    } == expected_dates
    assert all(
        any(
            basis in item.license_or_use_basis.casefold()
            for basis in (
                "factual paraphrase",
                "independently worded factual findings",
            )
        )
        for item in sources.values()
    )

    swiss = sources["headphones_swiss_service_lifetime_2017"]
    assert swiss.canonical_url == "https://doi.org/10.1111/jiec.12551"
    swiss_basis = swiss.license_or_use_basis.casefold()
    assert "accepted manuscript" in swiss_basis
    assert "supporting information s1" in swiss_basis
    assert "redistribut" in swiss_basis

    osha = sources["headphones_osha_small_lithium_devices_2019"]
    assert osha.canonical_url == "https://obis.osha.gov/dts/shib/shib011819.html"
    osha_basis = osha.license_or_use_basis.casefold()
    assert "workplace" in osha_basis
    assert "advisory" in osha_basis
    assert "not a regulation" in osha_basis
    assert "chemistry" in osha_basis


def test_headphone_identity_scopes_are_exact_current_models(headphone_records):
    identities = {item.identity_id: item for item in headphone_records.identities}
    expected_years = {
        "apple_airpods_pro_2_usb_c": 2023,
        "beats_studio_pro": 2023,
        "bose_quietcomfort_ultra_headphones": 2023,
        "jabra_elite_8_active": 2023,
        "sony_wh_1000xm5": 2022,
    }

    assert all(item.identity_kind is IdentityKind.MODEL for item in identities.values())
    assert all(item.model_id == item.identity_id for item in identities.values())
    assert all(item.market_state is MarketState.CURRENT for item in identities.values())
    assert all(
        item.battery_architecture is BatteryArchitecture.BATTERY_BEARING
        for item in identities.values()
    )
    assert all(item.evidence_level is EvidenceLevel.A for item in identities.values())
    for identity_id, model_year in expected_years.items():
        identity = identities[identity_id]
        assert identity.model_year_from == identity.model_year_to == model_year
        assert len(identity.source_ids) == 1

    airpods = identities["apple_airpods_pro_2_usb_c"]
    assert airpods.source_ids == (
        "headphones_apple_airpods_pro_2_usb_c_launch_2023",
    )
    assert "usb-c" in " ".join(
        (airpods.display_name, *airpods.aliases, *airpods.distinguishing_tokens)
    ).casefold()
    bose = identities["bose_quietcomfort_ultra_headphones"]
    assert "earbuds" not in " ".join(
        (bose.display_name, *bose.aliases, *bose.distinguishing_tokens)
    ).casefold()
    jabra = identities["jabra_elite_8_active"]
    assert "gen 2" not in " ".join(
        (jabra.display_name, *jabra.aliases, *jabra.distinguishing_tokens)
    ).casefold()


def test_headphone_runtime_union_is_exact_and_keeps_airpods_unknown(
    headphone_records,
):
    reviewed = {
        item.record_id: item for item in headphone_records.specific_lifecycles
    }
    unknown = {
        item.claim_id: item
        for item in headphone_records.unknowns
        if item.claim_kind is UnknownClaimKind.SPECIFIC_LIFECYCLE
    }

    assert set(reviewed).isdisjoint(unknown)
    assert set(reviewed) | set(unknown) == EXPECTED_RUNTIME_ENDPOINTS
    assert set(reviewed) == EXPECTED_REVIEWED_RUNTIME_ENDPOINTS
    assert set(unknown) == {"airpods_pro_2_listening_runtime"}
    assert len(headphone_records.specific_lifecycles) == 2

    for record in reviewed.values():
        assert record.scope.kind is ScopeKind.MODEL
        assert record.subject == "device_battery"
        assert record.endpoint == "charge_runtime"
        assert record.endpoint_kind is LifecycleEndpointKind.OPERATING_ENDURANCE
        assert record.metric == "elapsed_time"
        assert record.unit == "hours"
        assert record.evidence_level is EvidenceLevel.A
        assert record.applicable_from is None
        assert record.applicable_to is None
        assert record.excluded_variant_ids == ()
        assert "service life" in record.endpoint_qualification.casefold()

    airpods = unknown["airpods_pro_2_listening_runtime"]
    assert "six" in airpods.reason.casefold() or "6" in airpods.reason.casefold()
    assert "date" in airpods.reason.casefold()
    assert "usb-c" in airpods.evidence_request.casefold()
    assert airpods.evidence_level is None
    assert airpods.source_ids == ()


def test_sony_and_bose_runtime_modes_are_not_blended(headphone_records):
    records = {
        item.record_id: item for item in headphone_records.specific_lifecycles
    }
    sony = records["sony_wh_1000xm5_charge_runtime"]
    bose = records["bose_quietcomfort_ultra_charge_runtime"]

    assert sony.scope.id == "sony_wh_1000xm5"
    assert (sony.lower_bound, sony.upper_bound) == (30.0, 30.0)
    assert sony.required_variant_ids == ("headphones_wireless_rechargeable",)
    assert sony.source_ids == (
        "headphones_sony_wh_1000xm5_help_guide_2025",
    )
    sony_text = " ".join((sony.endpoint_qualification, *sony.assumptions)).casefold()
    assert "maximum" in sony_text
    assert "fully charged" in sony_text
    assert "bluetooth" in sony_text
    assert "aac" in sony_text
    assert "noise cancel" in sony_text and "on" in sony_text
    assert "communication" in sony_text
    assert "quick-charge" in sony_text
    assert "not a guaranteed minimum" in sony_text

    assert bose.scope.id == "bose_quietcomfort_ultra_headphones"
    assert (bose.lower_bound, bose.upper_bound) == (24.0, 24.0)
    assert bose.required_variant_ids == ("headphones_wireless_rechargeable",)
    assert bose.source_ids == (
        "headphones_bose_quietcomfort_ultra_launch_2023",
    )
    bose_text = " ".join((bose.endpoint_qualification, *bose.assumptions)).casefold()
    assert "up to" in bose_text
    assert "immersive audio" in bose_text and "off" in bose_text
    assert "original 2023" in bose_text
    assert "earbuds" in bose_text
    assert "second-generation" in bose_text or "second generation" in bose_text
    assert "sparse" in bose_text
    assert "not a guaranteed minimum" in bose_text


def test_headphone_broad_service_life_is_qualified_historical_iqr(
    headphone_records,
):
    assert len(headphone_records.industry_averages) == 1
    record = headphone_records.industry_averages[0]

    assert record.record_id == "headphones_industry_service_life"
    assert record.scope.kind is ScopeKind.CATEGORY
    assert record.scope.id == CATEGORY_ID
    assert record.subject == "device"
    assert record.endpoint == "service_life"
    assert record.endpoint_kind is LifecycleEndpointKind.TOTAL_LIFE
    assert record.metric == "elapsed_time"
    assert record.unit == "years"
    assert (record.lower_bound, record.upper_bound) == (2.0, 5.0)
    assert record.evidence_level is EvidenceLevel.C
    assert record.required_variant_ids == ()
    assert record.excluded_variant_ids == ()
    assert record.applicable_from is None
    assert record.applicable_to is None
    assert record.model_year_from is None
    assert record.model_year_to is None
    assert record.source_ids == ("headphones_swiss_service_lifetime_2017",)

    qualification = record.endpoint_qualification.casefold()
    assert "approximately 2-5 years" in qualification
    assert "weighted interquartile" in qualification
    assert "graph-read" in qualification
    assert "respondent-reported average completed use" in qualification
    assert "headphones/headsets" in qualification
    assert "individual-device" in qualification
    assert "physical" in qualification
    assert "forecast" in qualification

    assumptions = " ".join(record.assumptions).casefold()
    assert "active use" in assumptions
    assert "373" in assumptions
    assert "aggregate answers" in assumptions
    assert "unique people" in assumptions
    assert "first-owner" in assumptions
    assert "central-half" in assumptions
    assert "exactly 50%" in assumptions

    population = record.population_definition.casefold()
    assert "switzerland" in population
    assert "liechtenstein" in population
    assert "convenience" in population
    assert "demographic" in population
    assert "2014" in record.publication_period
    assert "2015-2016" in record.publication_period

    methodology = record.methodology.casefold()
    assert "figure 1" in methodology
    assert "box plot" in methodology
    assert "weighted histogram" in methodology
    assert "one-year" in methodology
    assert "supporting information s1" in methodology
    assert "graph-read" in methodology
    assert "mean" not in methodology

    assert "Broad estimate" in record.uncertainty
    assert "Low confidence" in record.uncertainty
    limitations = " ".join(record.limitations).casefold()
    assert "recall" in limitations
    assert "selection" in limitations
    assert "timing" in limitations
    assert "sale year" in limitations
    assert "second service" in limitations
    assert "ownership" in limitations
    assert "modern wireless" in limitations
    assert "earbud" in limitations
    assert "reference-only" in limitations
    assert "industry_average_reference_only" in limitations


def test_headphone_component_templates_cover_supported_layers_only(
    headphone_records,
):
    templates = {
        item.template_id: item for item in headphone_records.component_templates
    }
    associations: dict[str, list] = {}
    for item in headphone_records.component_associations:
        associations.setdefault(item.template_id, []).append(item)

    assert set(templates) == {
        "headphones_modern_wireless",
        "headphones_standard",
        "headphones_true_wireless",
    }
    assert "headphones_legacy_wired" not in templates
    assert all(
        len(items) == len({item.component_id for item in items})
        for items in associations.values()
    )
    assert templates["headphones_standard"].template_kind is TemplateKind.STANDARD
    assert templates["headphones_standard"].scope == type(
        templates["headphones_standard"].scope
    )(ScopeKind.CATEGORY, CATEGORY_ID)
    assert templates["headphones_modern_wireless"].template_kind is (
        TemplateKind.MODERN_OVERLAY
    )
    assert templates["headphones_modern_wireless"].scope == type(
        templates["headphones_modern_wireless"].scope
    )(ScopeKind.SUBTYPE, "headphones_wireless_over_ear")
    assert templates["headphones_true_wireless"].template_kind is (
        TemplateKind.MODERN_OVERLAY
    )
    assert templates["headphones_true_wireless"].scope == type(
        templates["headphones_true_wireless"].scope
    )(ScopeKind.SUBTYPE, "headphones_true_wireless")

    standard = {item.component_id for item in associations["headphones_standard"]}
    assert standard >= {
        "audio_driver",
        "audio_driver_material",
        "controls",
        "ear_cushions_or_tips",
        "enclosure_material",
        "enclosure_or_headband",
        "signal_cable",
    }
    modern = {
        item.component_id for item in associations["headphones_modern_wireless"]
    }
    assert modern >= {
        "circuit_board_material",
        "controls",
        "device_battery",
        "device_battery_chemistry",
        "microphones",
        "printed_circuit_board",
        "radio_module",
    }
    true_wireless = {
        item.component_id for item in associations["headphones_true_wireless"]
    }
    assert true_wireless >= modern | {
        "charging_case",
        "charging_case_battery",
        "charging_case_battery_chemistry",
        "charging_case_material",
    }


def test_headphone_resolved_components_keep_device_and_case_batteries_distinct(
    headphone_records,
):
    identities = {item.identity_id: item for item in headphone_records.identities}
    resolver = EvidenceResolver(_LoadedHeadphoneComponentStore(headphone_records))

    sony = resolver.resolve_components(_identity_scope(identities["sony_wh_1000xm5"]))
    sony_components = {item.component_id: item for item in sony.components}
    assert sony.applied_template_ids == (
        "headphones_standard",
        "headphones_modern_wireless",
    )
    assert sony_components["device_battery"].status is (
        AssociationStatus.COMMONLY_ASSOCIATED
    )
    assert sony_components["device_battery_chemistry"].status is (
        AssociationStatus.UNKNOWN
    )
    assert "charging_case_battery" not in sony_components

    airpods = resolver.resolve_components(
        _identity_scope(identities["apple_airpods_pro_2_usb_c"])
    )
    airpods_components = {item.component_id: item for item in airpods.components}
    assert airpods.applied_template_ids == (
        "headphones_standard",
        "headphones_true_wireless",
    )
    assert airpods_components["device_battery"].status is (
        AssociationStatus.COMMONLY_ASSOCIATED
    )
    assert airpods_components["charging_case_battery"].status is (
        AssociationStatus.COMMONLY_ASSOCIATED
    )
    assert airpods_components["device_battery_chemistry"].status is (
        AssociationStatus.UNKNOWN
    )
    assert airpods_components["charging_case_battery_chemistry"].status is (
        AssociationStatus.UNKNOWN
    )
    assert airpods_components["device_battery"] != airpods_components[
        "charging_case_battery"
    ]


def test_headphone_component_unknowns_are_structured_and_covered(
    headphone_records,
):
    associations = {
        item.association_id: item
        for item in headphone_records.component_associations
    }
    authored_unknowns = {
        item.claim_id: item
        for item in headphone_records.unknowns
        if item.claim_kind is UnknownClaimKind.COMPONENT_ASSOCIATION
    }
    actual_unknowns = {
        item.association_id
        for item in headphone_records.component_associations
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


def test_headphone_hazards_are_scoped_to_each_supported_battery_location(
    headphone_records,
):
    hazards = {item.hazard_id: item for item in headphone_records.hazards}

    assert set(hazards) == {
        "headphones_true_wireless_case_damaged_lithium_ion_battery",
        "headphones_true_wireless_device_damaged_lithium_ion_battery",
        "headphones_wireless_over_ear_damaged_lithium_ion_battery",
    }
    expected_scopes = {
        "headphones_true_wireless_case_damaged_lithium_ion_battery": (
            "charging_case_battery",
            "headphones_true_wireless",
        ),
        "headphones_true_wireless_device_damaged_lithium_ion_battery": (
            "device_battery",
            "headphones_true_wireless",
        ),
        "headphones_wireless_over_ear_damaged_lithium_ion_battery": (
            "device_battery",
            "headphones_wireless_over_ear",
        ),
    }
    for hazard_id, hazard in hazards.items():
        component_id, subtype_id = expected_scopes[hazard_id]
        assert hazard.component_id == component_id
        assert hazard.scope == type(hazard.scope)(ScopeKind.SUBTYPE, subtype_id)
        assert hazard.severity is HazardSeverity.URGENT
        assert hazard.trigger_observation_keys == (
            "observations.issue_flags.overheating",
            "observations.issue_flags.swelling_or_battery_damage",
        )
        assert hazard.evidence_level is EvidenceLevel.B
        assert hazard.source_ids == (
            "headphones_epa_used_li_ion_2026",
            "headphones_osha_small_lithium_devices_2019",
        )
        applicability = hazard.applicability.casefold()
        assert "activates precautionary guidance" in applicability
        assert "if the installed" in applicability
        assert "lithium-ion" in applicability
        assert "do not establish chemistry" in applicability


def test_headphone_hazard_actions_match_imported_source_scope(headphone_records):
    for hazard in headphone_records.hazards:
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
        assert not any(
            marker in all_actions
            for marker in ("leak confirmed", "ocr", "visual diagnosis")
        )


def test_headphone_damaged_battery_destinations_are_locally_qualified(
    headphone_records,
):
    for hazard in headphone_records.hazards:
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


def test_headphone_unknown_inventory_exposes_actual_release_gaps(headphone_records):
    unknowns_by_kind = {
        kind: {
            item.claim_id
            for item in headphone_records.unknowns
            if item.claim_kind is kind
        }
        for kind in UnknownClaimKind
    }

    assert len(headphone_records.identities) == 5
    assert len(headphone_records.subtypes) == 2
    assert len(headphone_records.specific_lifecycles) == 2
    assert len(headphone_records.industry_averages) == 1
    assert len(headphone_records.component_templates) == 3
    assert unknowns_by_kind[UnknownClaimKind.IDENTITY] == EXPECTED_UNKNOWN_IDENTITIES
    assert unknowns_by_kind[UnknownClaimKind.SUBTYPE] == EXPECTED_UNKNOWN_SUBTYPES
    assert unknowns_by_kind[UnknownClaimKind.SPECIFIC_LIFECYCLE] == {
        "airpods_pro_2_listening_runtime"
    }
    assert unknowns_by_kind[UnknownClaimKind.COMPONENT_ASSOCIATION] == (
        EXPECTED_COMPONENT_UNKNOWNS
    )
    assert unknowns_by_kind[UnknownClaimKind.VARIANT] == set()
    assert unknowns_by_kind[UnknownClaimKind.INDUSTRY_AVERAGE] == set()
    assert unknowns_by_kind[UnknownClaimKind.HAZARD] == set()


def test_headphone_ids_are_disjoint_from_shared_and_accepted_siblings(
    headphone_records,
):
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

    headphone_ids = {
        "sources": {item.source_id for item in headphone_records.sources},
        "subtypes": {item.subtype_id for item in headphone_records.subtypes},
        "variants": {item.variant_id for item in headphone_records.variants},
        "identities": {item.identity_id for item in headphone_records.identities},
        "lifecycles": {
            item.record_id
            for item in (
                *headphone_records.specific_lifecycles,
                *headphone_records.industry_averages,
            )
        },
        "templates": {
            item.template_id for item in headphone_records.component_templates
        },
        "associations": {
            item.association_id for item in headphone_records.component_associations
        },
        "hazards": {item.hazard_id for item in headphone_records.hazards},
    }
    for namespace, ids in headphone_ids.items():
        assert ids.isdisjoint(sibling_ids[namespace]), namespace
