"""Fixtures compartidas y configuracion de importacion de la bateria de tests.

``src`` se inserta en ``sys.path`` aqui para que los tests no dependan de que la
variable de entorno ``PYTHONPATH`` este puesta: ``pytest`` sin argumentos debe
funcionar en cualquier maquina recien clonada.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from models.irs_fields import (  # noqa: E402
    IBOR,
    OVERNIGHT_COMPOUNDED,
    FixedLegFields,
    FloatingLegFields,
    IRSFields,
)
from models.schedule import add_months  # noqa: E402


EFFECTIVE = date(2026, 9, 1)
MATURITY = date(2031, 9, 1)


def regular_dates(start: date, months: int, count: int) -> list[date]:
    """Calendario regular de ``count`` pagos cada ``months`` meses tras ``start``."""
    return [add_months(start, months * (i + 1)) for i in range(count)]


@pytest.fixture
def dates():
    """Acceso al ayudante de calendarios desde cualquier test."""
    return regular_dates


@pytest.fixture
def eur_fields():
    """Swap EUR a cinco anos con la convencion estandar para plazos > 1Y.

    Pata fija anual 30U/360, flotante semestral EURIBOR 6M ACT/360, descuento en
    EUR-ESTR y estimacion en EUR-EURIBOR-6M. Cinco fechas en la fija y diez en la
    flotante.
    """
    return IRSFields(
        notional=Decimal("10000000"), currency="EUR",
        is_fixed_rate_receiver=False,
        valuation_date=EFFECTIVE, effective_date=EFFECTIVE, maturity_date=MATURITY,
        discount_curve="EUR-ESTR",
        fixed_leg=FixedLegFields(
            rate=Decimal("0.0275"), day_count="30U/360", payment_frequency="1Y",
            payment_dates=regular_dates(EFFECTIVE, 12, 5),
        ),
        floating_leg=FloatingLegFields(
            rate_type=IBOR, index="EURIBOR", tenor="6M", spread=Decimal(0),
            day_count="ACT/360", payment_frequency="6M",
            forecast_curve="EUR-EURIBOR-6M",
            payment_dates=regular_dates(EFFECTIVE, 6, 10),
        ),
    )


@pytest.fixture
def usd_fields():
    """Swap USD a cinco anos: un OIS contra SOFR capitalizado, sin tenor.

    Ambas patas anuales en ACT/360, descuento y estimacion en USD-SOFR.
    """
    return IRSFields(
        notional=Decimal("50000000"), currency="USD",
        is_fixed_rate_receiver=True,
        valuation_date=EFFECTIVE, effective_date=EFFECTIVE, maturity_date=MATURITY,
        discount_curve="USD-SOFR",
        fixed_leg=FixedLegFields(
            rate=Decimal("0.0385"), day_count="ACT/360", payment_frequency="1Y",
            payment_dates=regular_dates(EFFECTIVE, 12, 5),
        ),
        floating_leg=FloatingLegFields(
            rate_type=OVERNIGHT_COMPOUNDED, index="SOFR", spread=Decimal(0),
            day_count="ACT/360", payment_frequency="1Y",
            forecast_curve="USD-SOFR",
            payment_dates=regular_dates(EFFECTIVE, 12, 5),
        ),
    )
