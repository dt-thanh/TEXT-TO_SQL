# Architecture skeleton

This project separates HTTP transport, LangGraph orchestration, safety policy, and external
adapters so each part can be implemented and tested independently.

```mermaid
flowchart LR
    Client --> API[FastAPI /ask]
    API --> Generate[generate_sql]
    Generate --> Validate[validate_sql]
    Validate -->|valid| Execute[execute_sql]
    Validate -->|invalid and retryable| Repair[repair_sql]
    Execute -->|success| Explain[explain_result]
    Execute -->|error and retryable| Repair
    Repair --> Validate
    Generate -.-> LLM[OpenAI or Anthropic]
    Repair -.-> LLM
    Explain -.-> LLM
    Execute -.-> Snowflake
    Schema[schema_tools] -.-> Snowflake
    Schema -.-> Generate
```

## Boundaries

- `src/api` owns HTTP contracts and routing.
- `src/agents` owns state, nodes, edges, retry routing, and future checkpoints.
- `src/services` owns provider adapters and the SQL safety boundary.
- `data` and `eval` are offline tooling, not API runtime dependencies.

TODO: Document dependency injection, error taxonomy, security controls, and deployment topology.
