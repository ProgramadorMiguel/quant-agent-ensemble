from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

# Criterio de acierto, declarado en un solo sitio porque el tribunal preguntara
# por el: la unidad de analisis es el CASO, no la ejecucion. Un caso cuenta como
# acierto solo si acierta en todas sus repeticiones.
#
# Motivo: las repeticiones de un mismo prompt no son observaciones
# independientes. Tratarlas como tales infla artificialmente el tamano de
# muestra y estrecha los intervalos de confianza, que es el peor error posible
# en un capitulo de resultados: aparenta una precision que no se tiene. Las
# repeticiones sirven para medir estabilidad, no para agrandar N.
SUCCESS_CRITERION = (
    "unidad de analisis = caso (n = numero de casos, no de ejecuciones); "
    "un caso acierta solo si acierta en TODAS sus repeticiones"
)


@dataclass(frozen=True)
class CaseAggregate:
    """Un caso, colapsado sobre sus repeticiones."""

    case_name: str
    repetitions: int
    product_ok: bool
    validation_ok: bool
    exact_ok: bool                 # los 10 campos correctos en todas las reps
    scored: bool                   # el caso tiene campos que puntuar
    field_accuracy_mean: float     # media de las reps de este caso
    hallucinated: int              # total de campos inventados en las reps
    stable: bool                   # todas las reps dieron el mismo resultado
    distinct_results: int
    latencies: tuple[float, ...]
    cost_usd: float | None         # coste medio de una ejecucion del caso


@dataclass(frozen=True)
class ModelAggregate:
    model: str
    cases: tuple[CaseAggregate, ...]
    excluded_errors: int           # filas con error de API, fuera del agregado

    @property
    def n(self) -> int:
        return len(self.cases)

    def successes(self, attribute: str) -> int:
        return sum(1 for case in self.cases if getattr(case, attribute))

    @property
    def repetitions(self) -> int:
        return sum(case.repetitions for case in self.cases)

    @property
    def field_accuracy_mean(self) -> float:
        """Macro-media sobre casos: cada caso pesa igual, no cada campo.

        No se le pone intervalo de Wilson: los diez campos de un caso estan
        correlacionados y no son ensayos de Bernoulli independientes.
        """
        scored = [c.field_accuracy_mean for c in self.cases if c.scored]
        return mean(scored) if scored else 0.0

    @property
    def hallucinated(self) -> int:
        return sum(case.hallucinated for case in self.cases)

    @property
    def latencies(self) -> list[float]:
        return [ms for case in self.cases for ms in case.latencies]

    @property
    def cost_usd(self) -> float | None:
        values = [case.cost_usd for case in self.cases if case.cost_usd is not None]
        return sum(values) if values else None

    @property
    def cost_per_valid_usd(self) -> float | None:
        """Coste de una pasada completa dividido entre los casos que salen bien.

        Es la cifra que importa: un modelo barato que falla la mitad de las
        veces no es barato.
        """
        total, ok = self.cost_usd, self.successes("validation_ok")
        return total / ok if total is not None and ok else None

    @property
    def unstable(self) -> tuple[CaseAggregate, ...]:
        return tuple(c for c in self.cases if not c.stable)


ROWS_SQL = """
    SELECT case_name, product_correct, validation_correct, matched_fields,
           total_fields, COALESCE(hallucinated_count, 0), field_results,
           elapsed_ms, cost_usd
    FROM evaluation_runs
    WHERE model = ? AND error_text IS NULL
"""

ERRORS_SQL = (
    "SELECT COUNT(*) FROM evaluation_runs WHERE model = ? AND error_text IS NOT NULL"
)

MODELS_SQL = "SELECT DISTINCT model FROM evaluation_runs"

BATCHES_SQL = (
    "SELECT DISTINCT batch_id FROM evaluation_runs "
    "WHERE batch_id IS NOT NULL ORDER BY batch_id"
)


def _scoped(sql: str, batch_id: str | None) -> str:
    """Restringe una consulta a una tanda concreta.

    Filtrar por tanda no es cosmetico: entre una tanda y otra pueden cambiar las
    instrucciones de un agente o un caso dorado, y agregar filas medidas contra
    referencias distintas produce cifras que no significan nada.
    """
    return sql if batch_id is None else f"{sql} AND batch_id = ?"


def _params(model: str, batch_id: str | None) -> tuple:
    return (model,) if batch_id is None else (model, batch_id)


def available_batches(store) -> list[str]:
    return [row[0] for row in store.query(BATCHES_SQL)]


def latest_batch(store) -> str | None:
    batches = available_batches(store)
    return batches[-1] if batches else None


def evaluated_models(store, batch_id: str | None = None) -> list[str]:
    sql = MODELS_SQL if batch_id is None else f"{MODELS_SQL} WHERE batch_id = ?"
    params = () if batch_id is None else (batch_id,)
    return sorted(row[0] for row in store.query(sql, params))


def load_model(store, model: str, batch_id: str | None = None) -> ModelAggregate:
    grouped: dict[str, list[tuple]] = {}
    for row in store.query(_scoped(ROWS_SQL, batch_id), _params(model, batch_id)):
        grouped.setdefault(row[0], []).append(row)
    errors = store.query(_scoped(ERRORS_SQL, batch_id), _params(model, batch_id))
    return ModelAggregate(
        model=model,
        cases=tuple(_case(name, rows) for name, rows in sorted(grouped.items())),
        excluded_errors=errors[0][0] if errors else 0,
    )


def _case(name: str, rows: list[tuple]) -> CaseAggregate:
    # Un caso UNSUPPORTED no tiene campos que extraer: cuenta para la
    # clasificacion de producto, pero no debe entrar en la exactitud de campos
    # con un 0% que no significa nada.
    accuracies = [row[3] / row[4] for row in rows if row[4]]
    costs = [row[8] for row in rows if row[8] is not None]
    signatures = {row[6] for row in rows if row[6] is not None}
    return CaseAggregate(
        case_name=name,
        repetitions=len(rows),
        product_ok=all(row[1] for row in rows),
        validation_ok=all(row[2] for row in rows),
        exact_ok=all(row[3] == row[4] for row in rows),
        scored=bool(accuracies),
        field_accuracy_mean=mean(accuracies) if accuracies else 0.0,
        hallucinated=sum(row[5] for row in rows),
        stable=len(signatures) <= 1,
        distinct_results=len(signatures),
        latencies=tuple(row[7] for row in rows if row[7] is not None),
        cost_usd=(sum(costs) / len(costs)) if costs else None,
    )


def percentile(values: list[float], fraction: float) -> float | None:
    """Percentil por interpolacion lineal. La media no sirve para latencias de
    API: la cola derecha es lo que se nota en una mesa."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def min_discordant_for_significance(alpha: float = 0.05) -> int:
    """Pares discordantes minimos para que McNemar exacto pueda bajar de alpha.

    Con el binomial exacto bilateral el mejor caso posible es p = 2^(1-n). Con
    menos pares que este umbral el test no puede dar significativo ni aunque el
    resultado sea unanime: la conclusion seria falta de potencia, no ausencia de
    diferencia.
    """
    n = 1
    while 2.0 ** (1 - n) > alpha:
        n += 1
    return n
