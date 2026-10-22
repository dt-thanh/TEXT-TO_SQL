-- Every MART column must carry a description in Snowflake: the Text-to-SQL agent learns what a
-- column means only from these COMMENTs (persist_docs). Returns each undocumented column.
--
-- The depends_on lines make dbt run this test after the marts are rebuilt, so it checks the
-- comments of this build rather than the previous one.
-- depends_on: {{ ref('mart_asset_daily') }}
-- depends_on: {{ ref('mart_macro_daily') }}
-- depends_on: {{ ref('mart_chain_tvl_daily') }}
-- depends_on: {{ ref('mart_market_macro_daily') }}
-- depends_on: {{ ref('mart_cpi_monthly') }}

select
    table_name,
    column_name
from {{ target.database }}.information_schema.columns
where table_schema = 'MART'
  and coalesce(trim(comment), '') = ''
