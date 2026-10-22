-- One row per DefiLlama chain FinSight loads, with the asset each chain belongs to.
-- Built from the defillama_chains seed; fct_chain_tvl is tested against it (relationships).

select
    chain_id,
    chain_slug,
    chain_name,
    related_symbol,
    description
from {{ ref('defillama_chains') }}
