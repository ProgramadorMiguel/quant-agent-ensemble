from pathlib import Path

from evaluation.costs import ModelPrice, cost_of, load_prices


ROOT = Path(__file__).resolve().parents[1]


def test_cached_input_tokens_are_billed_at_the_reduced_rate():
    price = ModelPrice(
        provider="openai", input_per_mtok=1.0, output_per_mtok=2.0,
        cached_input_per_mtok=0.25, verified=True,
    )
    full = price.cost_usd(1_000_000, 0)
    half_cached = price.cost_usd(1_000_000, 0, cached=500_000)
    assert full == 1.0
    assert half_cached == 0.5 + 0.125


def test_cost_of_discounts_cached_tokens_when_reported():
    """Sin el descuento, la factura calculada sobreestima la real."""
    model = next(iter(load_prices(ROOT)))
    without = cost_of(ROOT, model, 2_000, 100)
    with_cache = cost_of(ROOT, model, 2_000, 100, cached_input_tokens=1_500)
    assert without is not None and with_cache is not None
    assert with_cache < without
    # None (proveedor sin dato) equivale a "nada cacheado", no a un error.
    assert cost_of(ROOT, model, 2_000, 100, cached_input_tokens=None) == without


def test_unknown_model_has_no_cost():
    assert cost_of(ROOT, "modelo-inexistente", 10, 10) is None
