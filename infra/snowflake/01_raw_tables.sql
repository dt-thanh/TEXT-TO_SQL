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
