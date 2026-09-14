from evaluation.metrics import FieldOutcome, compare_fields, flatten


GOLDEN = {
    "notional": 10000000,
    "currency": "EUR",
    "is_fixed_rate_receiver": False,
    "valuation_date": "2026-09-01",
    "effective_date": "2026-09-01",
    "maturity_date": "2031-09-01",
    "discount_curve": "EUR-ESTR",
    "forecast_curve": "EUR-EURIBOR-6M",
    "fixed_leg": {
        "rate": 0.0275, "day_count": "30/360", "payment_frequency": "1Y",
    },
    "floating_leg": {
        "index": "EURIBOR", "tenor": "6M", "spread": None,
        "day_count": "ACT/360", "payment_frequency": "6M",
    },
}


def test_flatten_uses_dotted_paths_for_legs():
    flat = flatten(GOLDEN)
    assert flat["fixed_leg.day_count"] == "30/360"
    assert flat["floating_leg.tenor"] == "6M"
    assert "fixed_leg" not in flat


def test_every_leg_term_is_counted_separately():
    """Sin aplanar, cada pata contaria como un solo campo y la exactitud
    por campo dejaria de ser un diagnostico."""
    comparison = compare_fields(GOLDEN, GOLDEN)
    assert comparison.total == 16
    assert comparison.matched == 16


def test_two_errors_in_one_leg_count_as_two():
    actual = {**GOLDEN, "fixed_leg": {
        "rate": 0.0275, "day_count": "ACT/360", "payment_frequency": "6M",
    }}
    comparison = compare_fields(actual, GOLDEN)
    assert comparison.count(FieldOutcome.WRONG) == 2
    assert comparison.per_field["fixed_leg.day_count"] is FieldOutcome.WRONG
    assert comparison.per_field["fixed_leg.payment_frequency"] is FieldOutcome.WRONG


def test_a_dropped_leg_term_is_missing_not_wrong():
    actual = {**GOLDEN, "floating_leg": {**GOLDEN["floating_leg"], "day_count": None}}
    comparison = compare_fields(actual, GOLDEN)
    assert comparison.per_field["floating_leg.day_count"] is FieldOutcome.MISSING


def test_an_invented_leg_term_is_hallucinated():
    """El dorado deja el spread vacio: rellenarlo es una alucinacion."""
    actual = {**GOLDEN, "floating_leg": {**GOLDEN["floating_leg"], "spread": 0.0025}}
    comparison = compare_fields(actual, GOLDEN)
    assert comparison.per_field["floating_leg.spread"] is FieldOutcome.HALLUCINATED
    assert comparison.hallucinated_fields == ["floating_leg.spread"]
