# FinSight AI

[![CI](https://github.com/dt-thanh/TEXT-TO_SQL/actions/workflows/ci.yml/badge.svg)](https://github.com/dt-thanh/TEXT-TO_SQL/actions/workflows/ci.yml)

Nền tảng phân tích thị trường tài chính. Dữ liệu crypto (Binance) và vĩ mô (FRED) được nạp vào
Snowflake, biến đổi bằng dbt, rồi người dùng hỏi bằng ngôn ngữ tự nhiên: hệ thống sinh, kiểm tra,
chạy và **hiển thị SQL** cùng kết quả.

Đặc tả đầy đủ: [FINSIGHT_AI_PROJECT_SPEC.md](../FINSIGHT_AI_PROJECT_SPEC.md).

## Trạng thái

- Phase 0 (nền móng): config, logging, exception, Snowflake client dùng key-pair, script dựng Snowflake.
- Phase 1: Binance → `RAW` xong: nạp idempotent (MERGE), backfill theo từng tháng, incremental theo
  watermark cho 4 symbol MVP.
- Phase 2: FRED (DFF, DGS10) → `RAW`: giữ mọi vintage (mỗi lần công bố/sửa là một dòng), incremental theo
  ngày công bố.
- Phase 3: dbt — STAGING (3 view), CORE (star schema, `fct_crypto_kline_1h` incremental) và MART
  (`mart_asset_daily`, `mart_macro_daily` point-in-time, `mart_market_macro_daily`), 69 data test.
- Phase 3b: Airflow (Docker) chạy toàn bộ pipeline mỗi ngày lúc 00:30 UTC.
- Phase 4: Text-to-SQL tối giản — câu hỏi → schema MART (từ metadata Snowflake) → OpenAI → SQL → chạy bằng
  user chỉ-đọc `FINSIGHT_AGENT_SVC`.
- Phase 5: SQL guard (sqlglot) — chỉ cho một câu SELECT trên bảng MART được phép, không `SELECT *`, ép
  LIMIT ≤ 100.
- Phase 6: semantic layer (`semantic/*.yml`: phạm vi dữ liệu, định nghĩa metric, glossary, SQL mẫu đã kiểm
  chứng) + retrieval theo từ đồng nghĩa (Việt/Anh, có/không dấu).
- Phase 7: LangGraph — retrieve_context → generate_sql → validate_sql → execute_sql, lỗi guard/biên dịch
  được gửi lại cho model sửa (repair_sql), tối đa 2 lần.
- Phase 8: FastAPI `POST /ask` + giao diện Streamlit (câu trả lời, biểu đồ, bảng, SQL luôn hiển thị, các lần sửa,
  chi phí), chạy local hoặc bằng Docker Compose.

## Cài đặt

### 1. Python 3.11

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
make test          # test integration tự skip cho tới khi cấu hình Snowflake
```

### 2. Snowflake

1. Tạo tài khoản trial: Enterprise, AWS, Asia Pacific (Singapore).
2. Tạo key-pair cho service user, lưu ngoài repo:

   ```bash
   mkdir -p ~/.snowflake && chmod 700 ~/.snowflake
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/.snowflake/finsight_svc_key.p8 -nocrypt
   openssl rsa -in ~/.snowflake/finsight_svc_key.p8 -pubout -out ~/.snowflake/finsight_svc_key.pub
   chmod 600 ~/.snowflake/finsight_svc_key.p8
   ```

3. Trong Snowsight: mở [infra/snowflake/00_setup.sql](../infra/snowflake/00_setup.sql), thay
   `<YOUR_LOGIN_NAME>` bằng kết quả `SELECT CURRENT_USER();`, rồi Run All.
4. Gắn public key cho `FINSIGHT_SVC`:

   ```bash
   grep -v "PUBLIC KEY" ~/.snowflake/finsight_svc_key.pub | tr -d '\n'; echo
   ```

   ```sql
   USE ROLE USERADMIN;
   ALTER USER FINSIGHT_SVC SET RSA_PUBLIC_KEY = '<kết quả lệnh trên>';
   ```

5. Điền `.env`:
   - `SNOWFLAKE_ACCOUNT`: kết quả `SELECT CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME();`
   - `SNOWFLAKE_PRIVATE_KEY_PATH`: đường dẫn tuyệt đối tới file `.p8` (`~` không được hiểu).
6. Kiểm tra:

   ```bash
   make check-snowflake   # in account, user, role, warehouse đang dùng
   make test              # test integration giờ phải PASS
   ```

## Lấy dữ liệu Binance (chưa cần Snowflake)

```bash
python -m scripts.extract_binance --symbol BTCUSDT --start 2024-01-01 --end 2024-01-08
```

Khoảng thời gian là nửa mở `[start, end)` theo UTC; nến chưa đóng bị bỏ qua. Toàn bộ lịch sử 1h từ
2019 của 4 symbol MVP (~257 nghìn nến) mất khoảng 40 giây qua REST API.

## Nạp dữ liệu Binance vào Snowflake

Chạy [01_raw_tables.sql](../infra/snowflake/01_raw_tables.sql) một lần (role `FINSIGHT_ENGINEER`), rồi:

```bash
make load-binance                                    # incremental: từ watermark của từng symbol tới hiện tại
python -m scripts.load_binance --start 2019-01-01    # nạp lại/backfill một khoảng cho cả 4 symbol
python -m scripts.load_binance --symbols BTCUSDT --start 2024-01-01 --end 2024-01-08
```

- Watermark = `MAX(open_time)` của symbol trong RAW. Symbol chưa có dữ liệu thì nạp từ 2019-01-01.
- Mỗi lần incremental đọc lùi 1 ngày trước watermark; MERGE khiến phần chồng lấn không sinh trùng.
- Khoảng thời gian được chia theo tháng UTC, mỗi tháng MERGE và commit riêng: chết giữa chừng thì chạy
  lại, phần đã xong không mất.
- Watermark chỉ nhìn phần mới nhất: lỗ hổng hoặc dòng sai *phía trước* watermark phải sửa bằng một lần
  nạp có `--start`.

Dữ liệu đi qua một bảng tạm rồi được `MERGE` vào `RAW.RAW_BINANCE_KLINE` theo khóa
`(symbol, interval_code, open_time)`. Chạy lại cùng lệnh không thêm dòng nào; nến bị sửa thì cập nhật
đúng dòng đó.

## Nạp dữ liệu FRED vào Snowflake

Cần `FRED_API_KEY` trong `.env` và các bảng trong [01_raw_tables.sql](../infra/snowflake/01_raw_tables.sql):

```bash
make load-fred                                   # lần đầu: backfill từ 2018-12-01; sau đó chỉ phần mới công bố
python -m scripts.load_fred --start 2018-12-01   # nạp lại mọi thứ FRED công bố từ ngày đó
```

- Khóa `RAW_FRED_OBSERVATION` là `(series_id, observation_date, realtime_start)`: `realtime_start` là
  ngày FRED công bố giá trị. Khi FRED sửa số liệu, RAW thêm một dòng mới; giá trị cũ được giữ lại để
  tránh look-ahead bias.
- Lấy dữ liệu bằng `output_type=3` (chỉ giá trị mới hoặc bị sửa), mỗi request một năm công bố
  (FRED giới hạn 2000 vintage mỗi request).
- Watermark = `MAX(realtime_start)`, mỗi lần incremental đọc lùi 7 ngày.
- `value_raw = "."` nghĩa là hôm đó không có giá trị (ngày lễ); khi đó `value` là `NULL`.

## Biến đổi dữ liệu bằng dbt

Dự án dbt nằm trong [dbt/](../dbt/). Makefile nạp `.env` rồi chạy dbt với cùng user/role như loader Python.

```bash
make dbt-deps    # một lần: cài dbt_utils
make dbt-build   # nạp seed, tạo STAGING + CORE, chạy toàn bộ data test
make dbt-build ARGS="--full-refresh"   # xây lại cả model incremental từ đầu
make dbt-docs    # tài liệu + sơ đồ lineage tại http://localhost:8082
```

- `stg_binance_kline`: UTC rõ ràng, `trade_date`, cờ `is_full_candle` (nến bị cắt ngắn khi sàn tạm dừng).
- `stg_fred_observation`: tính `realtime_end` của mỗi vintage = ngày trước vintage kế tiếp.
- Seed (`dbt/seeds/*.csv`): danh sách coin và chỉ số vĩ mô do người định nghĩa, review như code.
- CORE theo star schema: fact = sự kiện (nến, giá trị vĩ mô), dimension = đối tượng (ngày, tài sản, chỉ số).
  `fct_crypto_kline_1h` là incremental (chỉ MERGE dòng loader mới đổi, theo `loaded_at`).
- MART: `mart_asset_daily` (OHLCV ngày, daily/log return, volatility 30 ngày × √365),
  `mart_macro_daily` (mỗi ngày: giá trị vĩ mô mới nhất ĐÃ công bố — không look-ahead),
  `mart_market_macro_daily` (bảng chính cho Text-to-SQL). Role `FINSIGHT_AGENT` chỉ đọc được schema này.
- Test cảnh báo (`warn`) cho điểm bất thường đã biết của nguồn; test lỗi (`error`) cho điều không được phép
  xảy ra, ví dụ khoảng trống dữ liệu > 12 giờ (dấu hiệu pipeline bỏ sót).

## Chạy tự động bằng Airflow

Airflow 3.3 chạy trong Docker ([airflow/](../airflow/)): Postgres (metadata của Airflow), api-server (giao diện),
scheduler (LocalExecutor, chạy task), dag-processor (đọc file DAG). Cần Docker đang chạy.

```bash
make airflow-up      # build image (lần đầu vài phút) + khởi động; UI http://localhost:8081, airflow / airflow
make airflow-check   # liệt kê DAG bị lỗi import (không in gì = ổn)
make airflow-logs    # xem log scheduler
make airflow-down    # tắt (metadata vẫn giữ trong volume Postgres)
```

DAG `finsight_daily` ([finsight_daily.py](../airflow/dags/finsight_daily.py)), 00:30 UTC mỗi ngày:
`load_binance` + `load_fred` (song song) → `check_source_freshness` → `dbt_build_staging` → `dbt_build_core` →
`dbt_build_marts`. `check_source_freshness` (`dbt source freshness`, ngưỡng trong
[_sources.yml](../dbt/models/staging/_sources.yml)) làm run đỏ khi nến Binance mới nhất cũ hơn 48 giờ hoặc FRED không có
công bố mới trong 7 ngày; test `mart_is_up_to_date` đỏ khi MART thiếu ngày hôm qua. Dữ liệu cũ hiện thành lỗi trong
Airflow, không thành câu trả lời lỗi thời.
Mỗi task gọi lại đúng lệnh chạy tay (script Python, dbt) trong virtualenv riêng `/opt/finsight-venv` của image;
Airflow chỉ lo lịch, thứ tự, thử lại (2 lần, cách 5 phút) và không cho hai lần chạy chồng nhau.

## Hỏi bằng ngôn ngữ tự nhiên (Text-to-SQL)

1. Chạy [02_agent_user.sql](../infra/snowflake/02_agent_user.sql) trong Snowsight, rồi gắn public key:
   `grep -v "PUBLIC KEY" ~/.snowflake/finsight_agent_key.pub | tr -d '\n'` →
   `ALTER USER FINSIGHT_AGENT_SVC SET RSA_PUBLIC_KEY = '...';`
2. `.env`: `OPENAI_API_KEY`, `SNOWFLAKE_AGENT_PRIVATE_KEY_PATH` (xem `.env.example`).
3. Hỏi:

```bash
make ask Q="BTC biến động thế nào khi lợi suất 10 năm trên 4%?"
```

In ra SQL, giải thích từng bước, bảng kết quả và chi phí (gpt-4o-mini: ~1.500–2.000 token/câu ≈ $0,0004).
`make prompt Q="..."` chỉ in ra đúng những gì model sẽ đọc (không gọi LLM, $0).
Schema đưa cho model lấy từ `INFORMATION_SCHEMA` của MART, kèm mô tả cột do dbt ghi vào Snowflake
(`persist_docs`). SQL chạy bằng role `FINSIGHT_AGENT` (chỉ SELECT được MART), timeout 30 giây, tối đa 100 dòng.

Trước khi chạy, SQL đi qua [SQL guard](../src/services/sql_guard.py): parse thành cây cú pháp bằng sqlglot,
chặn mọi thứ không phải một câu SELECT (DML/DDL/GRANT/USE/CALL, lệnh ghi giấu trong CTE, nhiều câu lệnh),
chỉ cho đọc bảng có trong metadata MART (tên đầy đủ `FINSIGHT.MART.<bảng>`), không `SELECT *`, không table
function, không `SYSTEM$`, rồi thêm/giảm LIMIT về tối đa 100. SQL được chạy là bản guard in lại từ cây đã
kiểm tra (bỏ comment). Câu bị chặn không chạm tới Snowflake và trả về mã lỗi (`violations`) cho repair loop.

### API và giao diện

```bash
make run    # API: http://localhost:8000/docs  (POST /ask, GET /health)
make ui     # terminal thứ hai, giao diện: http://localhost:8501
make app-up # hoặc cả hai trong Docker (Docker Desktop phải đang chạy); make app-down để tắt
```

`POST /ask {"question": "..."}` trả về `status` (`answered` / `declined` / `blocked` / `failed`), `data_as_of` (ngày
mới nhất có dữ liệu), `total_seconds`, `sql`, `explanation`,
`rows` (JSON thuần: Decimal → số, date → ISO), `chart` (chọn bằng luật trong
[chart_service.py](../src/services/chart_service.py), không gọi LLM), các lần sửa và chi phí. SQL bị chặn hay lỗi vẫn là
câu trả lời (200); không gọi được OpenAI/Snowflake là 503 (chi tiết chỉ nằm trong log). Giao diện
[ui/streamlit_app.py](../ui/streamlit_app.py) chỉ gọi API, không có khóa bí mật nào.

### Repair loop (LangGraph)

Luồng nằm trong [src/agents/graph.py](../src/agents/graph.py), sơ đồ và bảng phân loại lỗi ở
[docs/architecture.md](architecture.md). Khi guard chặn một lỗi sửa được (`SELECT *`, tên bảng thiếu) hoặc
Snowflake báo `SQL compilation error`, SQL hỏng cùng thông báo lỗi được gửi lại cho model, tối đa 2 lần. Lệnh ghi
(DELETE, nhiều câu lệnh, `SYSTEM$`), timeout và lỗi kết nối không được sửa. `make ask` in từng lần thử thất bại.

### Semantic layer

Mô tả **cột** nằm trong dbt (`_marts.yml` → COMMENT trong Snowflake → schema trong prompt).
[semantic/](../semantic/) chứa kiến thức **không nằm trong một cột nào**:

- [glossary.yml](../semantic/glossary.yml): `coverage` (4 tài sản, 2 chuỗi vĩ mô, thứ KHÔNG có trong dữ liệu) —
  luôn có trong prompt; `terms` (giá đóng cửa, lãi suất Fed, lợi suất 10 năm, so với hôm trước).
- [metrics.yml](../semantic/metrics.yml): công thức + từ đồng nghĩa + bẫy (volatility của một giai đoạn, lợi nhuận
  cả kỳ, trung bình động, khối lượng...).
- [verified_queries.yml](../semantic/verified_queries.yml): SQL mẫu đã chạy thật (thay few-shot cố định).

[retriever.py](../src/semantic/retriever.py) chọn định nghĩa có từ đồng nghĩa xuất hiện trong câu hỏi (bỏ dấu,
cụm từ liền nhau) và tối đa 2 ví dụ chia sẻ ≥ một nửa khái niệm với câu hỏi. File YAML được kiểm tra khi
đọc (pydantic, key sai là lỗi); `tests/integration/test_semantic_layer.py` kiểm tra chúng khớp dữ liệu thật.

### Đánh giá (execution accuracy)

[eval/gold_questions.jsonl](../eval/gold_questions.jsonl): câu hỏi chuẩn (Level 0–7 của spec §27), mỗi câu có SQL đáp án
đã kiểm chứng. Chấm bằng cách so **kết quả chạy**, không so chữ SQL. Hai nhóm (`split`):

- `dev` (q01–q11): đã nhìn khi xây agent, được phép chỉnh prompt/semantic layer theo chúng → điểm lạc quan.
- `holdout` (q12 trở đi): viết trước khi agent thấy, **không bao giờ chỉnh hệ thống để sửa một câu holdout** (sửa
  rồi thì câu đó chuyển sang `dev` và viết câu holdout mới) → điểm trung thực cho câu hỏi mới.

```bash
make eval-gold                                          # chỉ chạy SQL đáp án: $0
make eval                                               # chấm cả bộ: 1 lần gọi LLM/câu (+ sửa) ≈ $0,0005/câu
make eval ARGS="--split holdout"                        # chỉ nhóm holdout
make eval ARGS="--only q04 q10"                         # chấm lại vài câu
make eval ARGS="--regrade eval/results/run_<...>.json"  # chấm lại SQL đã lưu: $0
```

Thêm một câu hỏi: viết câu hỏi trước (tự nhiên, đừng nhìn danh sách từ đồng nghĩa trong `semantic/`), viết SQL đáp án
và chạy thử (`make eval ARGS="--gold-only --only q22"`), tự kiểm tra con số bằng một cách tính khác, chỉ `SELECT`
những cột quyết định đáp án (cột thừa ở câu trả lời của model được chấp nhận, cột thiếu thì không), ghi bẫy vào
`notes`. `tests/unit/test_gold_questions.py` kiểm tra định dạng (tag hợp lệ, đúng một tag ngôn ngữ, SQL rỗng khi và
chỉ khi câu có tag `unanswerable`/`adversarial`). Câu `unanswerable`/`adversarial` đạt khi không SQL nào được chạy
(model từ chối, hoặc guard chặn).

Baseline (2026-09-28, gpt-4o-mini, chưa có SQL guard / semantic layer / repair): **8/11 = 73%**, $0,0036.
Sai: q04 (lọc trước window), q10 (sai định nghĩa volatility + lọc trước LAG), q11 (bịa mã TSLAUSDT).
Sau SQL guard (regrade cùng SQL đó): vẫn 8/11, không câu nào bị chặn — guard giới hạn thiệt hại, không
sửa lỗi nghĩa. `tests/integration/test_sql_guard_gold.py` kiểm tra guard không đổi đáp án của SQL gold.
Sau semantic layer (2026-09-28): **10/11 = 91%**, $0,0039 — q04, q11 đúng; q10 vẫn sai (lọc trước LAG).
Lưu ý: semantic layer được chỉnh sau khi nhìn 11 câu này, nên con số lạc quan; bộ 30 câu (Bài 14) mới đo thật.
Sau repair loop (2026-09-29): **10/11**, $0,0052 — 2 câu cần sửa (3 lần gọi sửa), q07 sửa thành công; q10 lặp lại
cùng một lỗi thiếu cột 3 lần.
Có holdout (2026-09-29, 21 câu): **19/21**, $0,0087 — dev 9/11 [95% CI 52–95%], holdout 10/10 [72–100%]. Hai khoảng
chồng nhau: chưa đủ câu để nói hai nhóm khác nhau. Cùng một prompt, q05 lúc đúng lúc sai (3 lần chạy lại: 1 sai, 2 đúng).
Sau hardening (2026-09-29): độ trễ **thật** (cả câu hỏi) p50 2,4 s / p95 6,2 s — trước đó ~9–10 s vì mỗi câu đăng nhập
Snowflake ~2,3 s ít nhất hai lần và đọc lại metadata; 100% SQL qua guard và chạy được; $0,00043/câu; 18/21 (dev 12/15,
holdout 6/6 [61–100%]). A/B 3 lần chạy mỗi cấu hình cho thấy ba luật thêm vào system prompt làm holdout tụt từ 26/27
xuống 20/27; đã gỡ (commit `ffc42ec`). q14, q15, q16, q18 chuyển sang dev vì đã được dùng để quyết định thay đổi.

## Kiểm tra tự động (CI)

[.github/workflows/ci.yml](../.github/workflows/ci.yml) chạy trên GitHub Actions mỗi lần push/pull request vào `main`,
ba job song song, không cần khóa bí mật và không tốn tiền:

- **python**: `ruff`, unit test (chạy được không cần mạng), `dbt parse` với thông tin kết nối giả;
- **dags**: cài Airflow 3.3.2 (constraints chính thức) và parse `airflow/dags` như dag-processor
  ([test_dag_integrity.py](../tests/dags/test_dag_integrity.py): không lỗi import, đúng thứ tự task, không catchup);
- **docker**: build image API/UI rồi chạy smoke test trong container (nạp semantic layer, prompt, gọi `/health`).

Integration test và benchmark không chạy trong CI: cần khóa Snowflake/OpenAI và tốn tiền; chạy local (`make test`,
`make eval`). Trước khi push: `make ci` chạy cùng các kiểm tra của job python.

## Lệnh

```bash
make run              # chạy API (uvicorn, :8000)
make test             # pytest: unit + integration (integration gọi Binance thật)
make test-unit        # chỉ unit test, chạy offline được
make ci               # lint + unit test + dbt parse: như CI, trước khi push
make lint             # ruff
make check-snowflake  # kiểm tra kết nối Snowflake
make load-binance     # nạp incremental Binance → RAW
make load-fred        # nạp incremental FRED → RAW
make dbt-build        # dbt: tạo model + chạy data test
make dbt-freshness    # dữ liệu RAW có đủ mới không
make airflow-up       # Airflow: pipeline tự chạy hằng ngày (UI :8081)
make ui               # giao diện Streamlit (cần make run)
make ask Q="..."      # hỏi dữ liệu bằng ngôn ngữ tự nhiên
make prompt Q="..."   # xem prompt model sẽ đọc, không gọi LLM
```

## Cấu trúc

```text
src/common/        config, logging, exception dùng chung
src/services/      adapter ra bên ngoài: Snowflake, LLM, SQL guard
src/ingestion/     lấy dữ liệu nguồn (Binance, FRED) và nạp vào RAW; phần dùng chung: retrying_http,
                   merge_loader
src/agents/        vòng Text-to-SQL; LangGraph workflow (skeleton)
src/semantic/      đọc semantic/*.yml và chọn ngữ cảnh cho từng câu hỏi
semantic/          semantic layer: metric, glossary, SQL mẫu (dữ liệu, viết tay)
ui/                giao diện Streamlit, chỉ gọi API
src/api/           FastAPI routes
infra/snowflake/   SQL dựng warehouse, database, schema, role, user
dbt/               dự án dbt: RAW → STAGING → CORE → MART, kèm data test
airflow/           Airflow trong Docker: Dockerfile, docker-compose.yml, dags/
scripts/           công cụ dòng lệnh, chạy bằng `python -m scripts.<tên>`
tests/unit/        test không cần hệ thống ngoài
tests/integration/ test chạy với hệ thống thật (Snowflake, Binance)
```

Ranh giới module: [docs/architecture.md](architecture.md).
