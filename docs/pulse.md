# FinSight Pulse (2026-10-26)

FinSight Pulse turns the Research Copilot into a tool the owner uses every day:
- watchlists of coins the owner picks;
- risk signals computed by fixed rules;
- a Daily Brief each morning with evidence for every number.

The plan is `FinSight_AI_Research_Copilot_Upgrade_Spec.md` v1.1 (Pulse sections and the
single-owner changes #21–#30). Operating it: [operations.md](operations.md). The rules and how
often they fire: [risk_signals.md](risk_signals.md).

Pulse is for one owner, with no accounts. It is still protected:
- endpoints are bound to localhost, or need a service key when deployed;
- LLM cost has a daily cap;
- Snowflake credits have a monthly monitor.

## What changed

| Area | Change |
|---|---|
| Asset universe | Any USDT spot pair Binance trades can be added, at most 20 assets in all. `CONTROL.ASSET_REGISTRY` tracks each request: requested → validating → backfilling → ready, or unsupported / error / disabled. The existing loader does the backfill (365 days, closed candles, MERGE), run by the DAG `finsight_asset_onboarding`, which the API starts when a coin is added. The daily run then loads core + ready assets. `mart_asset_universe` is the one list the agent, the research resolver and the UI share. The 8 hard-coded asset/chain lists are gone, and chains come from the curated seed. |
| Risk signals | `mart_risk_signal_daily`: abnormal move, volatility spike, drawdown, chain TVL drop, by rules in a seed, with calendar windows that never look ahead. High correlation is computed with the brief. dbt unit tests cover the threshold edge, too few observations and look-ahead. |
| Catalog | `symbol_list` parameters and results with many rows, judged row by row (a new coin's short history does not fail the others). Four metrics: `watchlist_snapshot`, `return_correlation_matrix`, `risk_signals`, `data_status`. Five verified queries (spec 4.4). |
| Daily Brief | The research graph with a plan built in code: no planner call, the same resolver, guard, read-only role, writer and grounding check. Tables and signals come from the evidence, so the brief still stands when the writer fails or the LLM is off. Airflow makes it each morning after the marts (`generate_daily_brief`) and saves it in `CONTROL.DAILY_BRIEF`. English or Vietnamese. |
| Chat and interface | Ask and Research report are both chats, sharing one mechanism (`/chat`, `/research/chat`); each tab opens with a short guide (what it is for, how, what you get), and suggested questions replace the old dropdown. Quick SQL as a chat. The client keeps the conversation and the server keeps none. The first question goes to the agent unchanged, so the benchmark still applies; a follow-up is rewritten into a standalone question and the rewrite is shown ("Understood as …"); greetings and advice/forecast requests are answered by rules at $0. EN/VI switch at the top right, kept in the URL; tabs renamed by purpose: Ask, Research report, Watchlist & Daily Brief. |
| API / UI | Assets, watchlists, `/brief`, `/briefs`, `/usage/today`, `/health/data`, and the tab *Watchlist & Brief*: statuses, add/remove, saved and on-demand briefs, a system status line. GETs are cached 60 s, so clicks do not wake the warehouse. |
| Production | `AUTH_MODE` local/deployed with one service key (fail closed); global rate limits; a daily LLM cost cap that reserves each request's maximum first; request ids on responses, log lines and Snowflake `QUERY_TAG`; JSON logs; seconds per graph node; `CONTROL.REQUEST_LOG`; API, UI and Airflow bound to 127.0.0.1; deploy compose with Caddy (HTTPS, password), `scripts/deploy.sh` with smoke test and rollback, CI publishes images for `v*` tags. |

## Results so far

| Check | Result |
|---|---|
| Unit tests | 411 pass (`pytest tests/unit`), lint clean |
| Integration tests (Snowflake, live APIs) | 74/74, including all 14 catalog golden cases |
| `dbt build` | PASS=144, WARN=2 (known: short candles, CPI October 2025), ERROR=0; 4 risk-rule unit tests included |
| Onboarding, live (2026-10-26) | `make add-asset SYMBOL=link` → `requested` (Airflow off: trigger failed softly) → `make onboard-assets`: verified, 8,762 hourly candles (365 days), dbt 65/65, `ready`, data through yesterday. A second run found nothing to do. The daily load list is now core + LINKUSDT. LINK has no TVL chain (none mapped) |
| API, live, no LLM | search, asset status, `PUT /watchlists/defi` (ETH, LINK, SOL), an unknown pair → 422 with nothing saved, a no-LLM brief saved and listed, `/usage/today`, `/health/data`; `REQUEST_LOG` rows written; the request id shows in Snowflake `QUERY_TAG` |
| Daily Brief without the LLM, 4 cases (answers computed independently, written before any run) | 4/4: plan, period, every return and drawdown, every signal |
| Risk rule frequency | measured. `volatility_spike` raised from 1.5 to 2.0 (it fired on 8–15% of days, now 1.5–5.4%); `drawdown_alert` is kept as a state (risk_signals.md) |
| Adding coins | typed freely, several at once, checked against Binance's 516 USDT pairs; typos get suggestions (`arbb` → ARBUSDT, `dogecoin` → DOGEUSDT); only right coins are added (`POST /assets/check`, `POST /watchlists/{name}/add`, UI *Check* → *Add*, `make add-asset`) |
| Quick SQL benchmark after the changes (2026-10-26) | 35/35, holdout 16/16 [81–100%], p50 1.9 s / p95 3.3 s, $0.0019 per question (`run_20261026T024759Z`) |
| Research benchmark after the changes | 20/21 at first: r08 (dev) planned `watchlist_snapshot` for one asset, the right numbers but not the catalog's single metrics. The catalog now says that metric is for two or more assets. After that: 21/21, holdout 11/11, values 27/27, refusals 4/4, p50 2.4 s / p95 3.4 s (`research_20261026T025114Z`). The Quick SQL run came before this one-sentence catalog note, which only shows when a question says "watchlist" or similar |
| Chat (Quick SQL with follow-ups), 10 conversations written before any run | 10/10, holdout 7/7: follow-ups ("and ETH?", "còn tháng 4?", "the yield known on that day?"), a greeting, advice declined by rule, a news question declined by the rewriter; $0.033 (`chat_20261026T033807Z`) |
| Daily Brief with the writer | 4/4 (holdout 2/2), 26 findings, 0 dropped by the number check, p50 4.3 s / p95 9.1 s, $0.0118 for all 4 (`brief_20261026T024926Z`) |

Not yet run (no invented numbers):
- the onboarding trigger through Airflow's REST API (Docker was off);
- product evaluation A/B/C: tasks and scoring are ready (`eval/run_product_eval.py`), no
  measurement yet;
- deploy and rollback exercise;
- manual check in a browser.

## Gap log

| Item | Status |
|---|---|
| Discord/Telegram brief and alert delivery | P2 by the owner's decision; failures show in Airflow and the UI |
| Onboarding trigger from the Docker API container | Not reachable (Airflow bound to the host's 127.0.0.1); the daily fallback run picks requests up. `make run` triggers at once |
| Rate limits and reservations | In-process, one API instance; several instances would need a shared counter (no Redis until needed) |
| Holdout exposure | The new verified queries share patterns with holdout questions q27, q28, q31, q35: their results from now on are optimistic |
| Product evaluation | One person who built the system; if no second person takes part, the report says so |
