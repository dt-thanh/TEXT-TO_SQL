# Architecture

This project separates HTTP transport, LangGraph orchestration, safety policy, and external
adapters so each part can be implemented and tested independently. Two question modes share the
same safety layers:

- **Quick SQL** (`POST /ask`): the model writes one SQL query from the schema and the semantic
  layer; a guard checks it; it runs as a read-only role.
- **Research** (`POST /research`): the model only plans with a catalog of verified metrics; code
  writes the SQL from templates; the model states findings; code checks every number.

## Text-to-SQL graph (src/agents/graph.py)

```mermaid
flowchart TD
    start([START]) --> retrieve[retrieve_context<br/>schema + semantic layer]
    retrieve --> generate[generate_sql<br/>LLM]
    generate -->|SQL| validate[validate_sql<br/>SQL guard]
    generate -->|no SQL: cannot answer| stop([END])
    validate -->|valid| execute[execute_sql<br/>Snowflake, agent role]
    validate -->|fixable violation, repairs left| repair[repair_sql<br/>LLM + failed attempts]
    validate -->|final violation or no repairs left| stop
    execute -->|rows| stop
    execute -->|compilation error, repairs left| repair
    execute -->|other error or no repairs left| stop
    repair -->|SQL| validate
    repair -->|no SQL: gave up| stop
```

## Research graph (src/agents/research/graph.py)

```mermaid
flowchart TD
    start([START]) --> prepare[prepare<br/>newest data day, table allowlist]
    prepare --> plan[plan<br/>LLM picks catalog metrics + parameters]
    plan -->|declined or no task| stop([END])
    plan --> execute[execute<br/>resolve params, render template,<br/>SQL guard, agent role]
    execute -->|no usable evidence| stop
    execute --> write[write<br/>LLM states findings, cites evidence]
    write --> check[check<br/>grounding: every number in the evidence]
    check -->|a number not in the evidence, one rewrite left| write
    check -->|grounded, or out of attempts / budget| stop
```

- **Catalog** (`semantic/metrics.yml`): a metric with a `template` has typed parameters, result
  columns with units, the column holding its sample size, a minimum number of observations, a
  point-in-time mode and a golden case verified by an independent calculation.
- **Resolver** (`catalog.py`): the planner's output is untrusted. Symbols and chains must be in the
  coverage, dates within the data, numbers within range; only then are values written into the
  template as SQL literals. The SQL still goes through the guard and runs as the agent role.
- **Grounding** (`grounding.py`): plain code reads every number of a finding (percent, basis
  points, billion/tỷ, English and Vietnamese number formats) and accepts it only if it matches a
  cited result, a sample size, a parameter or a number from the question.
- **Status** is decided by code: complete, partial, insufficient_data, declined, error.
- **Budgets**: 4 tasks, 2 writes, 60 s, $0.01 per question.

## Dependency injection

Nodes are plain functions `node(state, *, dependency)`. `build_graph(llm, warehouse, ...)` and
`build_research_graph(llm, warehouse, layer)` bind the LLM client, the warehouse connection and the
limits with `functools.partial`, so tests pass fakes and no node reads a global client.
`answer_question` and `answer_research` build their graph per call and pass an explicit
`recursion_limit` (LangGraph 1.x defaults to 10,007 steps).

## Error taxonomy (Quick SQL)

| Where | Error | Repaired? | Why |
|---|---|---|---|
| SQL guard | `not_select`, `forbidden_statement`, `multiple_statements`, `forbidden_function` | no | an attempt to write or escape; retrying teaches the model to get around the guard |
| SQL guard | `parse_error`, `empty`, `select_star`, `unqualified_table`, `table_not_allowed`, `table_function`, `rewrite_failed` | yes | a mistake in the SQL text |
| SQL guard | `duplicate_column`, `limit_without_order` | yes | SQL that runs but returns a misleading table (a dropped column, arbitrary "top" rows) |
| Snowflake | `SQL compilation error` (unknown column, syntax, types), `duplicate column names` | yes | a mistake in the SQL text |
| Snowflake | timeout, connection, privilege | no | rewriting the SQL does not change it |

At most `MAX_REPAIRS` (2) repairs per question; every failed attempt is kept and shown to the
next repair and to the analyst. The guard checks every `From`/`Join` node of the syntax tree, not
argument names: sqlglot 30 renamed the FROM argument, and a name-based rule silently stopped
seeing table functions (caught by a unit test during the upgrade).

## Boundaries

- `ui` is a thin Streamlit client: it calls `POST /ask` and `POST /research`, imports nothing from
  `src`, holds no secret.
- `src/api` owns HTTP contracts and routing; `src/models/schemas.py` is the contract.
- `src/agents` owns state, nodes, edges, retry routing, and prompt building (`sql_generation.py`);
  `src/agents/research` owns the research workflow, the catalog resolver and grounding.
- `src/semantic` reads the semantic layer (`semantic/*.yml`) and picks context per question.
- `src/services` owns provider adapters and the SQL safety boundary.
- `src/ingestion` owns the sources (Binance, FRED, DefiLlama); `dbt/` owns every transformation.
- `eval` is offline tooling, not an API runtime dependency.
