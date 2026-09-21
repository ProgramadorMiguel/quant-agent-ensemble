from __future__ import annotations

import importlib.util
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from google.protobuf import json_format, text_format
from grpc_tools import protoc

from models.irs_fields import FixedLegFields, FloatingLegFields, IRSFields


@lru_cache(maxsize=4)
def _load_pricing_module(proto_path: Path):
    """Compila (si hace falta) y carga el modulo generado, una vez por proceso.

    Sin la cache, cada llamada volvia a ejecutar el modulo pb2 y a registrar el
    mismo descriptor en el pool de protobuf. Funcionaba porque protobuf tolera
    el duplicado identico, pero era trabajo repetido en cada RFQ.
    """
    cache_dir = Path(tempfile.gettempdir()) / "rfq_agents_proto"
    cache_dir.mkdir(parents=True, exist_ok=True)
    generated = cache_dir / "pricing_pb2.py"
    if not generated.exists() or generated.stat().st_mtime < proto_path.stat().st_mtime:
        result = protoc.main([
            "grpc_tools.protoc",
            f"-I{proto_path.parent}",
            f"--python_out={cache_dir}",
            str(proto_path),
        ])
        if result != 0:
            raise RuntimeError(f"Could not compile protobuf schema: {proto_path}")
    module_name = "rfq_agents_pricing_pb2"
    spec = importlib.util.spec_from_file_location(module_name, generated)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load generated protobuf module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def fields_to_textproto(fields: IRSFields, rfq_id: str, proto_path: Path) -> str:
    """Mapeador determinista. Es el que produce la RFQ que emite el sistema.

    Copia los terminos ya validados, incluidos los calendarios de pago. No genera
    calendarios: el diseno acordado encarga ese calculo al agente, porque con
    periodos rotos el calendario no se deduce de la frecuencia, y saber si un
    modelo de lenguaje lo resuelve es una de las preguntas del trabajo.
    """
    pb = _load_pricing_module(proto_path)
    message = pb.RFQ(rfq_id=rfq_id)
    irs = message.irs
    irs.notional = float(fields.notional)
    irs.currency = fields.currency
    irs.is_fixed_rate_receiver = bool(fields.is_fixed_rate_receiver)
    irs.valuation_date = fields.valuation_date.isoformat()
    irs.effective_date = fields.effective_date.isoformat()
    irs.maturity_date = fields.maturity_date.isoformat()
    irs.discount_curve = fields.discount_curve

    irs.fixed_leg.rate = float(fields.fixed_leg.rate)
    irs.fixed_leg.day_count = fields.fixed_leg.day_count
    irs.fixed_leg.payment_frequency = fields.fixed_leg.payment_frequency
    irs.fixed_leg.payment_dates.extend(
        d.isoformat() for d in fields.fixed_leg.payment_dates
    )

    floating = fields.floating_leg
    irs.floating_leg.rate_type = pb.FloatingRateType.Value(floating.rate_type)
    irs.floating_leg.index = floating.index
    if floating.tenor is not None:
        irs.floating_leg.tenor = floating.tenor
    irs.floating_leg.spread = float(floating.spread or 0)
    irs.floating_leg.day_count = floating.day_count
    irs.floating_leg.payment_frequency = floating.payment_frequency
    irs.floating_leg.forecast_curve = floating.forecast_curve
    irs.floating_leg.payment_dates.extend(
        d.isoformat() for d in floating.payment_dates
    )
    return text_format.MessageToString(message)


def validate_textproto(proto_text: str, proto_path: Path) -> str:
    pb = _load_pricing_module(proto_path)
    message = pb.RFQ()
    text_format.Parse(proto_text, message)
    if not message.HasField("irs"):
        raise ValueError("Generated RFQ does not contain the irs message")
    return text_format.MessageToString(message)


def parse_irs_textproto(proto_text: str, proto_path: Path) -> IRSFields:
    """Lee un InterestRateSwap en texto y lo lleva al modelo de extraccion."""
    pb = _load_pricing_module(proto_path)
    message = pb.InterestRateSwap()
    text_format.Parse(proto_text, message)

    def present(holder, name):
        return getattr(holder, name) if holder.HasField(name) else None

    fixed = message.fixed_leg
    floating = message.floating_leg
    rate_type = present(floating, "rate_type")
    return IRSFields.model_validate({
        "notional": present(message, "notional"),
        "currency": present(message, "currency"),
        "is_fixed_rate_receiver": present(message, "is_fixed_rate_receiver"),
        "valuation_date": present(message, "valuation_date"),
        "effective_date": present(message, "effective_date"),
        "maturity_date": present(message, "maturity_date"),
        "discount_curve": present(message, "discount_curve"),
        "fixed_leg": FixedLegFields.model_validate({
            "rate": present(fixed, "rate"),
            "day_count": present(fixed, "day_count"),
            "payment_frequency": present(fixed, "payment_frequency"),
            "payment_dates": list(fixed.payment_dates),
        }),
        "floating_leg": FloatingLegFields.model_validate({
            # El enum llega como entero; se guarda con su nombre para que el
            # validador y los casos dorados hablen del mismo valor.
            "rate_type": (pb.FloatingRateType.Name(rate_type)
                          if rate_type not in (None, 0) else None),
            "index": present(floating, "index"),
            "tenor": present(floating, "tenor"),
            "spread": present(floating, "spread"),
            "day_count": present(floating, "day_count"),
            "payment_frequency": present(floating, "payment_frequency"),
            "forecast_curve": present(floating, "forecast_curve"),
            "payment_dates": list(floating.payment_dates),
        }),
    })


def textproto_to_json(proto_text: str, proto_path: Path) -> str:
    """Canonical JSON projection of an RFQ. The protobuf text remains the source."""
    pb = _load_pricing_module(proto_path)
    message = pb.RFQ()
    text_format.Parse(proto_text, message)
    return json_format.MessageToJson(message, indent=2, preserving_proto_field_name=True)
