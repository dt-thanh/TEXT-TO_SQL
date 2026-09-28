-- FinSight AI: a dedicated Snowflake user for the Text-to-SQL agent. Safe to re-run.
-- Run in Snowsight as a user with ACCOUNTADMIN (it uses USERADMIN and SECURITYADMIN).
--
-- Why a separate user: SQL written by a language model runs under THIS identity. It only has
-- FINSIGHT_AGENT, which can SELECT from MART and nothing else (00_setup.sql, block 4b). Even a
-- wrong or malicious query cannot read RAW, change data or switch to the ENGINEER role.

USE ROLE USERADMIN;
CREATE USER IF NOT EXISTS FINSIGHT_AGENT_SVC
    TYPE = SERVICE
    DEFAULT_ROLE = FINSIGHT_AGENT
    DEFAULT_WAREHOUSE = FINSIGHT_WH
    COMMENT = 'Text-to-SQL agent: read-only access to MART';
-- Set the public key separately (one line, see README "Text-to-SQL"):
-- ALTER USER FINSIGHT_AGENT_SVC SET RSA_PUBLIC_KEY = '<one-line public key>';

USE ROLE SECURITYADMIN;
GRANT ROLE FINSIGHT_AGENT TO USER FINSIGHT_AGENT_SVC;
