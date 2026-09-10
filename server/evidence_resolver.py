"""Deterministic selection and assembly of reviewed evidence snapshots."""

from __future__ import annotations

from server.evidence_types import (
    CanonicalIdentityScope,
    ComponentResolution,
    HazardResolution,
    LifecycleRecordSnapshot,
    LifecycleRequest,
    LifecycleResolution,
    ResolvedEvidence,
    ResolutionStep,
    ResolutionTier,
    ScopeKind,
)
from server.knowledge_store import KnowledgeStore


_TIER_ORDER = (
    ResolutionTier.EXACT_MODEL,
    ResolutionTier.FAMILY,
    ResolutionTier.SUBTYPE,
    ResolutionTier.INDUSTRY_AVERAGE,
)
_SCOPE_FIELDS = {
    ScopeKind.CATEGORY: "category_id",
    ScopeKind.SUBTYPE: "subtype_id",
    ScopeKind.FAMILY: "family_id",
    ScopeKind.MODEL: "model_id",
}
_CONFLICT_REASON = "Conflicting reviewed records at the same evidence tier."
_NO_COMPATIBLE_REASON = "No compatible reviewed lifecycle record."


def _scope_matches(
    scope: CanonicalIdentityScope, scope_kind: ScopeKind, scope_id: str,
) -> bool:
    return getattr(scope, _SCOPE_FIELDS[scope_kind]) == scope_id


def _rejection_reason(
    record: LifecycleRecordSnapshot,
    scope: CanonicalIdentityScope,
    request: LifecycleRequest,
) -> str | None:
    if not _scope_matches(scope, record.scope_kind, record.scope_id):
        return "scope mismatch"
    for field in ("subject", "endpoint", "metric", "unit"):
        if getattr(record, field) != getattr(request, field):
            return f"{field} mismatch"

    if record.model_year_from is not None or record.model_year_to is not None:
        if scope.model_year is None:
            return "model year unavailable"
        if (
            record.model_year_from is not None
            and scope.model_year < record.model_year_from
        ) or (
            record.model_year_to is not None
            and scope.model_year > record.model_year_to
        ):
            return "model year out of range"

    if record.applicable_from is not None or record.applicable_to is not None:
        if scope.applicable_on is None:
            return "applicability date unavailable"
        if (
            record.applicable_from is not None
            and scope.applicable_on < record.applicable_from
        ) or (
            record.applicable_to is not None
            and scope.applicable_on > record.applicable_to
        ):
            return "applicability date out of range"

    variants = set(scope.variant_ids)
    if not set(record.required_variant_ids).issubset(variants):
        return "required variant missing"
    if set(record.excluded_variant_ids).intersection(variants):
        return "excluded variant present"
    return None


class EvidenceResolver:
    """Resolve records without deriving assessments or interpreting policy."""

    def __init__(self, store: KnowledgeStore):
        self._store = store

    def resolve_lifecycle(
        self, scope: CanonicalIdentityScope, request: LifecycleRequest,
    ) -> LifecycleResolution:
        candidates = self._store.lifecycle_candidates(scope)
        trace = []
        for tier in _TIER_ORDER:
            considered = tuple(sorted(
                (record for record in candidates if record.resolution_tier is tier),
                key=lambda record: record.record_id,
            ))
            considered_ids = tuple(record.record_id for record in considered)
            if not considered:
                trace.append(ResolutionStep(
                    tier, (), (), None, "no_candidates",
                ))
                continue

            rejected = []
            eligible = []
            for record in considered:
                reason = _rejection_reason(record, scope, request)
                if reason is None:
                    eligible.append(record)
                else:
                    rejected.append((record.record_id, reason))
            rejected_tuple = tuple(rejected)
            if not eligible:
                trace.append(ResolutionStep(
                    tier, considered_ids, rejected_tuple, None, "filtered",
                ))
                continue

            precedence = min(record.precedence for record in eligible)
            winners = tuple(
                record for record in eligible if record.precedence == precedence
            )
            if len(winners) != 1:
                trace.append(ResolutionStep(
                    tier, considered_ids, rejected_tuple, None, "conflict",
                ))
                return LifecycleResolution(
                    None, None, tuple(trace), _CONFLICT_REASON,
                )

            selected = winners[0]
            trace.append(ResolutionStep(
                tier,
                considered_ids,
                rejected_tuple,
                selected.record_id,
                "selected",
            ))
            return LifecycleResolution(selected, tier, tuple(trace), None)

        return LifecycleResolution(
            None, None, tuple(trace), _NO_COMPATIBLE_REASON,
        )

    def resolve_components(
        self, scope: CanonicalIdentityScope,
    ) -> ComponentResolution:
        components = []
        slots = {}
        applied_template_ids = []
        for layer in self._store.component_layers(scope):
            applied_template_ids.append(layer.template_id)
            for association in layer.associations:
                slot = slots.get(association.component_id)
                if slot is None:
                    slots[association.component_id] = len(components)
                    components.append(association)
                else:
                    components[slot] = association
        return ComponentResolution(tuple(components), tuple(applied_template_ids))

    def resolve_hazards(self, scope: CanonicalIdentityScope) -> HazardResolution:
        return HazardResolution(tuple(
            hazard
            for hazard in self._store.hazard_candidates(scope)
            if _scope_matches(scope, hazard.scope_kind, hazard.scope_id)
        ))

    def resolve(
        self, scope: CanonicalIdentityScope, request: LifecycleRequest,
    ) -> ResolvedEvidence:
        return ResolvedEvidence(
            scope,
            self.resolve_lifecycle(scope, request),
            self.resolve_components(scope),
            self.resolve_hazards(scope),
            self._store.policy_bundle(),
            self._store.manifest.stamp,
        )
