from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

from google.protobuf import text_format
from grpc_tools import protoc

from models.irs_fields import IRSFields


def _load_pricing_module(proto_path: Path):
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
    """Deterministic mapper useful for tests and non-LLM fallback tooling."""
    pb = _load_pricing_module(proto_path)
    message = pb.RFQ(rfq_id=rfq_id)
    irs = message.irs
    irs.notional = float(fields.notional)
    irs.currency = fields.currency
    irs.direction = getattr(pb.InterestRateSwap, fields.direction)
    irs.effective_date = fields.effective_date.isoformat()
    irs.maturity_date = fields.maturity_date.isoformat()
    irs.fixed_rate = float(fields.fixed_rate)
    irs.floating_index = fields.floating_index
    irs.floating_tenor = fields.floating_tenor
    irs.discount_curve = fields.discount_curve
    irs.forwarding_curve = fields.forwarding_curve
    return text_format.MessageToString(message)


def validate_textproto(proto_text: str, proto_path: Path) -> str:
    pb = _load_pricing_module(proto_path)
    message = pb.RFQ()
    text_format.Parse(proto_text, message)
    if not message.HasField("irs"):
        raise ValueError("Generated RFQ does not contain the irs message")
    return text_format.MessageToString(message)


def parse_irs_textproto(proto_text: str, proto_path: Path) -> IRSFields:
    pb = _load_pricing_module(proto_path)
    message = pb.InterestRateSwap()
    text_format.Parse(proto_text, message)

    def present(name: str):
        return getattr(message, name) if message.HasField(name) else None

    direction = None
    if message.HasField("direction"):
        direction = pb.InterestRateSwap.Direction.Name(message.direction)
    return IRSFields.model_validate({
        "notional": present("notional"), "currency": present("currency"),
        "direction": direction, "effective_date": present("effective_date"),
        "maturity_date": present("maturity_date"), "fixed_rate": present("fixed_rate"),
        "floating_index": present("floating_index"),
        "floating_tenor": present("floating_tenor"),
        "discount_curve": present("discount_curve"),
        "forwarding_curve": present("forwarding_curve"),
    })
