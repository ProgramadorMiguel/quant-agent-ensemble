# RFQ Agents MVP

A Python MVP that turns a natural-language vanilla interest rate swap request
into an `RFQ` protobuf text-format file. Agents are Markdown steering files;
Python is execution infrastructure only. The MVP does not price trades, use
QuantLib, create a separate textual RFQ, or support products other than IRS.

## Flow

1. The orchestrator agent classifies the prompt (`IRS` or `UNSUPPORTED`).
2. The product specialist follows the IRS extraction skill and returns an
   `InterestRateSwap` protobuf text-format message.
3. Python validates all required terms and writes a validation report.
4. For valid requests, the RFQ proto agent emits protobuf text, which Python
   parses against `protos/pricing.proto` before saving it.

`src/app_service.py` owns this flow. Its
`generate_rfq_from_prompt(prompt: str) -> RFQGenerationResult` function is the
stable boundary for the CLI and a future Streamlit UI.

## Setup

Python 3.10 or newer is recommended.

```powershell
cd rfq-agents
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and replace the placeholder with a real OpenAI API key. The key is
never committed. `LLM_MODEL` defaults to `gpt-4.1-mini`.

## Run

```powershell
python src/runner.py --input examples/valid_irs_prompt.txt
```

The CLI prints the classification, extracted fields, validation report, and RFQ
path. Every classified IRS writes `outputs/validation_<id>.txt`. A valid request
also writes `outputs/rfq_<id>.textproto`. Invalid requests stop before protobuf
generation and return exit code 2. Missing configuration or API errors return 1.

Try the deterministic failure path with:

```powershell
python src/runner.py --input examples/incomplete_irs_prompt.txt
```

## Test

Tests do not call OpenAI and do not require an API key.

```powershell
pytest -q
```

The protobuf mapper compiles `pricing.proto` into the operating system's
temporary directory at runtime; generated Python files are not source agents and
are not committed.

## API telemetry and model evaluation

Every OpenAI call is recorded in `outputs/evaluations.db` (SQLite), including
run ID, agent, model, latency, input/output/total tokens, success or error,
request, response, and error details. No API key is stored.

Run the same golden cases against one or more models with:

```powershell
python src/evaluate.py --models gpt-4.1-mini gpt-4.1
```

Golden cases live under `evaluation/cases` as prompt files paired with expected
`InterestRateSwap` `.textproto` files. The evaluator reports product and
validation correctness, exact field accuracy, end-to-end latency, and output
path. Aggregate rows and the underlying per-agent calls are retained in SQLite
for later comparison. RFQs and expected financial structures remain protobuf
text format; JSON is not used as an interchange format.
Each evaluation also writes a report named `<case>__<model>.result.txt` next to
the case under `evaluation/cases`, making the model explicit in every result.

## Agent configuration

The agent network is declared in `config/agents.yaml`. That file is the single
source of truth for the pipeline: each agent lists its Markdown instruction
file, its optional product skill and its optional `.proto` schema, and the
`pipeline` key fixes the execution order. `src/llm_client.py` reads it at
runtime, so adding or reordering agents does not require touching Python.

The system prompt of each agent is built as
`instructions + skill + schema`, in that order.

The deterministic validation layer sits between `product_specialist` and
`rfq_proto`. It is Python, not an agent, and is therefore not listed in the
pipeline.

## Sample RFQs

`samples/` holds RFQs produced end to end by the agent network from the prompts
in `examples/`. Filenames match, so `examples/<case>.txt` is the request that
produced `samples/<case>.textproto`.

Protobuf text format is the only output written by default: JSON is not an
interchange format in this project. Pass `--json` to also emit the canonical
JSON projection when a reader needs it.

Prompts that omit required terms produce `<case>.rejected.txt` instead,
reporting which fields were missing. No RFQ is emitted.

Regenerate the whole set with:

```powershell
python src/generate_batch.py
```

Optional flags: `--prompts <dir>`, `--out <dir>`, `--model <model>`.

## Evaluation and metrics

Golden cases live in `evaluation/cases/` as a `.prompt.txt` / `.expected.textproto`
pair. Run the agent network against all of them:

```powershell
python src/evaluate.py --models gpt-4.1-mini
python src/evaluate.py --models gpt-4.1-mini gpt-4.1 --repetitions 5
```

Every field is classified as `MATCH`, `WRONG` (a value was extracted but is not
the expected one), `MISSING` (stated in the prompt, dropped by the model) or
`HALLUCINATED` (never stated, invented by the model). Keeping those four apart is
what turns "94% accuracy" into a diagnosis.

Results accumulate in `outputs/evaluations.db`. Print the comparison with:

```powershell
python src/report.py
```

The report covers per-model accuracy with 95% Wilson confidence intervals, the
per-field failure breakdown, cost and latency per agent, run-to-run stability
across repetitions, and a paired McNemar test when two or more models share
cases. Model prices are declared in `config/model_costs.toml`; unverified entries
are flagged in the report rather than silently trusted.

### Proto agent fidelity

The RFQ the system emits is always produced by the deterministic mapper. The
proto agent still runs, but only as a measured subject: its output is normalised,
compared against the mapper and recorded as `MATCH`, `MISMATCH`, `UNPARSEABLE` or
`NOT_RUN`. A mismatch never aborts a run that already holds a valid RFQ.

This turns "can an LLM serialise correctly against a schema it is given?" into a
number, which — read next to that agent's share of the token bill — is what
decides whether the stage earns its place.
