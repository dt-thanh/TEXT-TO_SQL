# FinSight AI

Nền tảng phân tích thị trường tài chính. Dữ liệu crypto (Binance) và vĩ mô (FRED) được nạp vào
Snowflake, biến đổi bằng dbt, rồi người dùng hỏi bằng ngôn ngữ tự nhiên: hệ thống sinh, kiểm tra,
chạy và **hiển thị SQL** cùng kết quả.

Đặc tả đầy đủ: [FINSIGHT_AI_PROJECT_SPEC.md](FINSIGHT_AI_PROJECT_SPEC.md).

## Trạng thái

- Phase 0 (nền móng): config, logging, exception, Snowflake client dùng key-pair, script dựng Snowflake.
- Phase 1 (đang làm): Binance client + extractor đã xong; nạp vào `RAW` chưa có.
- `/ask` và LangGraph vẫn là skeleton; FRED, dbt, UI chưa có.

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

## Lệnh

```bash
make run              # chạy API (uvicorn)
make test             # pytest: unit + integration (integration gọi Binance thật)
make test-unit        # chỉ unit test, chạy offline được
make lint             # ruff
make check-snowflake  # kiểm tra kết nối Snowflake
```

## Cấu trúc

```text
src/common/        config, logging, exception dùng chung
src/services/      adapter ra bên ngoài: Snowflake, LLM, SQL guard
src/ingestion/     lấy dữ liệu nguồn (Binance, sau này FRED) và nạp vào RAW
src/agents/        LangGraph workflow (skeleton)
src/api/           FastAPI routes
infra/snowflake/   SQL dựng warehouse, database, schema, role, user
scripts/           công cụ dòng lệnh, chạy bằng `python -m scripts.<tên>`
tests/unit/        test không cần hệ thống ngoài
tests/integration/ test chạy với hệ thống thật (Snowflake, Binance)
```

Ranh giới module: [docs/architecture.md](docs/architecture.md).
