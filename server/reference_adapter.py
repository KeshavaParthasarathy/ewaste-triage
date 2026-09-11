"""Opt-in schema-3 evidence projection for legacy v1 reference consumers."""

from __future__ import annotations

from server.evidence_resolver import EvidenceResolver
from server.evidence_types import (
    AssociationStatus,
    CanonicalIdentityScope,
    ComponentAssociationSnapshot,
    HazardSnapshot,
    SourceSnapshot,
)
from server.knowledge_store import KnowledgeStore


_CATEGORY_PRESENCE = {
    AssociationStatus.COMMONLY_ASSOCIATED: "standard",
    AssociationStatus.CONDITIONAL: "optional",
    AssociationStatus.LEGACY_SPECIFIC: "unknown",
    AssociationStatus.NOT_PRESENT: "unknown",
    AssociationStatus.UNKNOWN: "unknown",
}


def _source_dict(source: SourceSnapshot) -> dict[str, object]:
    return {
        "source_id": source.source_id,
        "title": source.title,
        "publisher": source.publisher,
        "canonical_url": source.canonical_url,
        "publication_or_revision_date": (
            source.publication_or_revision_date.isoformat()
        ),
        "accessed_on": source.accessed_on.isoformat(),
        "license_or_use_basis": source.license_or_use_basis,
        "reviewed_by": source.reviewed_by,
        "reviewed_on": source.reviewed_on.isoformat(),
    }


def _presence_label(status: AssociationStatus) -> str:
    try:
        return _CATEGORY_PRESENCE[status]
    except KeyError as exc:
        raise ValueError(
            "item-specific association status cannot be projected at category scope"
        ) from exc


def _component_dict(
    association: ComponentAssociationSnapshot,
) -> dict[str, object]:
    sources = [_source_dict(source) for source in association.sources]
    return {
        "association_id": association.association_id,
        "association_status": association.status.value,
        "component_id": association.component_id,
        "display_name": association.display_name,
        "presence_label": _presence_label(association.status),
        "applicability": association.applicability,
        "lifecycle": None,
        "source_ids": [source.source_id for source in association.sources],
        "sources": sources,
        "evidence_grade": (
            association.evidence_level.value
            if association.evidence_level is not None
            else None
        ),
        "reviewed_on": None,
        "safety_sensitive": None,
        "notes": list(association.notes),
    }


def _hazard_text(hazard: HazardSnapshot) -> str:
    sections = [
        "Possible conditional hazard; trigger observations were not evaluated.",
        f"Applicability: {hazard.applicability}",
        "Immediate actions: " + " ".join(hazard.immediate_actions),
        "Follow-up actions: " + " ".join(hazard.follow_up_actions),
        "Handling guidance: " + " ".join(hazard.handling_guidance),
        "Disposal guidance: " + " ".join(hazard.disposal_guidance),
    ]
    return " ".join(sections)


def _rule_dict(hazard: HazardSnapshot) -> dict[str, object]:
    sources = [_source_dict(source) for source in hazard.sources]
    return {
        "rule_id": hazard.hazard_id,
        "component_id": hazard.component_id,
        "text": _hazard_text(hazard),
        "revision": None,
        "reviewed_on": None,
        "applicability": hazard.applicability,
        "trigger_observation_keys": list(hazard.trigger_observation_keys),
        "severity": hazard.severity.value,
        "immediate_actions": list(hazard.immediate_actions),
        "follow_up_actions": list(hazard.follow_up_actions),
        "handling_guidance": list(hazard.handling_guidance),
        "disposal_guidance": list(hazard.disposal_guidance),
        "source_ids": [source.source_id for source in hazard.sources],
        "sources": sources,
        "evidence_grade": hazard.evidence_level.value,
    }


class V1ReferenceAdapter:
    """Project category-only evidence through the existing v1 store interface."""

    def __init__(self, store: KnowledgeStore, resolver: EvidenceResolver):
        self._store = store
        self._resolver = resolver

    def _category_dict(self, category) -> dict[str, object]:
        return {
            "category_id": category.category_id,
            "display_name": category.display_name,
            "template_version": self._store.manifest.bundle_version,
        }

    def list_categories(self) -> list[dict[str, object]]:
        return [
            self._category_dict(category)
            for category in self._store.list_categories()
        ]

    def get_category(self, category_id: str) -> dict[str, object] | None:
        category = self._store.get_category(category_id)
        return self._category_dict(category) if category is not None else None

    def snapshot(self, category_id: str) -> dict[str, object]:
        category = self.get_category(category_id)
        if category is None:
            raise KeyError(category_id)

        scope = CanonicalIdentityScope(category_id)
        components = self._resolver.resolve_components(scope)
        hazards = self._resolver.resolve_hazards(scope)
        return {
            **category,
            "schema_version": self._store.manifest.schema_version,
            "components": [
                _component_dict(component) for component in components.components
            ],
            "rules": [_rule_dict(hazard) for hazard in hazards.hazards],
        }
