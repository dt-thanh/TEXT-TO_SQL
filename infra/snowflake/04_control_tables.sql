-- FinSight AI: CONTROL tables. Safe to re-run. Needs 03_control_access.sql first.
-- Run as FINSIGHT_ENGINEER so the pipeline role owns the tables; FINSIGHT_APP gets row access
-- through the future grants of 03_control_access.sql.
-- Snowflake does not enforce PRIMARY KEY; the code keeps keys unique (MERGE, guarded UPDATEs).

USE ROLE FINSIGHT_ENGINEER;
USE WAREHOUSE FINSIGHT_WH;

-- Binance USDT spot pairs that are trading, refreshed by the daily pipeline. The API searches it
-- and checks a requested pair against it without calling Binance during a user's request.
CREATE TABLE IF NOT EXISTS FINSIGHT.CONTROL.BINANCE_SYMBOL (
    symbol          VARCHAR(30)     NOT NULL,
    base_asset      VARCHAR(20)     NOT NULL,
    quote_asset     VARCHAR(20)     NOT NULL,
    status          VARCHAR(20)     NOT NULL,
    is_spot         BOOLEAN         NOT NULL,
    refreshed_at    TIMESTAMP_TZ(3) NOT NULL,
    CONSTRAINT pk_binance_symbol PRIMARY KEY (symbol)
)
COMMENT = 'Binance USDT spot pairs with status TRADING, from /api/v3/exchangeInfo';

-- Coins the owner added beyond the four core assets, and how far their onboarding got:
-- requested -> validating -> backfilling -> ready, or unsupported / error / disabled.
CREATE TABLE IF NOT EXISTS FINSIGHT.CONTROL.ASSET_REGISTRY (
    symbol          VARCHAR(30)     NOT NULL,
    asset_key       VARCHAR(50)     NOT NULL,   -- BINANCE:<baseAsset>, the coin's identity
    base_asset      VARCHAR(20)     NOT NULL,
    quote_asset     VARCHAR(20)     NOT NULL,
    display_name    VARCHAR(100),
    status          VARCHAR(20)     NOT NULL,
    backfill_start  DATE            NOT NULL,
    requested_at    TIMESTAMP_TZ(3) NOT NULL,
    ready_at        TIMESTAMP_TZ(3),
    data_through    DATE,
    last_error      VARCHAR(1000),
    attempts        NUMBER(5,0)     NOT NULL DEFAULT 0,
    claim_id        VARCHAR(64),                -- the onboarding run working on it, if any
    updated_at      TIMESTAMP_TZ(3) NOT NULL,
    CONSTRAINT pk_asset_registry PRIMARY KEY (symbol)
)
COMMENT = 'Assets added by the owner and their onboarding status';

-- Named watchlists (at most 3, 10 symbols each, checked by the API).
CREATE TABLE IF NOT EXISTS FINSIGHT.CONTROL.WATCHLIST (
    watchlist_name  VARCHAR(30)     NOT NULL,
    symbol          VARCHAR(30)     NOT NULL,
    added_at        TIMESTAMP_TZ(3) NOT NULL,
    CONSTRAINT pk_watchlist PRIMARY KEY (watchlist_name, symbol)
)
COMMENT = 'Named watchlists of the owner';

-- One saved daily brief per day and watchlist; a re-run the same day replaces it.
CREATE TABLE IF NOT EXISTS FINSIGHT.CONTROL.DAILY_BRIEF (
    brief_date      DATE            NOT NULL,
    watchlist_name  VARCHAR(30)     NOT NULL,
    window_days     NUMBER(5,0)     NOT NULL,
    status          VARCHAR(30)     NOT NULL,
    markdown        VARCHAR         NOT NULL,
    response_json   VARIANT,
    cost_usd        FLOAT,
    seconds         FLOAT,
    data_as_of      DATE,
    created_at      TIMESTAMP_TZ(3) NOT NULL,
    CONSTRAINT pk_daily_brief PRIMARY KEY (brief_date, watchlist_name)
)
COMMENT = 'Daily briefs, scheduled or on request';

-- LLM spend per UTC day, for the daily cost cap. Updated by the API and the scheduled brief.
CREATE TABLE IF NOT EXISTS FINSIGHT.CONTROL.API_USAGE (
    usage_date      DATE            NOT NULL,
    llm_cost_usd    FLOAT           NOT NULL DEFAULT 0,
    llm_requests    NUMBER(10,0)    NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP_TZ(3) NOT NULL,
    CONSTRAINT pk_api_usage PRIMARY KEY (usage_date)
)
COMMENT = 'LLM cost per UTC day';

-- One row per API request that used the LLM or Snowflake, for latency and cost over time.
CREATE TABLE IF NOT EXISTS FINSIGHT.CONTROL.REQUEST_LOG (
    request_id      VARCHAR(64)     NOT NULL,
    logged_at       TIMESTAMP_TZ(3) NOT NULL,
    endpoint        VARCHAR(100)    NOT NULL,
    status          VARCHAR(30),
    http_status     NUMBER(3,0),
    seconds         FLOAT,
    sql_count       NUMBER(5,0),
    sql_errors      NUMBER(5,0),
    findings_dropped NUMBER(5,0),
    input_tokens    NUMBER(10,0),
    output_tokens   NUMBER(10,0),
    cost_usd        FLOAT,
    timings         VARIANT,
    CONSTRAINT pk_request_log PRIMARY KEY (request_id)
)
COMMENT = 'API requests: status, latency, SQL and LLM usage';
