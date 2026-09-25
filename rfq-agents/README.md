# RFQ Agents

Python prototype that converts natural-language vanilla interest-rate swap requests into validated `RFQ` messages in Protocol Buffers text format. The system interprets and validates requests; it does not price trades or calculate risk.

## Scope

- Vanilla IRS in EUR and USD.
- Nominal maturity of at least one year.
- Par-rate quotations and valuations.
- Spanish, English and trading-desk shorthand.
- Explicit rejection of unsupported, incomplete or inconsistent requests.

## Architecture

1. **Orchestrator agent:** classifies the request as `IRS` or `UNSUPPORTED`.
2. **Product specialist agent:** extracts terms, derives applicable conventions and produces the leg-specific payment calendars.
3. **Deterministic validator:** checks completeness and financial consistency. Correctable extraction errors are returned to the specialist, with a maximum of five passes. Classification is outside this loop.
4. **Deterministic mapper:** emits the production `RFQ` defined in `protos/pricing.proto`.
5. **Proto agent:** runs sequentially after the mapper and reproduces the same serialization only for experimental measurement. Its result never replaces or blocks an already valid deterministic RFQ.

The application flow is implemented in `src/app_service.py`. Agent composition and execution order are declared in `config/agents.yaml`.

## Project structure

```text
agents/                 Agent instructions
config/                 Agent network and model pricing
protos/                 RFQ Protocol Buffers schema
evaluation/cases/       23 reference cases in five families
evaluation/results/     Archived experimental databases
skills/                 IRS extraction knowledge
src/                    Application, validation and evaluation code
tests/                  Deterministic test suite
tools/                  Case and cost verification utilities
docs/                   Architecture, conventions, experiment log and thesis sources
```

## Setup

Python 3.11 or newer is required. The final experiments used Python 3.13 and the exact versions in `requirements.lock`.

### Windows PowerShell

```powershell
cd rfq-agents
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
Copy-Item .env.example .env
```

Configure at least the key required by the selected provider:

```env
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
LLM_MODEL=gpt-5.6-terra
```

`.env` and generated outputs are excluded from Git. No API key is stored in the archived evaluation databases.

## Run one request

```powershell
python src/runner.py --input examples/cotizacion_es.txt
```

Alternatively, use `--prompt` for inline text or omit both options for interactive input. Valid requests produce a validation report and a protobuf text-format RFQ under `outputs/`. Invalid or unsupported requests stop without emitting an RFQ.

## Deterministic verification

These commands do not call OpenAI or Anthropic:

```powershell
python -m pytest -q
python tools/check_cases.py
```

Final state: **84 tests pass** and **23 reference cases are coherent**.

## Reference cases

All 23 cases were designed by the author from the tutor's guidance on mandatory fields and scope.

| Family | Cases | Purpose |
|---|---:|---|
| `cotizacion/` | 7 | Par-rate quotation requests |
| `valoracion/` | 5 | Existing-trade valuations |
| `jerga/` | 3 | Trading-desk shorthand |
| `no_valorables/` | 3 | Missing or inconsistent information |
| `no_soportados/` | 5 | Products outside scope |

Supported cases use `.prompt.txt` and `.expected.textproto`. Unsupported cases use `.expected.product`.

## Evaluation

The evaluator records model outputs, validation results, field-level metrics, tokens, cost and latency in SQLite:

```powershell
python src/evaluate.py --models gpt-5.6-terra
python src/report.py
```

The final comparison used the same 23 cases and instructions for six OpenAI and Anthropic models. Archived databases are stored in `evaluation/results/`; the working database under `outputs/` is intentionally not tracked.

Field results are classified as `MATCH`, `WRONG`, `MISSING` or `HALLUCINATED`. The report also calculates Wilson confidence intervals, paired McNemar comparisons, latency, task cost and proto-agent fidelity.

Current-generation models did not permit the experiment to fix temperature. OpenAI rejected non-default values and the Anthropic SDK did not accept the parameter. Reproducibility therefore relies on fixed cases, instructions, schema, reference date, dependency versions and archived responses, not on `temperature=0`.

## Final results

| Model | Validation | Cost per correct case |
|---|---:|---:|
| `gpt-5.6-terra` | 23/23 | USD 0.0102 |
| `gpt-5.6-sol` | 23/23 | USD 0.0182 |
| `claude-sonnet-5` | 23/23 | USD 0.0401 |
| `claude-opus-5` | 23/23 | USD 0.0904 |
| `gpt-5.6-luna` | 22/23 | USD 0.0013 |
| `claude-haiku-4-5` | 13/23 stored validation | USD 0.0203 |

`gpt-5.6-terra` is the recommended configuration because it achieved 23/23 at the lowest cost among the error-free models. For `claude-haiku-4-5`, orchestrator classification was reconstructed as 19/23 from archived API telemetry; 13/23 is the stored end-to-end validation result.

## Evidence and documentation

- `docs/REGISTRO_EXPERIMENTOS.md`: chronological experiment log.
- `docs/ESTADO_ACTUAL.md`: final project state.
- `docs/HALLAZGOS_MEMORIA.md`: evidence-backed findings.
- `docs/CONVENCIONES_MERCADO.md`: verified EUR and USD conventions.
- `docs/Overleaf/`: thesis chapter sources and bibliography.
- `evaluation/results/`: archived SQLite databases supporting the reported measurements.

The schema follows the two-leg IRS structure in Ausín Amigo (2025), *Quantitative Finance: Code, Concepts, and Practice*, Definition 2.19, and its multi-curve framework in section 2.4.6.2.