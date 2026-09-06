"""Deterministic, evidence-carrying lifecycle estimates for component templates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import ceil, floor
from typing import Mapping


class Usage(str, Enum):
    UNKNOWN = "unknown"
    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"


class Condition(str, Enum):
    UNKNOWN = "unknown"
    NO_VISIBLE_DAMAGE = "no_visible_damage"
    VISIBLE_WEAR = "visible_wear"
    DAMAGED = "damaged"


class OperationalState(str, Enum):
    UNKNOWN = "unknown"
    WORKING = "working"
    INTERMITTENT = "intermittent"
    NOT_WORKING = "not_working"


class Confidence(str, Enum):
    UNAVAILABLE = "unavailable"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class Recommendation(str, Enum):
    UNKNOWN = "unknown"
    LIKELY_REUSABLE = "likely_reusable"
    DIAGNOSTIC_TEST = "diagnostic_test"
    REPAIR_ASSESSMENT = "repair_assessment"
    RECYCLE = "recycle"
    SPECIALIST_HANDLING = "specialist_handling"


@dataclass(frozen=True)
class Range:
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if isinstance(self.minimum, bool) or isinstance(self.maximum, bool):
            raise ValueError("range bounds must be integers")
        if not isinstance(self.minimum, int) or not isinstance(self.maximum, int):
            raise ValueError("range bounds must be integers")
        if self.minimum < 0 or self.minimum > self.maximum:
            raise ValueError("range bounds must be non-negative and ordered")


@dataclass(frozen=True)
class Diagnostic:
    """An item-specific diagnostic value and the way it was obtained."""

    metric: str
    value: Range
    evidence_kind: str
    source_id: str | None = None


@dataclass(frozen=True)
class Evidence:
    kind: str
    detail: str
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssessmentInputs:
    age_months: Range | None = None
    usage: Usage = Usage.UNKNOWN
    condition: Condition = Condition.UNKNOWN
    operational: OperationalState = OperationalState.UNKNOWN
    diagnostics: tuple[Diagnostic, ...] = ()
    cycle_count: Range | None = None


@dataclass(frozen=True)
class LifecycleResult:
    percent_used: Range | None
    confidence: Confidence
    evidence: tuple[Evidence, ...]
    recommendation: Recommendation
    reasons: tuple[str, ...]


def _source_ids(lifecycle: Mapping) -> tuple[str, ...]:
    source_ids = lifecycle.get("source_ids", ())
    if isinstance(source_ids, str):
        source_ids = (source_ids,)
    if not isinstance(source_ids, (tuple, list)) or not all(
        isinstance(source_id, str) and source_id for source_id in source_ids
    ):
        return ()
    return tuple(source_ids)


def _lifecycle_range(lifecycle: Mapping) -> Range | None:
    minimum, maximum = lifecycle.get("minimum"), lifecycle.get("maximum")
    try:
        return Range(minimum, maximum)
    except ValueError:
        return None


def _outward_percent(numerator: Range, denominator: Range) -> Range:
    return Range(
        max(0, floor(100 * numerator.minimum / denominator.maximum)),
        min(100, ceil(100 * numerator.maximum / denominator.minimum)),
    )


def _age_estimate(lifecycle: Mapping, age_months: Range | None, cycle_count: Range | None) -> Range | None:
    life = _lifecycle_range(lifecycle)
    if life is None:
        return None
    if lifecycle.get("metric") == "years":
        if age_months is None:
            return None
        return _outward_percent(age_months, Range(life.minimum * 12, life.maximum * 12))
    if lifecycle.get("metric") == "cycles" and cycle_count is not None:
        return _outward_percent(cycle_count, life)
    return None


def _lower(confidence: Confidence) -> Confidence:
    return {
        Confidence.HIGH: Confidence.MODERATE,
        Confidence.MODERATE: Confidence.LOW,
        Confidence.LOW: Confidence.UNAVAILABLE,
        Confidence.UNAVAILABLE: Confidence.UNAVAILABLE,
    }[confidence]


def _apply_condition(value: Range, condition: Condition) -> Range:
    if condition is Condition.UNKNOWN:
        return Range(max(0, value.minimum - 15), min(100, value.maximum + 15))
    if condition is Condition.VISIBLE_WEAR:
        return Range(value.minimum, min(100, value.maximum + 10))
    return value


def _diagnostic_override(component: Mapping, diagnostics: tuple[Diagnostic, ...]) -> Diagnostic | None:
    supported = component.get("supported_diagnostics", ())
    if isinstance(supported, str):
        supported = (supported,)
    for diagnostic in diagnostics:
        if (
            diagnostic.evidence_kind == "measured"
            and diagnostic.source_id
            and diagnostic.metric in supported
            and diagnostic.metric == "percent_used"
        ):
            return diagnostic
    return None


def _recommendation(
    component: Mapping,
    inputs: AssessmentInputs,
    percent_used: Range | None,
) -> tuple[Recommendation, tuple[str, ...]]:
    safety_sensitive = component.get("safety_sensitive") is True
    if safety_sensitive and inputs.condition is Condition.DAMAGED:
        return Recommendation.SPECIALIST_HANDLING, (
            "Damage on a safety-sensitive component needs specialist handling before reuse.",
        )
    if safety_sensitive and inputs.operational is OperationalState.NOT_WORKING:
        return Recommendation.SPECIALIST_HANDLING, (
            "A non-working safety-sensitive component needs specialist handling before reuse.",
        )
    if inputs.operational is OperationalState.INTERMITTENT:
        return Recommendation.DIAGNOSTIC_TEST, (
            "Intermittent operation requires a diagnostic test before any reuse decision.",
        )
    if inputs.condition is Condition.DAMAGED or inputs.operational is OperationalState.NOT_WORKING:
        return Recommendation.REPAIR_ASSESSMENT, (
            "Damage or a non-working state needs a repair assessment before reuse.",
        )
    if percent_used is None:
        return Recommendation.UNKNOWN, (
            "A supported lifecycle estimate needs more item-specific evidence.",
        )
    if inputs.operational is OperationalState.WORKING:
        return Recommendation.LIKELY_REUSABLE, (
            "Working status supports likely reuse after the applicable functional test.",
        )
    return Recommendation.DIAGNOSTIC_TEST, (
        "Operating status is unknown; perform a diagnostic test before reuse.",
    )


def assess_component(component: Mapping, inputs: AssessmentInputs) -> LifecycleResult:
    """Estimate consumed lifecycle only from sourced references and supplied facts."""
    lifecycle = component.get("lifecycle")
    evidence: list[Evidence] = [
        Evidence("usage", f"User-reported usage: {inputs.usage.value}; it does not alter this estimate."),
        Evidence("condition", f"User-reported visible condition: {inputs.condition.value}."),
        Evidence("operational", f"User-reported operating state: {inputs.operational.value}."),
    ]

    recommendation, safety_reasons = _recommendation(component, inputs, None)
    if recommendation is Recommendation.SPECIALIST_HANDLING:
        return LifecycleResult(None, Confidence.UNAVAILABLE, tuple(evidence), recommendation, safety_reasons)

    if not isinstance(lifecycle, Mapping) or not _source_ids(lifecycle):
        return LifecycleResult(
            None,
            Confidence.UNAVAILABLE,
            tuple(evidence),
            Recommendation.UNKNOWN,
            ("No supported lifecycle reference is available for this component.",),
        )

    source_ids = _source_ids(lifecycle)
    base = _age_estimate(lifecycle, inputs.age_months, inputs.cycle_count)
    evidence.append(Evidence("lifecycle_reference", "Sourced lifecycle reference.", source_ids))
    if inputs.age_months is not None:
        evidence.append(Evidence("age", f"User-reported age: {inputs.age_months.minimum}–{inputs.age_months.maximum} months."))
    if inputs.cycle_count is not None:
        evidence.append(Evidence("cycle_count", f"User-reported cycles: {inputs.cycle_count.minimum}–{inputs.cycle_count.maximum}."))

    measured = _diagnostic_override(component, inputs.diagnostics)
    if measured is not None:
        if base is not None:
            evidence.append(Evidence("age_estimate", f"Age-based estimate retained for provenance: {base.minimum}–{base.maximum}%.", source_ids))
        evidence.append(Evidence("measured_diagnostic", f"Measured {measured.metric}: {measured.value.minimum}–{measured.value.maximum}%.", (measured.source_id,)))
        recommendation, reasons = _recommendation(component, inputs, measured.value)
        return LifecycleResult(measured.value, Confidence.HIGH, tuple(evidence), recommendation, reasons)

    if base is None:
        metric = lifecycle.get("metric")
        if metric not in {"years", "cycles"}:
            recommendation, reasons = _recommendation(component, inputs, None)
            return LifecycleResult(
                None,
                Confidence.UNAVAILABLE,
                tuple(evidence),
                recommendation,
                (f"Unsupported lifecycle metric: {metric!r}.", *reasons),
            )
        requirement = "cycle-count range" if lifecycle.get("metric") == "cycles" else "age range"
        recommendation, reasons = _recommendation(component, inputs, None)
        return LifecycleResult(
            None,
            Confidence.UNAVAILABLE,
            tuple(evidence),
            recommendation,
            (f"A user-supplied {requirement} is required for this sourced lifecycle estimate.", *reasons),
        )

    evidence.append(Evidence("age_estimate", f"Outward-rounded sourced estimate: {base.minimum}–{base.maximum}%.", source_ids))
    confidence = Confidence.MODERATE
    adjusted = _apply_condition(base, inputs.condition)
    if inputs.condition in {Condition.UNKNOWN, Condition.VISIBLE_WEAR}:
        confidence = _lower(confidence)
    recommendation, reasons = _recommendation(component, inputs, adjusted)
    return LifecycleResult(adjusted, confidence, tuple(evidence), recommendation, reasons)
