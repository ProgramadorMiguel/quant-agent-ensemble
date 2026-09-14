from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from app_service import PROJECT_ROOT
from evaluation.aggregate import (
    SUCCESS_CRITERION,
    ModelAggregate,
    available_batches,
    evaluated_models,
    latest_batch,
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
    print("  acierto. 'RFQ exacta' = todos los terminos correctos, con Wilson al 95%.")
    print("  'campos' es macro-media por caso y va sin intervalo: los terminos de un")
    print("  caso estan correlacionados y no son ensayos independientes. Cada termino")
    print("  de cada pata cuenta por separado (fixed_leg.day_count y los demas).")
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


FAMILY_QUESTION = {
    "completos": "extrae limpio una peticion completa",
    "incompletos": "detecta lo que falta y no lo inventa",
    "jerga": "entiende la redaccion abreviada de mesa",
    "no_soportados": "rechaza un producto que no sabe tratar",
}


def _batch_filter(batch_id: str | None, column: str = "batch_id") -> tuple[str, tuple]:
    """Clausula y parametros para restringir una consulta a una tanda."""
    if batch_id is None:
        return "", ()
    return f" AND {column} = ?", (batch_id,)


def report_families(store: TelemetryStore, batch_id: str | None = None) -> None:
    """Desglose por familia de caso.

    Un porcentaje global mezcla preguntas distintas y no es interpretable: un
    100% puede venir de casos triviales, y un 70% puede ser excelente si los
    fallos estan en la familia mas dificil.
    """
    clause, params = _batch_filter(batch_id)
    rows = store.query(f"""
        SELECT model, family, case_name,
               MIN(validation_correct), MIN(product_correct)
        FROM evaluation_runs
        WHERE error_text IS NULL AND family IS NOT NULL{clause}
        GROUP BY model, family, case_name
        ORDER BY model, family, case_name
    """, params)
    if not rows:
        return
    rule("Resultado por familia de caso")
    grouped: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for model, family, _case, validation_ok, product_ok in rows:
        grouped.setdefault((model, family), []).append((validation_ok, product_ok))

    current_model = None
    for (model, family), results in grouped.items():
        if model != current_model:
            print(f"\n{model}")
            current_model = model
        n = len(results)
        # En los casos no soportados lo que se mide es la clasificacion: el
        # flujo se detiene en el orquestador y no llega a validarse nada.
        index = 1 if family == "no_soportados" else 0
        ok = sum(1 for r in results if r[index])
        question = FAMILY_QUESTION.get(family, family)
        print(f"   {family:<16} {format_rate(ok, n):<26} {question}")
    print("\n  Cada familia responde a una pregunta distinta, asi que sus tasas no")
    print("  se promedian entre si. El agregado global esta arriba.")


def report_fields(store: TelemetryStore, batch_id: str | None = None) -> None:
    clause, params = _batch_filter(batch_id)
    rows = store.query(
        "SELECT model, field_results FROM evaluation_runs "
        f"WHERE field_results IS NOT NULL AND error_text IS NULL{clause}",
        params,
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


def report_proto_fidelity(store: TelemetryStore, batch_id: str | None = None) -> None:
    clause, params = _batch_filter(batch_id)
    rows = store.query(f"""
        SELECT model, proto_agent_status, COUNT(*)
        FROM evaluation_runs
        WHERE proto_agent_status IS NOT NULL AND error_text IS NULL{clause}
        GROUP BY model, proto_agent_status ORDER BY model
    """, params)
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


def report_agents(store: TelemetryStore, batch_id: str | None = None) -> None:
    # api_calls no lleva batch_id: se acota por los run_id de la tanda.
    clause, params = ("", ())
    if batch_id is not None:
        clause = (" AND run_id IN (SELECT run_id FROM evaluation_runs "
                  "WHERE batch_id = ? AND run_id IS NOT NULL)")
        params = (batch_id,)
    rows = store.query(f"""
        SELECT model, agent, COUNT(*), AVG(latency_ms),
               SUM(input_tokens), SUM(output_tokens), SUM(cost_usd)
        FROM api_calls WHERE status = 'SUCCESS'{clause}
        GROUP BY model, agent ORDER BY model, agent
    """, params)
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
    parser.add_argument("--batch", default=None,
                        help="Identificador de tanda. Por omision, la ultima.")
    parser.add_argument("--all-batches", action="store_true",
                        help="Agrega todas las tandas. Solo tiene sentido si se "
                             "midieron contra las mismas instrucciones y casos.")
    args = parser.parse_args()

    store = TelemetryStore(args.db)
    batches = available_batches(store)

    # Por omision se informa de una sola tanda, la ultima. Agregar tandas medidas
    # contra instrucciones o casos dorados distintos produce cifras que mezclan
    # criterios, y hace aparecer como inestabilidad del modelo lo que en realidad
    # es un cambio de referencia.
    batch_id = None if args.all_batches else (args.batch or latest_batch(store))

    models = evaluated_models(store, batch_id)
    if not models:
        if batch_id and batches:
            print(f"No hay filas para la tanda {batch_id}.")
            print(f"Tandas disponibles: {', '.join(batches)}")
            return 1
        print("Todavia no hay evaluaciones. Lanza:  python src/evaluate.py --models gpt-4.1-mini")
        return 0

    if args.all_batches and len(batches) > 1:
        print(f"AVISO: se agregan {len(batches)} tandas: {', '.join(batches)}.")
        print("Si entre ellas cambio una instruccion o un caso dorado, las cifras")
        print("mezclan criterios y no son publicables.\n")
    elif batch_id:
        print(f"Tanda: {batch_id}"
              + (f"   (hay {len(batches)}; --all-batches para agregarlas)"
                 if len(batches) > 1 else ""))
    legacy = store.query(
        "SELECT COUNT(*) FROM evaluation_runs WHERE batch_id IS NULL")
    legacy_rows = legacy[0][0] if legacy else 0
    if legacy_rows and batch_id is not None:
        print(f"AVISO: {legacy_rows} filas sin identificador de tanda, anteriores a su")
        print("introduccion, quedan fuera de este informe.")
    elif legacy_rows:
        print(f"AVISO: {legacy_rows} filas sin identificador de tanda. Se agregan todas,")
        print("y si entre ellas cambio una instruccion o un caso dorado, las cifras")
        print("mezclan criterios y no son publicables.")

    aggregates = [load_model(store, model, batch_id) for model in models]
    aggregates = [agg for agg in aggregates if agg.n]
    if not aggregates:
        print("Solo hay ejecuciones con error de API. Revisa la clave y la conectividad.")
        return 1

    report_models(aggregates)
    report_families(store, batch_id)
    report_operations(aggregates)
    report_fields(store, batch_id)
    report_proto_fidelity(store, batch_id)
    report_agents(store, batch_id)
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
