-- FinSight AI: the CONTROL schema and the API's own Snowflake identity. Safe to re-run.
-- Run in Snowsight as a user with ACCOUNTADMIN (it uses SYSADMIN, USERADMIN and SECURITYADMIN).
--
-- CONTROL holds operating state, not market data: the Binance symbol catalog, the asset registry
-- (which coins the owner asked for and how far their onboarding got), watchlists, saved daily
-- briefs and LLM usage. The tables themselves are created by 04_control_tables.sql.
--
-- Who can do what:
--   FINSIGHT_ENGINEER (pipeline, Airflow, dbt)  owns and writes every CONTROL table.
--   FINSIGHT_APP      (the API)                 reads and writes CONTROL rows; nothing else. It
--                                               cannot read RAW/STAGING/CORE or write MART.
--   FINSIGHT_AGENT    (LLM-written SQL)         unchanged: SELECT on MART only, no CONTROL.

-- 1. Schema ---------------------------------------------------------------------
USE ROLE SYSADMIN;
CREATE SCHEMA IF NOT EXISTS FINSIGHT.CONTROL COMMENT = 'Operating state: asset registry, watchlists, briefs, usage';

USE ROLE SECURITYADMIN;
GRANT ALL PRIVILEGES ON SCHEMA FINSIGHT.CONTROL TO ROLE FINSIGHT_ENGINEER;

-- 2. Role for the API -------------------------------------------------------------
USE ROLE USERADMIN;
CREATE ROLE IF NOT EXISTS FINSIGHT_APP COMMENT = 'FinSight API: read/write CONTROL rows only';

USE ROLE SECURITYADMIN;
GRANT ROLE FINSIGHT_APP TO ROLE SYSADMIN;
GRANT USAGE ON WAREHOUSE FINSIGHT_WH       TO ROLE FINSIGHT_APP;
GRANT USAGE ON DATABASE FINSIGHT           TO ROLE FINSIGHT_APP;
GRANT USAGE ON SCHEMA FINSIGHT.CONTROL     TO ROLE FINSIGHT_APP;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA FINSIGHT.CONTROL TO ROLE FINSIGHT_APP;
GRANT SELECT, INSERT, UPDATE, DELETE ON FUTURE TABLES IN SCHEMA FINSIGHT.CONTROL TO ROLE FINSIGHT_APP;

-- 3. Service user: key-pair only, no password -------------------------------------
USE ROLE USERADMIN;
CREATE USER IF NOT EXISTS FINSIGHT_APP_SVC
    TYPE = SERVICE
    DEFAULT_ROLE = FINSIGHT_APP
    DEFAULT_WAREHOUSE = FINSIGHT_WH
    COMMENT = 'FinSight API: watchlists, asset requests, saved briefs, usage';
-- Set the public key separately (one line, the body of ~/.snowflake/finsight_app_key.pub):
-- ALTER USER FINSIGHT_APP_SVC SET RSA_PUBLIC_KEY = '<one-line public key>';

USE ROLE SECURITYADMIN;
GRANT ROLE FINSIGHT_APP TO USER FINSIGHT_APP_SVC;
