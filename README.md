# FinSight AI

[![CI](https://github.com/dt-thanh/TEXT-TO_SQL/actions/workflows/ci.yml/badge.svg)](https://github.com/dt-thanh/TEXT-TO_SQL/actions/workflows/ci.yml)

Ask questions about crypto markets, the US macro backdrop and DeFi in plain English or
Vietnamese, and get an answer computed in Snowflake, **together with the SQL that produced it**.
Research questions get a short report whose every number is traced to verified SQL.

> *"What was Ethereum's annualized volatility in 2025 on days when the 10-year Treasury yield
> rose from the previous day?"* → SQL on curated marts → a number, a chart, the table, and the
> query, explained step by step.

The project has three parts, built to production habits rather than demo shortcuts:

- **A data platform.** Binance (hourly candles for BTC, ETH, SOL, BNB since 2019), FRED (Fed
  Funds rate, 10-year Treasury yield, with every revision) and DefiLlama (daily DeFi TVL of each
  asset's chain and of all chains) are loaded idempotently into Snowflake, modeled with dbt into
  point-in-time correct marts, and refreshed daily by Airflow.
- **A Text-to-SQL agent (Quick SQL).** A LangGraph workflow writes SQL with an LLM, checks it
  with a sqlglot-based guard, runs it as a read-only Snowflake role, and repairs its own mistakes
  a bounded number of times.
- **A research mode.** For multi-step questions the model only plans with a catalog of verified
  metrics; code writes the SQL from templates; the model states findings; code checks every
  number against the evidence. FastAPI and a Streamlit screen serve both modes.

## Results

Measured on 2026-10-22 with `gpt-4.1-mini`, graded by comparing **results**, not SQL text. Holdout
questions were committed before the agent answered them and are never used to tune anything.

| Quick SQL (`make eval`, 33 questions) | Value |
|---|---|
| Execution accuracy, all questions | 32/33 (97%, 95% CI 85–99%) |
| Holdout questions | 14/14 (95% CI 78–100%) |
| Generated SQL that passed the guard and ran | 29/29 |
| Latency per question, as the user waits | p50 1.9 s, p95 2.9 s |
| LLM cost per question | ~$0.0014 |

| Research mode (`make eval-research`, 19 questions) | Value |
|---|---|
| Questions answered correctly (right metrics, right values, grounded) | 19/19 (95% CI 83–100%) |
| Holdout questions | 9/9 (95% CI 70–100%) |
| Expected results reproduced exactly | 24/24 |
| Must-decline questions declined (stocks, raw tables, stablecoins, forecasts) | 4/4 |
| Latency per question | p50 3.3 s, p95 5.3 s |
| LLM cost per question | ~$0.0016 |

Tests: 377 Python tests (unit, integration on Snowflake and the live APIs, DAG integrity), 97 dbt
data tests, CI on every push.

The benchmarks are small and the confidence intervals say so. Model choice and prompt changes are
compared with repeated runs (see [Engineering notes](#engineering-notes)).

## Architecture

```mermaid
flowchart LR
    subgraph Sources
        B[Binance REST API]
        F[FRED API]
        D[DefiLlama API]
    end
    subgraph Snowflake
        RAW[(RAW)] --> STG[(STAGING)] --> CORE[(CORE<br/>star schema)] --> MART[(MART)]
    end
    B -- "Python loaders<br/>MERGE, watermarks" --> RAW
    F -- "every vintage" --> RAW
    D -- "own vintages" --> RAW
    AF[Airflow daily DAG] -. schedules .-> B & F & D
    AF -. "dbt build + freshness" .-> STG
    MART --> AG
    subgraph Agent["Text-to-SQL agent (LangGraph)"]
        AG[retrieve schema + semantic layer] --> GEN[LLM writes SQL] --> G{SQL guard}
        G -- valid --> EX[run as read-only role]
        G -- fixable --> REP[repair with the error]
        EX -- compilation error --> REP --> G
    end
    MART --> PL
    subgraph Research["Research mode (LangGraph)"]
        PL[LLM plans with catalog metrics] --> TPL[verified SQL templates<br/>guard + read-only role]
        TPL --> WR[LLM states findings] --> GR{grounding check:<br/>every number in evidence}
    end
    EX --> API[FastAPI /ask, /research] --> UI[Streamlit]
    GR --> API
```

| Layer | What it does | Where |
|---|---|---|
| Ingestion | Idempotent MERGE loads, per-source watermarks, month-by-month backfill that survives crashes, retries with backoff, a revision history for DefiLlama built from daily fetches | [src/ingestion/](src/ingestion/) |
| Warehouse | RAW → STAGING → CORE → MART with dbt; point-in-time macro join; known-answer and freshness tests | [dbt/](dbt/) |
| Orchestration | Airflow 3 in Docker; loads → freshness check → dbt layer by layer | [airflow/](airflow/) |
| Agent | Quick SQL: retrieve context → generate → validate → execute → repair. Research: plan → execute templates → write → grounding check | [src/agents/](src/agents/) |
| Semantic layer | Metric definitions with SQL templates and golden cases, glossary, verified example queries, all in YAML | [semantic/](semantic/) |
| Safety | AST-based SQL guard + least-privilege Snowflake role + timeouts | [src/services/sql_guard.py](src/services/sql_guard.py), [infra/snowflake/](infra/snowflake/) |
| Serving | FastAPI contract, Streamlit thin client (no secrets in the UI) | [src/api/](src/api/), [ui/](ui/) |
| Evaluation | Execution accuracy and a research benchmark (metric selection, values, grounding, refusal), dev/holdout, Wilson intervals | [eval/](eval/) |

More detail: [docs/architecture.md](docs/architecture.md) (both graphs, error taxonomy, boundaries).

## Key design decisions

**Point-in-time macro data.** FRED revises its numbers. RAW keeps every published version
(vintage), and the mart joins each trading day only to the value that had already been
published that day, so an analysis of "days when yields rose" cannot use information from the
future. A dbt test checks it on known dates (Friday's 10-year yield is only known on Monday).

**The LLM is untrusted.** Its SQL is parsed into a syntax tree with sqlglot and must be exactly
one read-only query on allowlisted MART tables, with no `SELECT *` and a row cap. What runs is
the query printed back from the checked tree, without comments. Behind the guard, the agent's
Snowflake role can only `SELECT` from MART, and statements time out after 30 s.

**Repair only what can be repaired.** A compilation error (unknown column) or a fixable guard
violation goes back to the model with the failed SQL, at most twice. An attempt to write data,
a timeout or a lost connection ends the run: retrying those only costs money or teaches the
model to get around the guard.

**No silent wrong answers.** Results with two columns of the same name are refused (a dict would
drop one), a `LIMIT` without `ORDER BY` in the same SELECT is refused (it returns arbitrary
rows), and every answer states the newest day the data covers. Stale sources fail the Airflow
run instead of producing outdated answers.

**Semantic layer as reviewed data.** Formulas that no single column holds (volatility of a period,
compounded return, moving averages) live in YAML with English and Vietnamese synonyms and known
pitfalls, validated on load and checked against the warehouse by integration tests. Retrieval is
lexical on purpose: with a dozen concepts it is free, deterministic and easy to debug.

**Research numbers never come from the model.** In research mode the model chooses metrics and
parameters from a catalog (its answer is a strict JSON schema whose metric id is an enum). Code
checks every parameter (known symbols and chains, dates within the data, numbers in range) and
fills a verified SQL template; the result still passes the guard and the read-only role. The
model then phrases findings, and a grounding check in plain code rejects any number that is not
in the evidence it cites (percent vs fraction, basis points, "billion"/"tỷ", English and
Vietnamese number formats). Caveats that follow from the data, such as a 10-year yield FRED
stopped publishing or retrospective TVL, are added by code.

**A revision history the source does not publish.** DefiLlama recomputes past TVL and keeps no
vintages. Each daily load stores a value only when it is new or differs from the newest stored
one, with the fetch day in the grain, so "what did DefiLlama say on day X" stays answerable from
the day the pipeline started; earlier history is marked retrospective.

**No technology without a problem.** No vector database, no message queue, no Kubernetes: the
data volume and the number of concepts do not need them. Each tool in the stack answers a
specific need listed above.

## Engineering notes

A few things that were measured rather than assumed:

- **Latency.** A key-pair login to Snowflake costs ~2.3 s, and each question used to open two
  connections and re-read the schema: users waited 9–10 s. One kept connection per process and a
  10-minute schema cache brought the Snowflake part to ~0.1 s per question.
- **A prompt regression caught by A/B.** Adding three "harmless" rules to the system prompt
  dropped holdout accuracy from 26/27 to 20/27 over three runs each. An ablation isolated the
  cause, the rules were reverted, and the questions used to decide moved from holdout to dev.
- **Holdout discipline.** A question used to decide a change leaves the holdout split, so the
  holdout score stays an estimate for questions nobody tuned for. New benchmark questions are
  committed before the agent answers any of them.
- **A dependency upgrade that would have opened a hole.** sqlglot 30 renamed the FROM argument of
  its syntax tree; the guard silently stopped seeing `TABLE(...)` sources until a unit test
  failed. The guard now checks every FROM/JOIN node rather than argument names.
- **Choosing the model by measurement.** gpt-4o-mini, gpt-4.1-mini and gpt-5-mini, three runs
  each on the same questions: gpt-4.1-mini matched the best accuracy, gave the same answers on
  every run and cut p95 latency from 10–15 s to about 3 s, for about twice the price.
- **A maintenance page served with HTTP 200.** FRED answered every request with an HTML page;
  the loader now retries a non-JSON 200 like a 5xx and fails with a clear error, and the
  freshness check turned the stale FRED data red instead of serving it silently.

## Tech stack

Python 3.11 · Snowflake · dbt 1.12 · Apache Airflow 3.3 · LangGraph 1.2 · OpenAI (`gpt-4.1-mini`,
Structured Outputs) · sqlglot · FastAPI · Streamlit · Docker Compose · pytest · GitHub Actions

## Getting started

Requirements: Python 3.11, a Snowflake account, a FRED API key, an OpenAI API key, and Docker for
Airflow and the containerised app.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
make install                 # runtime + dev dependencies
cp .env.example .env         # then fill it in (see below)
make test-unit               # offline tests, no credentials needed
```

**Snowflake.** Create a key pair outside the repository (`~/.snowflake/`), run
[infra/snowflake/00_setup.sql](infra/snowflake/00_setup.sql) (warehouse, database, schemas, roles,
service user, resource monitor), [01_raw_tables.sql](infra/snowflake/01_raw_tables.sql) and
[02_agent_user.sql](infra/snowflake/02_agent_user.sql) (the read-only agent user), register the
public keys, and fill `SNOWFLAKE_*` in `.env`. `make check-snowflake` confirms the connection.

**Load and model the data.**

```bash
make load-binance    # first run backfills 2019 → now (~257k candles), later runs are incremental
make load-fred       # every FRED vintage since 2018-12
make load-defillama  # DeFi TVL per chain; the first run is a backfill
make dbt-deps && make dbt-build
```

**Ask questions.**

```bash
make ask Q="Which asset had the highest 30-day volatility on 2026-09-01?"
make research Q="When Ethereum TVL fell more than 10% in a week, was ETH more volatile?"
make run             # API on http://localhost:8000/docs
make ui              # in a second terminal: http://localhost:8501
```

## Commands

| Command | Purpose |
|---|---|
| `make ci` | Lint, unit tests and `dbt parse`: the checks CI runs, before you push |
| `make test` | All tests; integration tests run when Snowflake is configured |
| `make load-binance` / `make load-fred` / `make load-defillama` | Incremental loads into RAW |
| `make dbt-build` / `make dbt-freshness` | Build and test the models / check source freshness |
| `make airflow-up` | Airflow in Docker, UI on :8081, daily run at 00:30 UTC |
| `make ask Q="..."` / `make research Q="..."` | One question (Quick SQL) or a research report from the terminal |
| `make prompt Q="..."` | Print exactly what the model would read, without calling it |
| `make eval` / `make eval-research` | Quick SQL and research benchmarks (~$0.05 and ~$0.03 per full run; `ARGS="--gold-only"` is free) |
| `make run` / `make ui` / `make app-up` | API, UI, or both in Docker |

## Repository layout

```text
src/ingestion/   Binance, FRED and DefiLlama clients, loaders, sync logic (watermarks, backfill)
dbt/             STAGING, CORE, MART models, seeds, data tests
airflow/         Airflow image, compose file and the daily DAG
src/agents/      Quick SQL graph, nodes, prompts; research/ (catalog resolver, grounding, report)
src/semantic/    semantic layer loading and retrieval   (data in semantic/)
src/services/    Snowflake client, LLM client, SQL guard, chart selection
src/api/, ui/    FastAPI endpoints, Streamlit client
eval/            benchmark questions, grader, runner
tests/           unit (offline), integration (Snowflake, APIs), dags (needs Airflow)
infra/snowflake/ one-off SQL to create warehouse, roles and users
```

## Limitations and next steps

- The benchmarks are small (33 Quick SQL and 19 research questions); the confidence intervals
  say so, and a larger holdout set written by someone other than the builder is the next step.
- The research grader checks metrics, values and grounding, not wording: a finding can carry only
  numbers from the evidence and still interpret them loosely. The evidence and its SQL are always
  shown next to the findings for that reason.
- Research answers only what the nine catalog metrics compute; other questions are declined (or
  asked in Quick SQL mode).
- Quick SQL's repair loop fixes compilation errors, not wrong reasoning.
- Inflation (CPI) is not loaded yet: FRED was in maintenance during the upgrade (see
  [docs/research_copilot.md](docs/research_copilot.md)).
- Single-turn questions only; follow-ups ("and for ETH?") would need conversation state.
- The API has no authentication yet, so it is meant to run locally; auth and rate limiting come
  before any deployment.

## Documentation

- [FINSIGHT_AI_PROJECT_SPEC.md](FINSIGHT_AI_PROJECT_SPEC.md): the full product and data specification.
- [docs/architecture.md](docs/architecture.md): both graphs, error taxonomy, module boundaries.
- [docs/research_copilot.md](docs/research_copilot.md): the Research Copilot upgrade: what changed, results, gaps.
- [docs/upgrade_baseline.md](docs/upgrade_baseline.md): baseline, dependency upgrade and model A/B.
- [docs/README.vi.md](docs/README.vi.md): detailed setup and operations guide in Vietnamese.
