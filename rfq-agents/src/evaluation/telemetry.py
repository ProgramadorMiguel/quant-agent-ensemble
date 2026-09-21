from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS api_calls (
    call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agent TEXT NOT NULL,
    model TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    status TEXT NOT NULL,
    request_text TEXT NOT NULL,
    response_text TEXT,
    error_text TEXT
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
    evaluation_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    model TEXT NOT NULL,
    case_name TEXT NOT NULL,
    product_correct INTEGER NOT NULL,
    validation_correct INTEGER NOT NULL,
    matched_fields INTEGER NOT NULL,
    total_fields INTEGER NOT NULL,
    field_accuracy REAL NOT NULL,
    elapsed_ms REAL NOT NULL,
    output_path TEXT,
    error_text TEXT
);
"""

# Columns added after the first version of the schema. Existing databases are
# migrated in place so historical rows are never lost.
ADDED_COLUMNS = {
    "api_calls": {
        "provider": "TEXT",
        "prompt_hash": "TEXT",       # identifies the agent instructions actually used
        "cached_input_tokens": "INTEGER",
        "cost_usd": "REAL",
    },
    "evaluation_runs": {
        "provider": "TEXT",
        "run_id": "TEXT",            # links back to the api_calls of this evaluation
        "repetition": "INTEGER",
        "topology": "TEXT",          # 'pipeline' or 'monolithic'
        "product_type": "TEXT",
        "field_results": "TEXT",     # JSON: field -> MATCH/WRONG/MISSING/HALLUCINATED
        "hallucinated_fields": "TEXT",
        "wrong_fields": "INTEGER",
        "missing_fields_count": "INTEGER",
        "hallucinated_count": "INTEGER",
        "proto_agent_status": "TEXT",   # MATCH / MISMATCH / UNPARSEABLE / NOT_RUN
        "cost_usd": "REAL",
        # Lo que el caso dorado exige. Sin esto no se puede distinguir "fallo"
        # de "rechazo correcto": un caso incompleto DEBE salir INVALID.
        "expected_status": "TEXT",          # VALID / INVALID / NOT_RUN
        "expected_product_type": "TEXT",    # IRS / UNSUPPORTED
        # Familia del caso: completos, incompletos, jerga, no_soportados. Un
        # porcentaje global mezcla las tres y no dice nada; separadas, cada
        # familia responde a una pregunta distinta.
        "family": "TEXT",
        # Identificador de la tanda a la que pertenece la fila.
        #
        # La base de datos acumula ejecuciones, y entre una tanda y otra pueden
        # cambiar las instrucciones de un agente o un caso dorado. Sin este
        # identificador, el informe agrega filas medidas con criterios distintos
        # y sus cifras dejan de ser interpretables: dos resultados discrepantes
        # del mismo caso aparecen como inestabilidad del modelo cuando en
        # realidad reflejan un cambio de referencia.
        "batch_id": "TEXT",
        # Pasadas del bucle de autocorreccion que ha necesitado el caso. 1 es a la
        # primera. Permite medir cuanto aporta el bucle: si casi todo se resuelve
        # en la primera pasada, cuesta latencia y no compensa.
        "iterations": "INTEGER",
        # Temperatura y fecha de referencia con las que se midio la fila. Sin
        # ellas una tanda no es reproducible ni comparable: son los dos
        # parametros que se barren en los experimentos.
        "temperature": "REAL",
        "as_of": "TEXT",
    },
}


class TelemetryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        for table, columns in ADDED_COLUMNS.items():
            existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, sql_type in columns.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _insert(self, table: str, values: dict) -> None:
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )

    def record_call(
        self, *, run_id: str, agent: str, model: str, latency_ms: float,
        status: str, request_text: str, response_text: str | None = None,
        error_text: str | None = None, input_tokens: int | None = None,
        output_tokens: int | None = None, total_tokens: int | None = None,
        provider: str | None = None, prompt_hash: str | None = None,
        cached_input_tokens: int | None = None, cost_usd: float | None = None,
    ) -> None:
        self._insert("api_calls", {
            "call_id": str(uuid4()), "run_id": run_id, "agent": agent, "model": model,
            "latency_ms": latency_ms, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "total_tokens": total_tokens,
            "status": status, "request_text": request_text,
            "response_text": response_text, "error_text": error_text,
            "provider": provider, "prompt_hash": prompt_hash,
            "cached_input_tokens": cached_input_tokens, "cost_usd": cost_usd,
        })

    def record_evaluation(self, **values) -> None:
        self._insert("evaluation_runs", values)

    def query(self, sql: str, parameters: tuple = ()) -> list[tuple]:
        with self.connect() as connection:
            return connection.execute(sql, parameters).fetchall()
