-- FinSight AI: RAW layer tables. Safe to re-run.
-- Run as FINSIGHT_ENGINEER so that role owns the tables and the loader (FINSIGHT_SVC) can write them.

USE ROLE FINSIGHT_ENGINEER;
USE WAREHOUSE FINSIGHT_WH;

-- Grain: one symbol + one interval + one candle open_time.
-- Snowflake does NOT enforce PRIMARY KEY; it only documents the key. The loader's MERGE keeps it unique.
CREATE TABLE IF NOT EXISTS FINSIGHT.RAW.RAW_BINANCE_KLINE (
    symbol                    VARCHAR(20)     NOT NULL,
    interval_code             VARCHAR(10)     NOT NULL,

    open_time                 TIMESTAMP_TZ(3) NOT NULL,
    close_time                TIMESTAMP_TZ(3) NOT NULL,

    open_price                NUMBER(38,18),
    high_price                NUMBER(38,18),
    low_price                 NUMBER(38,18),
    close_price               NUMBER(38,18),

    base_volume               NUMBER(38,18),
    quote_volume              NUMBER(38,18),

    trade_count               NUMBER(38,0),

    taker_buy_base_volume     NUMBER(38,18),
    taker_buy_quote_volume    NUMBER(38,18),

    source_file               VARCHAR(500),
    ingested_at               TIMESTAMP_TZ(3),
    batch_id                  VARCHAR(100),

    CONSTRAINT pk_raw_binance_kline PRIMARY KEY (symbol, interval_code, open_time)
)
COMMENT = 'Binance spot klines as returned by /api/v3/klines, one row per candle';

-- Grain: one FRED series. Metadata as returned by /fred/series.
CREATE TABLE IF NOT EXISTS FINSIGHT.RAW.RAW_FRED_SERIES (
    series_id                 VARCHAR(50)     NOT NULL,
    title                     VARCHAR(500),
    frequency                 VARCHAR(50),
    frequency_short           VARCHAR(10),
    units                     VARCHAR(200),
    seasonal_adjustment       VARCHAR(200),
    observation_start         DATE,
    observation_end           DATE,
    source_last_updated       TIMESTAMP_TZ(3),
    ingested_at               TIMESTAMP_TZ(3),

    CONSTRAINT pk_raw_fred_series PRIMARY KEY (series_id)
)
COMMENT = 'FRED series metadata, one row per series';

-- Grain: one series + one observation_date + one vintage (realtime_start = the day FRED published
-- that value). A revision adds a row with a later realtime_start; old vintages are never overwritten.
-- ASSUMPTION: realtime_end stays NULL here. The loader asks FRED for "new and revised values only"
-- (output_type=3), which carries no end date; STAGING derives it as the next vintage's start - 1 day.
CREATE TABLE IF NOT EXISTS FINSIGHT.RAW.RAW_FRED_OBSERVATION (
    series_id                 VARCHAR(50)     NOT NULL,
    observation_date          DATE            NOT NULL,

    value_raw                 VARCHAR(100),
    value                     NUMBER(38,10),

    realtime_start            DATE            NOT NULL,
    realtime_end              DATE,

    ingested_at               TIMESTAMP_TZ(3),
    batch_id                  VARCHAR(100),

    CONSTRAINT pk_raw_fred_observation PRIMARY KEY (series_id, observation_date, realtime_start)
)
COMMENT = 'FRED observations, one row per value per vintage (value_raw "." = no value that day)';

-- Grain: one chain + one TVL day + one fetch day. DefiLlama publishes no revision history and may
-- recompute past days, so the loader stores a value only when it is new or differs from the newest
-- one already stored: the table is its own vintage history (fetched_date plays the role FRED's
-- realtime_start plays). The first load of a chain is a backfill (is_backfill = TRUE): those values
-- were fetched long after the day they describe and must not be read as "known at the time".
CREATE TABLE IF NOT EXISTS FINSIGHT.RAW.RAW_DEFILLAMA_CHAIN_TVL (
    chain                     VARCHAR(50)     NOT NULL,
    tvl_date                  DATE            NOT NULL,
    fetched_date              DATE            NOT NULL,

    tvl_usd                   NUMBER(38,2)    NOT NULL,
    is_backfill               BOOLEAN         NOT NULL,

    ingested_at               TIMESTAMP_TZ(3),
    batch_id                  VARCHAR(100),

    CONSTRAINT pk_raw_defillama_chain_tvl PRIMARY KEY (chain, tvl_date, fetched_date)
)
COMMENT = 'DefiLlama daily TVL per chain (USD, excludes liquid staking and double counting), one row per value per fetch that changed it';
