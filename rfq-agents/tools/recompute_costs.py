"""Recalcula los costes registrados a partir de los tokens y las tarifas actuales.

El coste se calcula en el momento de la llamada y se guarda en la fila, de modo
que una tanda medida antes de corregir una tarifa queda con el coste antiguo. Los
tokens, en cambio, son un hecho de la ejecucion y no cambian: recalcular desde
ellos permite corregir una tarifa sin volver a gastar en la API.

Ejecutar desde la raiz del proyecto:

    python tools/recompute_costs.py                 muestra lo que cambiaria
    python tools/recompute_costs.py --apply         lo escribe
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evaluation.costs import cost_of  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "outputs/evaluations.db")
    parser.add_argument("--apply", action="store_true",
                        help="escribe los costes; sin esta opcion solo informa")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"No existe {args.db}")
        return 1

    connection = sqlite3.connect(args.db)
    rows = connection.execute("""
        SELECT call_id, model, input_tokens, output_tokens, cached_input_tokens,
               cost_usd
        FROM api_calls WHERE status = 'SUCCESS' AND input_tokens IS NOT NULL
    """).fetchall()

    changes: list[tuple[int, float | None]] = []
    por_modelo: dict[str, list[float]] = {}
    for call_id, model, entrada, salida, cache, antiguo in rows:
        nuevo = cost_of(ROOT, model, entrada, salida, cache)
        if nuevo is None or (antiguo is not None and abs(nuevo - antiguo) < 1e-12):
            continue
        changes.append((call_id, nuevo))
        por_modelo.setdefault(model, []).append((nuevo or 0) - (antiguo or 0))

    if not changes:
        print("Nada que recalcular: los costes ya corresponden a las tarifas actuales.")
        return 0

    print(f"{len(changes)} llamadas con el coste desactualizado:\n")
    for model, diferencias in sorted(por_modelo.items()):
        total = sum(diferencias)
        signo = "+" if total >= 0 else ""
        print(f"  {model:<22} {len(diferencias):>4} llamadas   {signo}{total:.4f} USD")

    if not args.apply:
        print("\nEjecuta con --apply para escribirlo.")
        return 0

    connection.executemany(
        "UPDATE api_calls SET cost_usd = ? WHERE call_id = ?",
        [(coste, call_id) for call_id, coste in changes],
    )
    # El coste de cada caso es la suma de sus llamadas, asi que hay que rehacerlo
    # despues de tocar api_calls.
    connection.execute("""
        UPDATE evaluation_runs SET cost_usd = (
            SELECT SUM(cost_usd) FROM api_calls
            WHERE api_calls.run_id = evaluation_runs.run_id
              AND cost_usd IS NOT NULL
        ) WHERE run_id IS NOT NULL
    """)
    connection.commit()
    print("\nEscrito.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
