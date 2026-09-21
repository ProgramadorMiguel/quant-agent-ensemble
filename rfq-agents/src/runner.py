"""Interfaz de linea de comandos para una peticion suelta.

Tres formas de dar la peticion:

    python src/runner.py --input examples/eur_minimal.txt   desde un fichero
    python src/runner.py --prompt "Value as of ..."         en la propia orden
    python src/runner.py                                    escribiendola a mano

Sin argumentos entra en modo interactivo: escribe la peticion en varias lineas y
cierra con una linea vacia. Es la via para probar un swap concreto sin crear un
fichero, que es lo habitual cuando se explora como responde el sistema a una
variante nueva.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from app_service import generate_rfq_from_prompt


BANNER = """\
Escribe la peticion del swap y cierra con una linea vacia.
Ctrl+C para salir.

Terminos obligatorios: fecha de valoracion, inicio, vencimiento, divisa (EUR o
USD), nocional, tipo fijo, y quien paga o recibe el fijo. El resto lo deriva el
sistema de la convencion de mercado.

Ejemplo:
  Value as of 2026-09-01 a vanilla EUR interest rate swap with notional
  EUR 10,000,000, effective 2026-09-01 and maturing 2031-09-01. We pay fixed
  at 2.75%.
"""


def read_interactive() -> str:
    """Lee una peticion de varias lineas de la entrada estandar."""
    print(BANNER)
    lines: list[str] = []
    while True:
        try:
            line = input("... " if lines else ">>> ")
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            continue  # una linea vacia al principio no cierra nada
        lines.append(line)
    return "\n".join(lines)


def report(result) -> None:
    print(f"\n1. Clasificacion de producto: {result.product_type}")

    print("2. Terminos extraidos:")
    for name, value in result.extracted_fields.items():
        if isinstance(value, dict):
            print(f"   {name}:")
            for sub_name, sub_value in value.items():
                if sub_value is None:
                    continue
                if isinstance(sub_value, list):
                    # El calendario se resume: en un swap a diez anos son veinte
                    # fechas y listarlas entorpece la lectura.
                    shown = ", ".join(str(d) for d in sub_value[:3])
                    tail = f" ... {sub_value[-1]}" if len(sub_value) > 4 else ""
                    print(f"      {sub_name}: {len(sub_value)} fechas "
                          f"[{shown}{tail}]")
                else:
                    print(f"      {sub_name}: {sub_value}")
        elif value is not None:
            print(f"   {name}: {value}")

    print(f"3. Validacion: {result.validation_status}")
    if result.missing_fields:
        print("   La peticion no enuncia estos terminos y no se derivan de nada:")
        for item in result.missing_fields:
            print(f"      - {item}")
    if result.validation_errors:
        print("   Errores:")
        for item in result.validation_errors:
            print(f"      - {item}")

    print(f"4. Pasadas del bucle de autocorreccion: {result.iterations}")
    for number, errors in enumerate(result.iteration_errors, start=1):
        print(f"   pasada {number} rechazada por:")
        for item in errors:
            print(f"      - {item}")

    # Contrato de salida: o una RFQ bien conformada, o un motivo. Nunca ambas
    # cosas a medias, y nunca una RFQ con huecos rellenados a ojo.
    print()
    if result.output_file_path:
        print("RFQ GENERADA")
        print(f"  {result.output_file_path}")
    elif result.product_type != "IRS":
        print("NO SE PUEDE GENERAR RFQ")
        print("  El producto no es un swap de tipos vanilla en EUR o USD con")
        print("  vencimiento de un ano o mas, que es el alcance del sistema.")
    elif result.missing_fields:
        print("NO SE PUEDE GENERAR RFQ")
        print("  Faltan terminos que la peticion no enuncia y que no se derivan")
        print("  de ninguna convencion. Anadelos y vuelve a pedirlo.")
    else:
        print("NO SE PUEDE GENERAR RFQ")
        print("  La peticion es incoherente y el sistema no ha logrado")
        print(f"  corregirla en {result.iterations} pasadas.")

    print(f"\nFidelidad del agente proto: {result.proto_agent.status}"
          + (f" ({result.proto_agent.error})" if result.proto_agent.error else ""))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera una RFQ de swap de tipos vanilla en protobuf",
        epilog="Sin --input ni --prompt, la peticion se escribe a mano.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, help="fichero de texto UTF-8")
    source.add_argument("--prompt", help="peticion en la propia orden")
    parser.add_argument("--model", help="sobreescribe el modelo de agents.yaml")
    parser.add_argument("--max-iterations", type=int, default=None,
                        help="cota de pasadas del bucle de autocorreccion")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None,
                        help="fecha de referencia YYYY-MM-DD, por omision hoy. "
                             "Resuelve 'spot' y las fechas relativas")
    args = parser.parse_args()

    try:
        if args.input:
            prompt = args.input.read_text(encoding="utf-8")
        elif args.prompt:
            prompt = args.prompt
        else:
            prompt = read_interactive()
        if not prompt.strip():
            print("No se ha dado ninguna peticion.", file=sys.stderr)
            return 1
        result = generate_rfq_from_prompt(
            prompt, model_override=args.model,
            max_iterations=args.max_iterations, as_of=args.as_of,
        )
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    report(result)
    return 0 if result.validation_status == "VALID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
