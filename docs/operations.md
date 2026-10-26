# Operating FinSight Pulse

FinSight Pulse has **one owner**, who uses it and runs it. There are no user accounts. What is
protected is the system: endpoints are not reachable by strangers, and the OpenAI and Snowflake
costs stay bounded (spec v1.1, 6.3).

## One-time setup for Pulse

1. **Snowflake, as ACCOUNTADMIN:** run [`infra/snowflake/03_control_access.sql`](../infra/snowflake/03_control_access.sql).
   It creates:
   - the `CONTROL` schema;
   - the `FINSIGHT_APP` role (CONTROL rows only);
   - the `FINSIGHT_APP_SVC` user.

   Then set the user's public key:

   ```sql
   ALTER USER FINSIGHT_APP_SVC SET RSA_PUBLIC_KEY = '<body of ~/.snowflake/finsight_app_key.pub>';
   ```

   The private key stays in `~/.snowflake/`.
2. **Snowflake, as FINSIGHT_ENGINEER:** run [`infra/snowflake/04_control_tables.sql`](../infra/snowflake/04_control_tables.sql)
   to create the CONTROL tables.
3. **`.env`:** add the following (see `.env.example`):
   - `SNOWFLAKE_APP_USER`, `SNOWFLAKE_APP_PRIVATE_KEY_PATH`;
   - `AIRFLOW_API_URL=http://localhost:8081` with the Airflow login;
   - `AUTH_MODE=local`;
   - `LLM_DAILY_COST_CAP_USD`;
   - `BRIEF_LANGUAGE`.
4. **Data:**
   1. `make refresh-binance-catalog` fills the list of USDT spot pairs.
   2. `make dbt-build` builds `dim_asset`, `mart_asset_universe` and `mart_risk_signal_daily`.
5. **Airflow:** `make airflow-up`. `airflow-init` creates the pools `binance_api` and `dbt`.
   The DAG `finsight_asset_onboarding` starts unpaused.

   Containers created before the pools existed stay stuck: Docker Desktop restarts them with
   their old configuration, and tasks that use a missing pool are never scheduled (the
   scheduler logs "non-existent pool"). Seen on 2026-10-26. `make airflow-up` recreates them;
   check with `docker exec airflow-airflow-scheduler-1 python -m airflow pools list`.

## Daily use

| What | How |
|---|---|
| Start the app | `make run` (API on 127.0.0.1:8000), then `make ui` (http://127.0.0.1:8501) |
| Add coins | UI tab *Watchlist & Brief*: type `link, avax, arb` → *Check* (✅ right, ❌ wrong with "did you mean …") → *Add N valid coin(s)*. Or `make add-asset SYMBOL="link avax arb"`, same check |
| Morning brief | Made by Airflow after the marts are built (`finsight_daily` → `generate_daily_brief`). The UI opens the newest one |
| Brief now | *Generate Daily Brief*, `make brief ARGS="--watchlist default --print"`, or `ARGS="--no-llm --print"` for $0 |
| Is everything fresh? | The status line of the Pulse tab, or `GET /health/data` |
| What did the LLM cost today? | `GET /usage/today`; the cap is `LLM_DAILY_COST_CAP_USD` (default $1/day) |

### What happens when a coin is added

1. You type coins the way you like: `link`, `LINK`, `linkusdt`, several at once, separated by
   commas or spaces. Each one is checked against `CONTROL.BINANCE_SYMBOL`, the 516 USDT spot
   pairs Binance trades (refreshed daily), without calling Binance during your request.
   - A wrong coin is reported with what you probably meant: `arbb` → ARBUSDT, `dogecoin` →
     DOGEUSDT, `solana` → SOLUSDT.
   - Only the right coins are added; a wrong one never blocks the others.
2. It writes a `requested` row and starts the onboarding DAG through Airflow's REST API.
3. The DAG claims at most 3 requests. It checks each pair with Binance and backfills 365 days
   of closed candles with the same loader as the daily run. Then it rebuilds the Binance
   models and marks the coin `ready` once MART has it.
4. From then on, the daily run loads it.

If Airflow is not running, the request still succeeds and the coin shows as `loading`. The DAG's
daily fallback run (01:30 UTC) picks it up. That run is daily, not hourly, because every run
reads the registry, and a read wakes the Snowflake warehouse: one minute is the billing minimum.

**Known limitation.** When the API runs in Docker (`make app-up`), Airflow's port is bound to the
host's 127.0.0.1, so the API container cannot reach it. Coins then start at the daily fallback
run, or when you trigger `finsight_asset_onboarding` in the Airflow UI. With `make run`, which is
the usual setup, they start immediately.

## Limits

| Limit | Value | Where |
|---|---|---|
| Watchlists × assets | 3 × 10 | `src/control/watchlists.py` |
| Tracked assets (core + added) | 20 | `src/control/assets.py` |
| New assets per day | 10 | idem |
| Requests | `/ask` 30/min, `/research` and `/brief` 6/min, `PUT /watchlists` 30/hour | `src/api/security.py` |
| LLM spend | `LLM_DAILY_COST_CAP_USD` per UTC day, API + scheduled briefs together | `src/control/usage.py` |
| Snowflake credits | resource monitor `FINSIGHT_MONTHLY_RM`, 20 credits/month, notify 80%, suspend 100% | `infra/snowflake/00_setup.sql` |

When the LLM cap is reached:
- `/ask`, `/research` and `/brief` answer 429 and do not call the model;
- `/brief` with `use_llm=false` still works, and the scheduled brief is saved without findings
  (`partial`);
- the endpoints that do not use the LLM keep working.

## Logs and request ids

- Every response carries `X-Request-ID`, the one the caller sent if it is safe to log, otherwise
  a new one.
- The same id is on every log line, and in each Snowflake query's `QUERY_TAG`
  (`finsight_agent:<id>`, `finsight_app:<id>`). One search in `QUERY_HISTORY` therefore finds
  every query of a slow request.
- `LOG_FORMAT=json` writes one JSON object per line.
- Requests that use the LLM or write CONTROL add a row to `CONTROL.REQUEST_LOG` in the
  background: endpoint, status, seconds, tokens, cost. A failed write never fails the request.
- Each answer reports the seconds spent in every LangGraph node (`timings`).

Alerts go nowhere yet. Discord/Telegram notifications were postponed by the owner (P2). Failures
are visible in the Airflow UI and in the status line of the UI.

## Deploying (optional; deploy-ready is required)

`AUTH_MODE=deployed` makes every route except `/health` require `X-API-Key: FINSIGHT_SERVICE_KEY`.
Without that key the API refuses to start.

1. **Publish images.** Push a tag `vX.Y.Z`. The CI job `publish` builds and pushes
   `ghcr.io/<owner>/finsight-app:vX.Y.Z` and `finsight-airflow:vX.Y.Z`.
2. **Prepare the machine.** It needs `.env` (with `FINSIGHT_SERVICE_KEY`, a long random string)
   and the private keys in `~/.snowflake/`.
3. **Set the UI password hash.**
   - Create it with `docker run --rm caddy:2.10.2 caddy hash-password`.
   - Put it in `FINSIGHT_UI_PASSWORD_HASH`.
   - Set `FINSIGHT_DOMAIN` to the domain, or `localhost` for a test.
4. **Deploy.** Run `scripts/deploy.sh vX.Y.Z`. It:
   - starts [`deploy/docker-compose.deploy.yml`](../deploy/docker-compose.deploy.yml) (API, UI, Caddy);
   - runs a smoke test inside the network: health, a refused request without the key, and an
     accepted one with it;
   - rolls back to the previous tag by itself if the smoke test fails.
5. **Roll back by hand:** `scripts/deploy.sh --rollback`.

Only Caddy publishes ports (80/443), with HTTPS and the owner's password. The API is reachable
only on the compose network. A cloud VM costs a fixed amount each month: note the provider's
real price here when one is chosen.

Exercise required by the spec (PROD-03): deploy tag A, deploy tag B, roll back to A, on this
machine or a VM, and write the date and outcome below.

| Date | Machine | Steps | Outcome |
|---|---|---|---|
| — | — | not run yet | — |

## Rotating secrets

| Secret | How |
|---|---|
| OpenAI key | new key in the OpenAI dashboard → `.env` → restart the API and Airflow |
| FRED key | new key at fred.stlouisfed.org → `.env` → restart Airflow (**still pending**: the old key once reached a log) |
| `FINSIGHT_SERVICE_KEY` | new random string in `.env` on the machine → `scripts/deploy.sh <same tag>` |
| Snowflake keys | new key pair → `ALTER USER … SET RSA_PUBLIC_KEY_2 = …` → switch the file → `UNSET RSA_PUBLIC_KEY` |
