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


class TelemetryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def record_call(
        self, *, run_id: str, agent: str, model: str, latency_ms: float,
        status: str, request_text: str, response_text: str | None = None,
        error_text: str | None = None, input_tokens: int | None = None,
        output_tokens: int | None = None, total_tokens: int | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO api_calls VALUES
                (?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), run_id, agent, model, latency_ms, input_tokens,
                 output_tokens, total_tokens, status, request_text,
                 response_text, error_text),
            )

    def record_evaluation(self, **values) -> None:
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO evaluation_runs ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
