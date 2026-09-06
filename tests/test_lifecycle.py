import pytest

from server.lifecycle import (
    AssessmentInputs,
    Condition,
    Confidence,
    Diagnostic,
    OperationalState,
    Range,
    Recommendation,
    Usage,
    assess_component,
)


def component_with_lifecycle(lifecycle, **extra):
    return {"component_id": "generic_component", "lifecycle": lifecycle, **extra}


def component_with_life_years(minimum, maximum, **extra):
    return component_with_lifecycle(
        {
            "metric": "years",
            "minimum": minimum,
            "maximum": maximum,
            "source_ids": ["reviewed_lifecycle_source"],
        },
        **extra,
    )


def inputs(**changes):
    values = {
        "age_months": None,
        "cycle_count": None,
        "usage": Usage.UNKNOWN,
        "condition": Condition.NO_VISIBLE_DAMAGE,
        "operational": OperationalState.WORKING,
        "diagnostics": (),
    }
    values.update(changes)
    return AssessmentInputs(**values)


def lithium_battery(**extra):
    return component_with_lifecycle(
        {
            "metric": "cycles",
            "minimum": 800,
            "maximum": 800,
            "source_ids": ["eu_phone_ecodesign_2023_1670"],
        },
        safety_sensitive=True,
        **extra,
    )


def test_year_range_uses_conservative_interval_math():
    result = assess_component(component_with_life_years(4, 6), inputs(age_months=Range(24, 36)))

    assert result.percent_used == Range(33, 75)
    assert result.confidence is Confidence.MODERATE
    assert {evidence.kind for evidence in result.evidence} >= {"lifecycle_reference", "age"}


@pytest.mark.parametrize(
    ("age", "expected"),
    [(Range(0, 0), Range(0, 0)), (Range(72, 96), Range(100, 100))],
)
def test_year_range_clamps_outward_rounded_boundaries(age, expected):
    result = assess_component(component_with_life_years(4, 6), inputs(age_months=age))

    assert result.percent_used == expected


def test_missing_lifecycle_returns_unknown_not_a_guess():
    result = assess_component(component_with_lifecycle(None), inputs(age_months=Range(24, 36)))

    assert result.percent_used is None
    assert result.confidence is Confidence.UNAVAILABLE
    assert result.recommendation is Recommendation.UNKNOWN
    assert "no supported lifecycle reference" in " ".join(result.reasons).lower()


def test_unsupported_lifecycle_metric_returns_unknown_not_missing_input_copy():
    result = assess_component(
        component_with_lifecycle(
            {
                "metric": "manufacturer_score",
                "minimum": 4,
                "maximum": 6,
                "source_ids": ["reviewed_lifecycle_source"],
            }
        ),
        inputs(age_months=Range(24, 36)),
    )

    assert result.percent_used is None
    assert result.confidence is Confidence.UNAVAILABLE
    assert "unsupported lifecycle metric" in " ".join(result.reasons).lower()


def test_cycle_lifecycle_requires_user_supplied_cycle_range():
    component = lithium_battery()

    missing = assess_component(component, inputs(age_months=Range(24, 36)))
    supplied = assess_component(component, inputs(cycle_count=Range(200, 400)))

    assert missing.percent_used is None
    assert supplied.percent_used == Range(25, 50)


def test_usage_is_evidence_but_does_not_shift_a_sourced_range():
    component = component_with_life_years(4, 6)
    light = assess_component(component, inputs(age_months=Range(24, 36), usage=Usage.LIGHT))
    heavy = assess_component(component, inputs(age_months=Range(24, 36), usage=Usage.HEAVY))

    assert light.percent_used == heavy.percent_used == Range(33, 75)
    assert any(evidence.kind == "usage" and "heavy" in evidence.detail for evidence in heavy.evidence)


def test_unknown_condition_widens_supported_interval_and_lowers_confidence():
    result = assess_component(
        component_with_life_years(4, 6),
        inputs(age_months=Range(24, 36), condition=Condition.UNKNOWN),
    )

    assert result.percent_used == Range(18, 90)
    assert result.confidence is Confidence.LOW


def test_visible_wear_widens_only_upper_bound_and_lowers_confidence():
    result = assess_component(
        component_with_life_years(4, 6),
        inputs(age_months=Range(24, 36), condition=Condition.VISIBLE_WEAR),
    )

    assert result.percent_used == Range(33, 85)
    assert result.confidence is Confidence.LOW


def test_damaged_safety_sensitive_component_blocks_reuse():
    result = assess_component(lithium_battery(), inputs(condition=Condition.DAMAGED))

    assert result.recommendation is Recommendation.SPECIALIST_HANDLING
    assert result.percent_used is None
    assert "photo confidence" not in " ".join(result.reasons).lower()


def test_not_working_safety_sensitive_component_blocks_reuse():
    result = assess_component(lithium_battery(), inputs(operational=OperationalState.NOT_WORKING))

    assert result.recommendation is Recommendation.SPECIALIST_HANDLING
    assert result.percent_used is None


def test_intermittent_operation_requires_diagnostic_test_even_with_low_estimate():
    result = assess_component(
        component_with_life_years(4, 6),
        inputs(age_months=Range(1, 1), operational=OperationalState.INTERMITTENT),
    )

    assert result.recommendation is Recommendation.DIAGNOSTIC_TEST
    assert "intermittent" in " ".join(result.reasons).lower()


def test_supported_measured_diagnostic_overrides_age_estimate_with_provenance():
    component = component_with_life_years(
        4,
        6,
        supported_diagnostics=("percent_used",),
    )
    result = assess_component(
        component,
        inputs(
            age_months=Range(24, 36),
            diagnostics=(
                Diagnostic(
                    metric="percent_used",
                    value=Range(20, 30),
                    evidence_kind="measured",
                    source_id="battery_tester_2026-09-06",
                ),
            ),
        ),
    )

    assert result.percent_used == Range(20, 30)
    assert result.confidence is Confidence.HIGH
    assert any(evidence.kind == "age_estimate" and "33–75%" in evidence.detail for evidence in result.evidence)
    assert any(evidence.kind == "measured_diagnostic" for evidence in result.evidence)


def test_unsupported_or_unmeasured_diagnostic_does_not_override_estimate():
    component = component_with_life_years(4, 6, supported_diagnostics=("percent_used",))
    result = assess_component(
        component,
        inputs(
            age_months=Range(24, 36),
            diagnostics=(
                Diagnostic(
                    metric="percent_used",
                    value=Range(20, 30),
                    evidence_kind="reported",
                    source_id="owner_report",
                ),
            ),
        ),
    )

    assert result.percent_used == Range(33, 75)
    assert result.confidence is Confidence.MODERATE


def test_range_rejects_reversed_or_negative_values():
    with pytest.raises(ValueError):
        Range(4, 3)
    with pytest.raises(ValueError):
        Range(-1, 3)
