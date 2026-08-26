from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from app_service import PROJECT_ROOT
from evaluation.costs import unverified_models
from evaluation.metrics import format_rate, mcnemar
from evaluation.telemetry import TelemetryStore


def rule(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def report_models(store: TelemetryStore) -> list[str]:
    rows = store.query("""
        SELECT model,
               COUNT(*),
               SUM(product_correct),
               SUM(validation_correct),
               SUM(matched_fields),
               SUM(total_fields),
               SUM(COALESCE(hallucinated_count, 0)),
               AVG(elapsed_ms),
               SUM(cost_usd)
        FROM evaluation_runs GROUP BY model ORDER BY model
    """)
    if not rows:
        print("Todavía no hay evaluaciones. Lanza:  python src/evaluate.py --models gpt-4.1-mini")
        return []

    rule("Resumen por modelo")
    print(f"{'modelo':<16} {'casos':>5}  {'producto OK':<26} {'campos OK':<26} "
          f"{'inventados':>10} {'ms':>7} {'coste $':>9}")
    models = []
    for (model, n, prod, valid, matched, total, halluc, ms, cost) in rows:
        models.append(model)
        print(f"{model:<16} {n:>5}  {format_rate(prod or 0, n):<26} "
              f"{format_rate(matched or 0, total or 0):<26} "
              f"{halluc or 0:>10} {ms or 0:>7.0f} "
              f"{('%.4f' % cost) if cost is not None else 'n/d':>9}")
    print("\n  [x-y] = intervalo de confianza al 95%. Con pocos casos, un 100% "
          "sigue siendo compatible\n  con una tasa real bastante más baja.")
    return models


def report_fields(store: TelemetryStore) -> None:
    rows = store.query(
        "SELECT model, field_results FROM evaluation_runs WHERE field_results IS NOT NULL"
    )
    if not rows:
        return
    per_model: dict[str, Counter] = defaultdict(Counter)
    totals: dict[str, Counter] = defaultdict(Counter)
    for model, blob in rows:
        for field, outcome in json.loads(blob).items():
            totals[model][field] += 1
            if outcome != "MATCH":
                per_model[model][f"{field}:{outcome}"] += 1

    rule("En qué se equivoca cada modelo")
    for model in sorted(totals):
        problems = per_model[model]
        if not problems:
            print(f"{model:<16} sin fallos de campo registrados")
            continue
        print(f"{model}")
        for key, count in problems.most_common(10):
            field, outcome = key.split(":")
            print(f"   {field:<20} {outcome:<14} {count:>3} de {totals[model][field]}")


def report_agents(store: TelemetryStore) -> None:
    rows = store.query("""
        SELECT model, agent, COUNT(*), AVG(latency_ms),
               SUM(input_tokens), SUM(output_tokens), SUM(cost_usd)
        FROM api_calls WHERE status = 'SUCCESS'
        GROUP BY model, agent ORDER BY model, agent
    """)
    if not rows:
        return
    rule("Coste y latencia por agente")
    print(f"{'modelo':<16} {'agente':<20} {'llamadas':>8} {'ms medios':>10} "
          f"{'tok in':>8} {'tok out':>8} {'coste $':>9}")
    for model, agent, n, ms, tin, tout, cost in rows:
        print(f"{model:<16} {agent:<20} {n:>8} {ms:>10.0f} {tin or 0:>8} {tout or 0:>8} "
              f"{('%.4f' % cost) if cost is not None else 'n/d':>9}")


def report_stability(store: TelemetryStore) -> None:
    rows = store.query("""
        SELECT model, case_name, COUNT(DISTINCT field_results), COUNT(*)
        FROM evaluation_runs WHERE field_results IS NOT NULL
        GROUP BY model, case_name HAVING COUNT(*) > 1
    """)
    if not rows:
        return
    rule("Estabilidad entre repeticiones")
    for model, case, distinct, n in rows:
        verdict = "estable" if distinct == 1 else f"{distinct} resultados distintos"
        print(f"{model:<16} {case:<28} {n} ejecuciones -> {verdict}")


def report_comparison(store: TelemetryStore, models: list[str]) -> None:
    if len(models) < 2:
        return
    rule("Comparación pareada entre modelos (McNemar)")
    for i, a in enumerate(models):
        for b in models[i + 1:]:
            rows_a = dict(store.query(
                "SELECT case_name, MIN(validation_correct) FROM evaluation_runs "
                "WHERE model = ? GROUP BY case_name", (a,)))
            rows_b = dict(store.query(
                "SELECT case_name, MIN(validation_correct) FROM evaluation_runs "
                "WHERE model = ? GROUP BY case_name", (b,)))
            shared = sorted(set(rows_a) & set(rows_b))
            if not shared:
                continue
            only_a, only_b, p = mcnemar([bool(rows_a[c]) for c in shared],
                                        [bool(rows_b[c]) for c in shared])
            verdict = "diferencia significativa" if p < 0.05 else "sin evidencia de diferencia"
            print(f"{a} vs {b}: {len(shared)} casos comunes | "
                  f"solo {a}: {only_a} | solo {b}: {only_b} | p = {p:.3f} -> {verdict}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Informe comparativo de modelos")
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "outputs/evaluations.db")
    args = parser.parse_args()

    store = TelemetryStore(args.db)
    models = report_models(store)
    if models:
        report_fields(store)
        report_agents(store)
        report_stability(store)
        report_comparison(store, models)

    pending = unverified_models(PROJECT_ROOT)
    if pending:
        print(f"\nAviso: tarifas sin verificar en config/model_costs.toml -> "
              f"{', '.join(pending)}.\nLos costes de esos modelos son orientativos; "
              f"verifícalos antes de citarlos en la memoria.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
