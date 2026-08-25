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
