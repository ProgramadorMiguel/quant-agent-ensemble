from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from app_service import PROJECT_ROOT
from evaluation.aggregate import (
    SUCCESS_CRITERION,
    ModelAggregate,
    evaluated_models,
    load_model,
    min_discordant_for_significance,
    percentile,
)
from evaluation.costs import unverified_models
from evaluation.metrics import format_rate, mcnemar
from evaluation.telemetry import TelemetryStore


def rule(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def money(value: float | None, digits: int = 4) -> str:
    return f"{value:.{digits}f}" if value is not None else "n/d"


def report_models(aggregates: list[ModelAggregate]) -> None:
    rule("Resumen por modelo")
    print(f"{'modelo':<16} {'casos':>5}  {'producto OK':<24} {'validacion OK':<24} "
          f"{'RFQ exacta':<24} {'campos':>7} {'inv.':>5}")
    for agg in aggregates:
        print(f"{agg.model:<16} {agg.n:>5}  "
              f"{format_rate(agg.successes('product_ok'), agg.n):<24} "
              f"{format_rate(agg.successes('validation_ok'), agg.n):<24} "
              f"{format_rate(agg.successes('exact_ok'), agg.n):<24} "
              f"{agg.field_accuracy_mean:>6.1%} {agg.hallucinated:>5}")

    print(f"\n  Criterio: {SUCCESS_CRITERION}.")
    print("  'validacion OK' = el estado coincide con el que exige el caso dorado:")
    print("  un caso incompleto debe salir INVALID, y rechazarlo bien puntua como")
    print("  acierto. 'RFQ exacta' = los diez campos correctos, con Wilson al 95%.")
    print("  'campos' es macro-media por caso y va sin intervalo: los diez campos")
    print("  de un caso estan correlacionados y no son ensayos independientes.")
    excluded = sum(agg.excluded_errors for agg in aggregates)
    if excluded:
        print(f"\n  Excluidas {excluded} ejecuciones con error de API: un timeout de red")
        print("  no es 'el modelo se dejo los campos'. Se conservan en la base de datos.")


def report_operations(aggregates: list[ModelAggregate]) -> None:
    rule("Latencia y coste extremo a extremo")
    print(f"{'modelo':<16} {'ejec.':>6} {'p50 ms':>8} {'p95 ms':>8} "
          f"{'$/pasada':>10} {'$/caso valido':>14}")
    for agg in aggregates:
        latencies = agg.latencies
        p50, p95 = percentile(latencies, 0.50), percentile(latencies, 0.95)
        print(f"{agg.model:<16} {agg.repetitions:>6} "
              f"{(f'{p50:.0f}' if p50 else 'n/d'):>8} "
              f"{(f'{p95:.0f}' if p95 else 'n/d'):>8} "
              f"{money(agg.cost_usd):>10} {money(agg.cost_per_valid_usd):>14}")
    print("\n  p95 en lugar de la media: en llamadas a API la cola derecha es lo que")
    print("  se nota. '$/caso valido' es el coste real de obtener una RFQ utilizable.")


def report_fields(store: TelemetryStore) -> None:
    rows = store.query(
        "SELECT model, field_results FROM evaluation_runs "
        "WHERE field_results IS NOT NULL AND error_text IS NULL"
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

    rule("En que se equivoca cada modelo")
    print("  (recuento sobre ejecuciones, para diagnostico; no es una tasa con IC)")
    for model in sorted(totals):
        problems = per_model[model]
        if not problems:
            print(f"{model:<16} sin fallos de campo registrados")
            continue
        print(f"{model}")
        for key, count in problems.most_common(10):
            field, outcome = key.split(":")
            print(f"   {field:<20} {outcome:<14} {count:>3} de {totals[model][field]}")


def report_proto_fidelity(store: TelemetryStore) -> None:
    rows = store.query("""
        SELECT model, proto_agent_status, COUNT(*)
        FROM evaluation_runs
        WHERE proto_agent_status IS NOT NULL AND error_text IS NULL
        GROUP BY model, proto_agent_status ORDER BY model
    """)
    if not rows:
        return
    rule("Fidelidad de serializacion del agente proto")
    per_model: dict[str, dict[str, int]] = defaultdict(dict)
    for model, status, count in rows:
        per_model[model][status] = count
    for model, counts in per_model.items():
        # NOT_RUN = la validacion detuvo el caso antes de llegar al agente. No es
        # un fallo suyo, asi que queda fuera del denominador.
        ran = sum(count for status, count in counts.items() if status != "NOT_RUN")
        match = counts.get("MATCH", 0)
        detail = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()) if k != "MATCH")
        print(f"{model:<16} coincide con el mapeador: {format_rate(match, ran)}"
              + (f"   {detail}" if detail else ""))
    print()
    print("  El mapeador determinista es el que produce la RFQ que usa el sistema.")
    print("  Esta tasa mide si el agente habria hecho el mismo trabajo, para decidir")
    print("  si compensa lo que cuesta. Denominador = ejecuciones, no casos.")


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
              f"{money(cost):>9}")


def report_stability(aggregates: list[ModelAggregate]) -> None:
    repeated = [agg for agg in aggregates
                if any(case.repetitions > 1 for case in agg.cases)]
    if not repeated:
        return
    rule("Estabilidad entre repeticiones")
    for agg in repeated:
        cases = [c for c in agg.cases if c.repetitions > 1]
        unstable = [c for c in cases if not c.stable]
        print(f"{agg.model:<16} {len(cases) - len(unstable)}/{len(cases)} casos estables")
        for case in unstable:
            print(f"   {case.case_name:<28} {case.repetitions} ejecuciones -> "
                  f"{case.distinct_results} resultados distintos")


def report_comparison(aggregates: list[ModelAggregate]) -> None:
    if len(aggregates) < 2:
        return
    rule("Comparacion pareada entre modelos (McNemar)")
    threshold = min_discordant_for_significance()
    for i, first in enumerate(aggregates):
        for second in aggregates[i + 1:]:
            a = {c.case_name: c.validation_ok for c in first.cases}
            b = {c.case_name: c.validation_ok for c in second.cases}
            shared = sorted(set(a) & set(b))
            if not shared:
                continue
            only_a, only_b, p = mcnemar([a[c] for c in shared], [b[c] for c in shared])
            discordant = only_a + only_b
            if discordant < threshold:
                verdict = (f"sin potencia (hacen falta >= {threshold} pares "
                           f"discordantes, hay {discordant})")
            elif p < 0.05:
                verdict = "diferencia significativa"
            else:
                verdict = "sin evidencia de diferencia"
            print(f"{first.model} vs {second.model}: {len(shared)} casos comunes | "
                  f"solo {first.model}: {only_a} | solo {second.model}: {only_b} | "
                  f"p = {p:.3f} -> {verdict}")
    print(f"\n  El binomial exacto no puede bajar de 0,05 con menos de {threshold} pares")
    print("  discordantes. Por debajo de ese umbral el resultado es falta de potencia,")
    print("  no ausencia de diferencia: no se debe redactar como empate.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Informe comparativo de modelos")
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "outputs/evaluations.db")
    args = parser.parse_args()

    store = TelemetryStore(args.db)
    models = evaluated_models(store)
    if not models:
        print("Todavia no hay evaluaciones. Lanza:  python src/evaluate.py --models gpt-4.1-mini")
        return 0

    aggregates = [load_model(store, model) for model in models]
    aggregates = [agg for agg in aggregates if agg.n]
    if not aggregates:
        print("Solo hay ejecuciones con error de API. Revisa la clave y la conectividad.")
        return 1

    report_models(aggregates)
    report_operations(aggregates)
    report_fields(store)
    report_proto_fidelity(store)
    report_agents(store)
    report_stability(aggregates)
    report_comparison(aggregates)

    pending = unverified_models(PROJECT_ROOT)
    if pending:
        print(f"\nAviso: tarifas sin verificar en config/model_costs.toml -> "
              f"{', '.join(pending)}.\nLos costes de esos modelos son orientativos; "
              f"verificalos antes de citarlos en la memoria.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
