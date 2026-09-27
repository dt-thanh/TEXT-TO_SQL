# FinSight AI

Nền tảng phân tích thị trường tài chính. Dữ liệu crypto (Binance) và vĩ mô (FRED) được nạp vào
Snowflake, biến đổi bằng dbt, rồi người dùng hỏi bằng ngôn ngữ tự nhiên: hệ thống sinh, kiểm tra,
chạy và **hiển thị SQL** cùng kết quả.

Đặc tả đầy đủ: [FINSIGHT_AI_PROJECT_SPEC.md](FINSIGHT_AI_PROJECT_SPEC.md).

## Trạng thái

- Phase 0 (nền móng): config, logging, exception, Snowflake client dùng key-pair, script dựng Snowflake.
- Phase 1: Binance → `RAW` xong: nạp idempotent (MERGE), backfill theo từng tháng, incremental theo
  watermark cho 4 symbol MVP.
- Phase 2: FRED (DFF, DGS10) → `RAW`: giữ mọi vintage (mỗi lần công bố/sửa là một dòng), incremental theo
  ngày công bố.
- Phase 3 (đang làm): dbt — STAGING (`stg_binance_kline`, `stg_fred_observation`) + 22 data test.
- `/ask` và LangGraph vẫn là skeleton; CORE, MART, UI chưa có.

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

3. Trong Snowsight: mở [infra/snowflake/00_setup.sql](infra/snowflake/00_setup.sql), thay
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

Chạy [01_raw_tables.sql](infra/snowflake/01_raw_tables.sql) một lần (role `FINSIGHT_ENGINEER`), rồi:

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

Cần `FRED_API_KEY` trong `.env` và các bảng trong [01_raw_tables.sql](infra/snowflake/01_raw_tables.sql):

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

Dự án dbt nằm trong [dbt/](dbt/). Makefile nạp `.env` rồi chạy dbt với cùng user/role như loader Python.

```bash
make dbt-deps    # một lần: cài dbt_utils
make dbt-build   # tạo view STAGING và chạy toàn bộ data test
make dbt-docs    # tài liệu + sơ đồ lineage tại http://localhost:8080
```

- `stg_binance_kline`: UTC rõ ràng, `trade_date`, cờ `is_full_candle` (nến bị cắt ngắn khi sàn tạm dừng).
- `stg_fred_observation`: tính `realtime_end` của mỗi vintage = ngày trước vintage kế tiếp.
- Test cảnh báo (`warn`) cho điểm bất thường đã biết của nguồn; test lỗi (`error`) cho điều không được phép
  xảy ra, ví dụ khoảng trống dữ liệu > 12 giờ (dấu hiệu pipeline bỏ sót).

## Lệnh

```bash
make run              # chạy API (uvicorn)
make test             # pytest: unit + integration (integration gọi Binance thật)
make test-unit        # chỉ unit test, chạy offline được
make lint             # ruff
make check-snowflake  # kiểm tra kết nối Snowflake
make load-binance     # nạp incremental Binance → RAW
make load-fred        # nạp incremental FRED → RAW
make dbt-build        # dbt: tạo model + chạy data test
```

## Cấu trúc

```text
src/common/        config, logging, exception dùng chung
src/services/      adapter ra bên ngoài: Snowflake, LLM, SQL guard
src/ingestion/     lấy dữ liệu nguồn (Binance, FRED) và nạp vào RAW; phần dùng chung: retrying_http,
                   merge_loader
src/agents/        LangGraph workflow (skeleton)
src/api/           FastAPI routes
infra/snowflake/   SQL dựng warehouse, database, schema, role, user
dbt/               dự án dbt: RAW → STAGING → CORE → MART, kèm data test
scripts/           công cụ dòng lệnh, chạy bằng `python -m scripts.<tên>`
tests/unit/        test không cần hệ thống ngoài
tests/integration/ test chạy với hệ thống thật (Snowflake, Binance)
```

Ranh giới module: [docs/architecture.md](docs/architecture.md).
