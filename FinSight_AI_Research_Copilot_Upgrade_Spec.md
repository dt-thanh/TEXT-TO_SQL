# FinSight AI

**IMPLEMENTATION SPEC — Text-to-SQL → Crypto & Macro Research Copilot → FinSight Pulse**

*FinSight Pulse — Personalized Crypto Macro & Risk Intelligence*

Bản hướng dẫn giao cho Coding Agent (Claude Code / Codex) để NÂNG CẤP repository hiện có, không tạo dự án mới.
Phiên bản 1.1 · 22/10/2026, cập nhật 25/10/2026 (bổ sung FinSight Pulse; điều chỉnh cho sản phẩm một chủ sở hữu) · Repository:
https://github.com/dt-thanh/TEXT-TO_SQL (public, nhánh `main`).

Các dữ kiện về repository trong tài liệu này đã được đối chiếu với code tại commit `92c84cc` (22/10/2026). Các dữ kiện về
DefiLlama và phiên bản thư viện được kiểm tra trực tiếp ngày 22/10/2026 (Mục 3.2, Mục 2.3). Nếu code hoặc API đã thay đổi
khi bạn thực thi: **ưu tiên code/API thực tế** và ghi khác biệt vào gap log.
Bản cập nhật 25/10/2026 đối chiếu thêm với code tại commit `95e63d8` (sau khi T0–T6 đã triển khai, xem Mục 2.6) và với Binance
`exchangeInfo` kiểm tra trực tiếp ngày 25/10/2026 (Mục 3.7).

## Thay đổi so với v1.0

| # | Thay đổi | Lý do |
|---|---|---|
| 1 | Sửa URL repo, ghi baseline đã kiểm chứng (Mục 2.2) | v1.0 ghi sai tên repo và coi 86%/2,4 s là chưa kiểm chứng, trong khi đã có file kết quả |
| 2 | Mở rộng bảng/pattern có sẵn thay vì tạo bảng song song (Mục 3.4) | `fct_macro_observation`, `mart_asset_daily`, `mart_market_macro_daily` đã tồn tại |
| 3 | Bỏ `raw_source_ingestion` (payload + hash) khỏi P0 | Repo dùng RAW có kiểu + MERGE theo grain; giữ một pattern |
| 4 | Ghi rõ chính sách ghi đè RAW (Mục 3.3) | v1.0 mâu thuẫn với loader Binance hiện tại |
| 5 | Thêm CPI (`CPIAUCSL`) vào P0 | v1.0 dùng CPI trong SQL chuẩn và test nhưng không có nguồn |
| 6 | Dữ kiện DefiLlama đã kiểm chứng + tự tạo vintage cho TVL (Mục 3.2, 3.5) | TVL không có lịch sử sửa đổi; ngày hôm nay là giá trị chưa chốt; số 0 ở đầu lịch sử là "chưa có dữ liệu" |
| 7 | Research mode **metric-first** (Mục 5) | Số liệu tính bằng SQL đã kiểm chứng, không để LLM sinh SQL tự do cho báo cáo |
| 8 | Kiểm tra grounding bằng code, ngân sách cụ thể (Mục 5.4, 5.5) | Thay các câu "giới hạn token/cost" chung chung |
| 9 | Task T0.5 nâng cấp dependency + so model bằng A/B (Mục 2.3) | Thư viện chính đã cũ nhiều phiên bản |
| 10 | Holdout viết trước, routing/metric-selection/grounding metrics (Mục 7) | v1.0 chưa có quy tắc holdout cho câu mới |
| 11 | Gộp Research Answer + Research Brief; streaming để P2 (Mục 1.3, 6) | Giảm phạm vi P1 mà không mất giá trị |
| 12 | Đưa các việc tồn đọng từ review trước vào T0/T6 (Mục 2.4) | Mô tả cột MART thiếu, tài liệu lệch, CI runner |

### Bổ sung trong v1.1 (cập nhật 25/10/2026) — FinSight Pulse

Không phải phiên bản mới: các task, test, data contract, guardrail và tiêu chí hoàn tất ở trên giữ nguyên. Phần bổ sung định
nghĩa đầu ra sản phẩm và các bước nhỏ tiếp theo trên kiến trúc đã có.

| # | Bổ sung | Mục | Lý do |
|---|---|---|---|
| 13 | Định hướng sản phẩm **FinSight Pulse**: watchlist cá nhân, chỉ số rủi ro, báo cáo cá nhân hoá có bằng chứng | 1 | Làm rõ đầu ra thay vì chỉ "trợ lý hỏi đáp" |
| 14 | Trạng thái triển khai T0–T6 và audit danh sách tài sản hardcode | 2.6, 2.7 | Coding Agent không làm lại phần đã xong; 8 chỗ đang cố định 4 đồng / 4 chain |
| 15 | **T1.5 Dynamic Asset Universe**: registry tài sản, onboarding + backfill có kiểm soát, giữ nguyên client/extractor/loader/sync | 3.7–3.9 | Người dùng tự chọn đồng tiền mà không viết lại ingestion |
| 16 | Catalog hỗ trợ danh sách tài sản và kết quả nhiều dòng; **risk signals** bằng luật có ngưỡng, đơn vị, cửa sổ, test | 4.5, 4.6 | Tín hiệu rủi ro do code tính, không do LLM |
| 17 | **Daily Brief** tái sử dụng research workflow với kế hoạch do code dựng | 5.7 | Không tạo agent mới |
| 18 | Watchlist UI, API mới, bảo vệ truy cập, rate limit, trần chi phí, observability (điều chỉnh ở #21) | 6.1–6.4 | Sản phẩm dùng được hằng ngày và an toàn khi deploy |
| 19 | Product evaluation A/B/C, regression test cho watchlist/risk/brief, test production | 7.3, 7.5 | Chứng minh giá trị AI tách khỏi giá trị Data Engineering |
| 20 | Work packages T1.5, T2.5, T3.5, T4.5, T5.5, T6.5; phạm vi và handoff đồng bộ | 8, 9, 10 | Thứ tự triển khai rõ, không thành roadmap lớn |

### Điều chỉnh trong v1.1 (25/10/2026, lần 2) — sản phẩm một chủ sở hữu

FinSight Pulse dùng cho **một chủ sở hữu** (chính người vận hành hệ thống). Phần bổ sung ở trên được điều chỉnh để không xây
những thứ chỉ hệ thống nhiều người dùng mới cần, nhưng vẫn giữ các bảo vệ mà một sản phẩm thật phải có.

| # | Điều chỉnh | Mục | Lý do |
|---|---|---|---|
| 21 | Bỏ vai trò reader/analyst/admin, `owner_id`, quota theo khóa; thêm `AUTH_MODE` (`local`/`deployed`), một khóa dịch vụ, trần chi phí LLM mỗi ngày, resource monitor Snowflake | 1.1, 6.2, 6.3 | Rủi ro thật của sản phẩm một người là chi phí và endpoint bị lộ, không phải phân quyền giữa người dùng |
| 22 | Watchlist có tên (tối đa 3, mỗi cái 10 đồng); giới hạn 20 tài sản active | 3.7, 3.9 | Không còn owner; một người hiếm khi theo dõi hơn 20 đồng |
| 23 | Daily Brief **theo lịch** đưa vào P1.5: task Airflow sau `dbt_build_marts`, lưu `CONTROL.DAILY_BRIEF`, xem trong UI (thông báo Discord/Telegram hoãn sang P2) | 1.3, 1.4, 5.7 | Airflow đã chạy hằng ngày lúc 00:30 UTC; có brief buổi sáng mà không cần chờ cloud |
| 24 | Thêm đồng mới kích hoạt DAG onboarding ngay; lịch mỗi giờ chỉ là dự phòng | 3.8 | Không bắt người dùng chờ tới 15 phút |
| 25 | Cloud deployment thành tuỳ chọn; bắt buộc **deploy-ready** (image, compose, healthcheck, rollback đã chạy thử) | 1.4, 6.5 | Không trả tiền VM cố định khi chỉ dùng trên máy mình |
| 26 | Product evaluation khả thi cho một người: biến thể nhiệm vụ, 6–8 nhiệm vụ, ghi rõ giới hạn | 7.5 | Yêu cầu ≥ 2 người không khả thi với dự án cá nhân |
| 27 | Đo tần suất bật của risk signal; câu "không phải khuyến nghị" do code thêm; ánh xạ chain cho token gốc là bước review tay; vị trí hardcode thứ 8 (`MVP_CHAINS`) | 2.7, 3.8, 4.6, 5.7 | Tránh tín hiệu ồn và TVL gán sai |
| 28 | Đồng bộ với code đã triển khai: freshness DefiLlama 36/60 h, tên cột MART thực tế, số câu eval | 3.4, 7.1 | Spec lệch với phần đã làm ở T1–T5 |
| 29 | Lịch dự phòng của DAG onboarding: **mỗi ngày** (01:30 UTC) thay cho mỗi giờ (phát hiện khi triển khai, 26/10/2026) | 3.8 | Mỗi lần chạy đọc registry → đánh thức warehouse, tính tối thiểu 60 s; 24 lần/ngày ≈ 0,4 credit/ngày ≈ 12/20 credit tháng chỉ để kiểm tra |
| 30 | Resource monitor đã có từ trước (`FINSIGHT_MONTHLY_RM`, 20 credit/tháng, `00_setup.sql`): không cần SQL mới | 6.3 | Tránh tạo trùng |
| 31 | Thêm coin kiểu "gõ → kiểm tra → thêm": gõ tự do nhiều coin, mỗi coin được đối chiếu danh mục Binance; coin sai được báo kèm gợi ý gần đúng (ARBB → ARBUSDT); chỉ coin đúng được thêm, coin sai không chặn coin khác | 6.1, 6.2 | Yêu cầu của chủ dự án (26/10/2026): thêm coin linh hoạt, báo rõ khi gõ nhầm |
| 32 | Ngưỡng `volatility_spike` 1,5 → 2,0; `drawdown_alert` giữ là trạng thái | 4.6 | Đo tần suất bật: 8–15% số ngày ở 1,5 (quá ồn), 1,5–5,4% ở 2,0 (`docs/risk_signals.md`) |
| 33 | Quick SQL và Research thành **chat** (cùng cơ chế; `/chat`, `/research/chat`), mỗi tab có khung hướng dẫn ngắn (dùng để, cách dùng, nhận được gì), nút "Thử hỏi" thay danh sách câu mẫu. Chi tiết chat: hỏi nối tiếp (viết lại thành câu đầy đủ, hiện "Hiểu là…"), chào hỏi và xin tư vấn mua bán/dự đoán xử lý bằng luật ($0, không SQL), câu ngoài phạm vi được từ chối kèm gợi ý; server không lưu hội thoại; nút EN/VI; tên tab theo mục đích. Benchmark riêng `eval/chat_conversations.jsonl` (10 hội thoại, viết trước khi chạy) | 1.3, 6 | Yêu cầu của chủ dự án (26/10/2026): dùng như sản phẩm thật. Câu đầu đi thẳng vào agent nên benchmark Quick SQL vẫn còn giá trị |

---

## 0. Lệnh thực thi cho Coding Agent

Bạn là senior AI/Data Engineer thực thi nâng cấp trên repository đang mở trong workspace. Đọc tài liệu từ đầu đến cuối,
**kiểm tra code**, triển khai từng task, chạy test, ghi kết quả thật. Không dừng ở kế hoạch; không khẳng định chức năng đã
tồn tại khi chưa kiểm tra.

- **Nhiệm vụ:** giữ nguyên lõi Text-to-SQL; mở rộng FinSight thành trợ lý nghiên cứu crypto và kinh tế vĩ mô: hỏi đáp,
  phân tích nhiều nguồn, báo cáo có bằng chứng cho từng con số; rồi thành **FinSight Pulse**: watchlist do người dùng chọn,
  chỉ số và tín hiệu rủi ro tính bằng luật, Daily Brief cá nhân hoá có bằng chứng.
- **Thứ tự:** T0 Audit → T0.5 Dependency upgrade → T1 Ingestion (DefiLlama, CPI) → T2 dbt + metric catalog → T3 Research
  workflow → T4 API/UI/report → T5 Evaluation → T6 Docs/CI. T0–T6 đã triển khai (Mục 2.6). Phần Pulse tiếp theo:
  T1.5 Dynamic Asset Universe → T2.5 Risk signals + catalog nhiều dòng → T3.5 Daily Brief (theo yêu cầu + theo lịch) →
  T4.5 API/UI watchlist → T5.5 Regression + product evaluation → T6.5 Production hardening (bảo vệ truy cập, trần chi phí,
  giám sát, deploy-ready; cloud deploy tuỳ chọn) (Mục 8).
- **Một chủ sở hữu:** không tài khoản, không đăng nhập, không vai trò người dùng (Mục 6.3, 9.1). Bảo vệ hệ thống và chi phí
  vẫn bắt buộc.
- **Nguyên tắc:** dùng lại code có sẵn trước; thay đổi tối thiểu; dữ liệu đúng trước, AI tinh vi sau; tính toán bằng luật,
  LLM chỉ hỗ trợ diễn giải; bằng chứng trước, lỗi thì dừng an toàn; không bịa benchmark; không thêm hạ tầng không cần.
- **Làm việc trực tiếp trên `main`** (dự án một người). Mỗi task là một hoặc vài commit nhỏ, rollback được. Không push khi
  chủ dự án chưa đồng ý.
- **Không làm:** đặt lệnh giao dịch, tư vấn đầu tư, dữ liệu khách hàng/ngân hàng; không thêm multi-agent, MCP, GraphRAG,
  vector DB, Kafka, Spark, Kubernetes, Redis, microservices chỉ để làm đẹp CV; không dự đoán giá, không khuyến nghị mua bán.
- **Bảo mật:** không in, log hay commit nội dung `.env`, khóa API, private key. Không thay đổi Snowflake role/user/warehouse
  khi chưa hỏi: role/schema/resource monitor mới (Mục 3.7, 6.2, 6.3) được viết thành SQL trong `infra/snowflake/` để chủ dự án chạy. Test mặc định
  không cần mạng hay credentials.
- **Trả về:** báo cáo handoff theo Mục 9.3.

---

## 1. Mục tiêu sản phẩm & phạm vi

### 1.1 Vấn đề cần giải quyết

FinSight hiện trả lời câu hỏi ngôn ngữ tự nhiên → SQL → kết quả trên Snowflake (MART). Bản nâng cấp giải quyết **câu hỏi
nghiên cứu** cần nhiều nguồn và định nghĩa chỉ số chặt chẽ: giá crypto, lãi suất/lợi suất/lạm phát Mỹ, TVL DeFi. Nguyên tắc:
**phần tính toán do SQL/code đã kiểm chứng làm; LLM chỉ lập kế hoạch và diễn giải**, mỗi con số trong báo cáo truy ngược
được về nguồn và câu SQL.

**FinSight Pulse — Personalized Crypto Macro & Risk Intelligence** là đầu ra sản phẩm của bản nâng cấp. Người dùng là **một
chủ sở hữu** nghiên cứu hoặc theo dõi thị trường crypto, đồng thời là người vận hành hệ thống (không có tài khoản hay nhiều
người dùng, Mục 6.3). Pulse giúp người đó:

1. Tự chọn các đồng tiền muốn theo dõi (tối đa 3 watchlist có tên, mỗi watchlist tối đa 10 đồng trong MVP).
2. Xem chỉ số thị trường và rủi ro tính từ dữ liệu: lợi nhuận, độ biến động, drawdown, tương quan, bối cảnh vĩ mô, TVL khi
   phù hợp, độ tươi dữ liệu.
3. Hỏi đáp, nghiên cứu, so sánh tài sản bằng ngôn ngữ tự nhiên (Quick SQL và Research đã có).
4. Tạo báo cáo thị trường cá nhân hoá (Daily Brief) với bằng chứng kiểm chứng được (giá trị, nguồn, SQL): theo yêu cầu, và
   tự động mỗi sáng sau khi pipeline hằng ngày chạy xong.
5. Tiết kiệm thời gian tổng hợp và phân tích (đo bằng product evaluation, Mục 7.5; không công bố con số chưa đo).

Pulse **chỉ hỗ trợ nghiên cứu và đánh giá rủi ro**: không dự đoán giá, không khuyến nghị mua bán, không tự động giao dịch.
Mọi tín hiệu rủi ro là luật đã định nghĩa (Mục 4.6); LLM không tự tính hay tự đặt ra tín hiệu.

### 1.2 Câu hỏi minh họa

- "Trong những ngày lợi suất trái phiếu Mỹ 10 năm tăng hơn 10 bps, BTC và ETH biến động ra sao trong 30 ngày tiếp theo?"
- "Khi TVL Ethereum giảm hơn 10% trong 7 ngày, độ biến động của ETH tuần đó có khác các tuần bình thường không?"
- "Tương quan giữa daily return của BTC và ETH trong 2025 là bao nhiêu, dựa trên bao nhiêu ngày?"
- "Lập báo cáo ngắn cho 30 ngày gần nhất: BTC, ETH, lợi suất 10 năm, TVL Ethereum — có bảng, SQL và nguồn từng chỉ số."
- (Pulse) Người dùng thêm LINK và AVAX vào watchlist cùng BTC, ETH; bấm **Generate Daily Brief** cho 30 ngày: hiệu suất từng
  đồng, tín hiệu rủi ro đang bật, tương quan trong watchlist, bối cảnh lãi suất/lạm phát, TVL cho chain có dữ liệu.

### 1.3 Chế độ đầu ra

| Chế độ | Kỳ vọng | Không được làm |
|---|---|---|
| **Quick SQL** (giữ nguyên) | Câu hỏi 1–2 chỉ số; kết quả, SQL, bảng/biểu đồ như `POST /ask` hiện tại | Không ép mọi câu hỏi qua planner nhiều bước |
| **Research** (mới) | Kế hoạch 1–4 bước theo metric catalog, kết quả từ 2–3 nguồn, findings có bằng chứng, caveats; xuất được Markdown | Không sinh số liệu, không kết luận nhân quả, không đặt lệnh hay cam kết lợi nhuận |
| **Daily Brief** (Pulse) | Báo cáo theo watchlist và khoảng thời gian: market overview, hiệu suất watchlist, risk signals, bối cảnh crypto–macro, findings, caveats, evidence + nguồn + SQL, độ tươi dữ liệu, thời gian chạy, chi phí LLM; xuất Markdown; theo yêu cầu hoặc theo lịch hằng ngày | Không xếp hạng "nên mua", không gán chỉ số không phù hợp cho token (ví dụ TVL cho token không có chain được ánh xạ), không gửi tới ai ngoài kênh riêng do chủ sở hữu cấu hình |

v1.0 tách "Research Answer" và "Research Brief"; v1.1 gộp: brief chỉ là research answer được trình bày thành Markdown.
Daily Brief của Pulse là một research answer với **kế hoạch do code dựng từ watchlist** (Mục 5.7), không phải chế độ hay agent
riêng.

### 1.4 Phân pha

- **P0 — dữ liệu và metric đáng tin:** TVL theo chain từ DefiLlama (tự tạo vintage), CPI từ FRED, dbt models + tests,
  metric catalog mở rộng, regression tests.
- **P1 — Research Copilot:** router, research workflow metric-first, grounding check, `POST /research`, tab Research trong
  Streamlit, eval trước/sau.
- **P1.5 — FinSight Pulse MVP:** Dynamic Asset Universe (T1.5), risk signals và catalog nhiều dòng (T2.5), Daily Brief theo
  yêu cầu **và theo lịch** bằng Airflow hiện có (T3.5), watchlist API/UI (T4.5), regression + product evaluation (T5.5).
- **P1.6 — Production readiness:** bảo vệ truy cập cho một chủ sở hữu (`AUTH_MODE`), rate limit toàn cục, trần chi phí LLM
  mỗi ngày, resource monitor Snowflake, request ID + structured logging + node-level timing, monitoring và cảnh báo
  freshness, deploy-ready + CI/CD có rollback; cloud deployment trên VM là **tuỳ chọn** (T6.5).
- **P2 — sau demo:** streaming tiến trình (SSE), stablecoin supply, protocol TVL, lưu payload gốc để replay, tin tức có giấy
  phép, PDF export, thông báo brief/cảnh báo qua Discord/Telegram, nhiều người dùng (tài khoản, vai trò, quota theo người dùng) nếu sau này có nhu cầu thật.

---

## 2. Baseline dự án và kiểm tra bắt buộc (T0, T0.5)

### 2.1 Kiến trúc hiện tại (đã kiểm chứng)

| Thành phần | File | Ghi chú |
|---|---|---|
| Ingestion Binance | `src/ingestion/binance/{client,extractor,loader,sync}.py` | Nến 1h BTC/ETH/SOL/BNB (USDT) từ 2019-01-01; watermark − 1 ngày; chỉ nến đã đóng |
| Ingestion FRED | `src/ingestion/fred/*` | `DFF`, `DGS10`; `output_type=3` (mọi vintage); watermark = `MAX(realtime_start)` − 7 ngày; từ 2018-12-01 |
| Phần dùng chung | `src/ingestion/retrying_http.py`, `merge_loader.py` | Retry 429/5xx có backoff, che secret; `TableSpec` + stage TEMPORARY + MERGE theo grain |
| Snowflake | `infra/snowflake/00_setup.sql`, `01_raw_tables.sql`, `02_agent_user.sql` | Role `FINSIGHT_ENGINEER` (pipeline), `FINSIGHT_AGENT` (chỉ SELECT MART, có future grants) |
| dbt | `dbt/models/{staging,core,marts}`, `dbt/tests/`, `dbt/seeds/` | 70 data test; `persist_docs` cho MART; freshness trong `_sources.yml` |
| Point-in-time | `stg_fred_observation.sql` (`realtime_end` bằng `LEAD`), `mart_macro_daily.sql` | Known-answer test: DGS10 biết ngày 22/12/2024 = 4.57 |
| Airflow | `airflow/dags/finsight_daily.py` | 00:30 UTC; loads song song → freshness → staging → core → marts |
| Agent | `src/agents/{text_to_sql,graph,state,sql_generation}.py`, `nodes/*` | LangGraph 5 node, `MAX_REPAIRS=2`, `MAX_ROWS=100`, timeout 30 s |
| Semantic layer | `semantic/{glossary,metrics,verified_queries}.yml`, `src/semantic/*` | Retrieval lexical (không embedding) |
| SQL guard | `src/services/sql_guard.py` | AST (sqlglot), allowlist từ `INFORMATION_SCHEMA`, LIMIT ≤ 100 |
| API/UI | `src/main.py`, `src/api/routes.py`, `src/models/schemas.py`, `ui/streamlit_app.py` | `POST /ask`, `GET /health`; UI là thin client |
| Eval | `eval/run_eval.py`, `eval/gold_questions.jsonl`, `src/evaluation/compare.py` | Execution accuracy, dev/holdout, Wilson CI |
| CI | `.github/workflows/ci.yml` | 3 job: python (ruff, unit, dbt parse), dags, docker smoke |

### 2.2 Baseline đã có

- Nguồn: `eval/results/run_20260929T041135Z.json` và README.
- Kết quả: **18/21** (dev 12/15, holdout 6/6 [95% CI 61–100%]); p50 **2,4 s**, p95 **6,2 s** (cả câu hỏi); ~$0,00043/câu;
  model `gpt-4o-mini`.
- Test: 276 test pytest (237 unit, chạy ~3 s), 39 test integration pass, 70 dbt test.

**T0 phải đo lại**: `make ci`, `make test` (nếu có credentials), `make eval-gold`, `make eval` (một lần, ~$0,01). Ghi exit
code, số liệu và cấu hình vào `docs/upgrade_baseline.md`. Không dùng con số cũ làm kết quả mới.

### 2.3 T0.5 — Nâng cấp dependency trước khi viết code mới

Phiên bản đang ghim so với bản mới nhất trên PyPI (kiểm tra 22/10/2026):

| Gói | Đang dùng | Mới nhất | Rủi ro khi nâng |
|---|---|---|---|
| `langgraph` | 0.4.5 | 1.2.16 | API graph/state; research workflow sẽ viết trên bản mới |
| `openai` | 1.78.1 | 3.36.0 | Cách gọi Structured Outputs, kiểu lỗi |
| `sqlglot` | 26.19.0 | 30.24.0 | Tên lớp AST → SQL guard (56 test bảo vệ) |
| `dbt-core` | 1.12.5 | 1.12.6 | Thấp |

Quy trình: nâng từng gói một → `make ci` + `make test` + `make eval-gold` → `make eval` một lần và so với baseline. Nếu một
gói làm hỏng hành vi mà không sửa được trong phạm vi nhỏ, giữ bản cũ và ghi vào gap log. Cập nhật constraints Airflow không
nằm trong task này.

**So model bằng A/B:** chạy `make eval` với `gpt-4o-mini` và tối đa 1–2 model nhỏ hiện hành của OpenAI, mỗi cấu hình 3 lần,
cùng bộ câu hỏi. Chỉ đổi model mặc định khi kết quả holdout không giảm và chi phí/độ trễ chấp nhận được. Cập nhật đơn giá
trong `Settings` theo trang giá chính thức tại thời điểm đổi.

### 2.4 Việc tồn đọng phải xử lý trong T0/T6

- `mart_market_macro_daily`: 10/12 cột có comment rỗng trong `INFORMATION_SCHEMA` (chỉ `treasury_10y`, `fed_funds_rate` có
  mô tả). Dùng dbt `{% docs %}` để viết mô tả một lần, dùng lại cho mọi model; thêm check "mọi cột MART phải có description".
  Đổi mô tả = đổi prompt → chạy lại eval.
- `docs/architecture.md`: bảng phân loại lỗi thiếu `duplicate_column`, `limit_without_order`, `empty`, `rewrite_failed`, và
  lỗi Snowflake "duplicate column names" (repairable).
- `docs/README.vi.md`: dòng 19 ("69 data test"), 307 ("skeleton"), 317 (thiếu FRED/quyền agent).
- CI: đổi `runs-on: ubuntu-latest` thành `ubuntu-24.04` (GitHub chuyển nhãn sang Ubuntu 26 từ 19/10/2026).
- Nhắc chủ dự án đổi `FRED_API_KEY` (từng lộ ra log trước khi có che secret). Agent không tự làm việc này.

### 2.5 Checkpoint T0

| Checkpoint | Điều kiện qua |
|---|---|
| T0.1 | `docs/upgrade_audit.md` mô tả đúng luồng hiện hành bằng đường dẫn thật; mọi khác biệt với Mục 2.1 được ghi lại |
| T0.2 | `docs/upgrade_baseline.md` có kết quả test/eval thật hoặc lý do không chạy được |
| T0.3 | Không lộ secret; không thay đổi tài nguyên Snowflake ở bước audit |
| T0.5 | Dependency đã nâng (hoặc gap log giải thích); toàn bộ test xanh; eval không giảm trên holdout |

### 2.6 Trạng thái triển khai T0–T6 (đã kiểm chứng tại commit `95e63d8`, 22/10/2026)

Chi tiết và số liệu: `docs/research_copilot.md`, `docs/upgrade_baseline.md`, `docs/upgrade_audit.md`. Không làm lại các phần
"Xong"; phần "Còn mở" thuộc T2/T3/T5 và được gom vào task Pulse tương ứng (Mục 8).

| Task | Trạng thái | Ghi chú |
|---|---|---|
| T0, T0.5 | Xong | sqlglot 30, openai 3, langgraph 1.2, dbt-core 1.12.6; model mặc định `gpt-4.1-mini` theo A/B 3 lần chạy |
| T1 | Xong | DefiLlama (5 chain, vintage tự tạo), CPI (`mart_cpi_monthly`, tháng 10/2025 không được công bố → NULL) |
| T2 | Xong, **còn mở 4.4** | 10 metric có template + golden case; `verified_queries.yml` vẫn chỉ 5 ví dụ cũ |
| T3 | Xong, router thay bằng chế độ chọn tường minh | Chưa có unit test cho AI-06 (vượt ngân sách) |
| T4 | Xong | `POST /research`, tab Research, Markdown export |
| T5 | Xong | Quick SQL 35/35 (holdout 16/16), Research 21/21 (holdout 11/11); bộ câu do người xây hệ thống viết trước khi chạy |
| T6 | Xong | README, `docs/research_copilot.md`, CI `ubuntu-24.04`; Docker image chưa build lại sau nâng cấp, CI chưa chạy (chưa push) |

Trạng thái FinSight Pulse (26/10/2026, chưa commit; chi tiết `docs/pulse.md`, `docs/operations.md`, `docs/risk_signals.md`):

| Task | Trạng thái | Ghi chú |
|---|---|---|
| T1.5 | Xong, chạy thật 26/10/2026 | CONTROL + `FINSIGHT_APP` đã tạo; LINKUSDT: requested → ready (8.762 nến, dbt 65/65); chạy lại = 0 việc; trigger qua Airflow REST chưa thử (Docker tắt) |
| T2.5 | Xong trên dữ liệu thật | `mart_risk_signal_daily` + 4 dbt unit test pass trên Snowflake; 4 metric nhiều dòng; golden 14/14; 5 verified query; bảng tần suất trong `docs/risk_signals.md`; ngưỡng `volatility_spike`/`drawdown_alert` chờ chủ dự án quyết |
| T3.5 | Xong | Brief không LLM 4/4 case trên dữ liệu thật; task Airflow `generate_daily_brief`; lưu `CONTROL.DAILY_BRIEF` cần CONTROL |
| T4.5 | Code + test xong | Endpoint Mục 6.2, tab Watchlist & Brief (AppTest); kiểm tra tay trên trình duyệt chưa làm |
| T5.5 | Xong phần tự động; product eval **chưa đo** | Brief có LLM 4/4 (holdout 2/2), 0 finding bị loại; sau thay đổi: Quick SQL 35/35 (holdout 16/16), Research 21/21 (holdout 11/11; r08 dev từng hụt do `watchlist_snapshot` chồng chéo → sửa mô tả catalog); product eval A/B/C: tasks + worksheet + report sẵn |
| T6.5 | Code + test xong | `AUTH_MODE`, khóa dịch vụ, rate limit, trần chi phí có giữ chỗ, request id + `QUERY_TAG`, log JSON, timing node, `REQUEST_LOG`, `/health/data`, bind 127.0.0.1, deploy compose + Caddy + `scripts/deploy.sh` + CI publish; deploy/rollback chưa chạy thử |

### 2.7 Audit danh sách tài sản cố định (đã kiểm chứng 25/10/2026)

Danh sách BTC/ETH/SOL/BNB (và 4 chain tương ứng) đang được viết cứng ở 8 nơi. T1.5 thay chúng bằng một nguồn tập trung
(Mục 3.7); T0 của mỗi lần chạy phải grep lại (`MVP_SYMBOLS`, `MVP_CHAINS`, `BTCUSDT`, `binance_assets`, `coverage.assets`,
`related_symbol`) và ghi khác biệt.

| Vị trí | Vai trò hiện tại | Sau T1.5 |
|---|---|---|
| `src/ingestion/binance/sync.py` `MVP_SYMBOLS` | Danh sách nạp hằng ngày | Mặc định cho "core assets"; danh sách nạp = core ∪ registry `ready` |
| `scripts/load_binance.py` (`--symbols` mặc định) | CLI và task Airflow | Mặc định đọc danh sách nạp ở trên |
| `dbt/seeds/binance_assets.csv` → `dim_asset` | Vũ trụ tài sản, test `relationships` | Seed giữ 4 core asset; `dim_asset` = seed ∪ registry `ready` |
| `semantic/glossary.yml` `coverage.assets` + `tests/integration/test_semantic_layer.py` (so khớp với MART) | Model biết tài sản nào tồn tại | Glossary giữ tên/synonym tuyển chọn cho core; coverage đầy đủ đọc từ MART (`mart_asset_universe`) |
| `src/agents/research/catalog.py` (`symbol ∈ coverage.assets`) | Resolver kiểm tra symbol | Kiểm tra theo tài sản `ready` trong universe |
| `src/semantic/retriever.py` (`format_context`) | In danh sách tài sản vào prompt | In từ universe (tối đa giới hạn ở Mục 3.8) |
| `dbt/seeds/defillama_chains.csv` (`related_symbol`) | Ánh xạ chain → đồng tiền cho TVL | Giữ là danh sách **tuyển chọn**; token mới không có TVL trừ khi được thêm có chủ ý |
| `src/ingestion/defillama/sync.py` `MVP_CHAINS` | Danh sách chain nạp TVL hằng ngày | Đọc từ `defillama_chains.csv` (cùng một danh sách với `dim_chain`), cộng tổng `All`; thêm một chain = thêm một dòng seed |

---

## 3. Dữ liệu: Binance + FRED (+ CPI) + DefiLlama

### 3.1 Nguồn dữ liệu và hợp đồng

| Nguồn | Endpoint | Grain trong RAW | Trạng thái |
|---|---|---|---|
| Binance | `GET /api/v3/klines` | (symbol, interval_code, open_time UTC) | Có sẵn, không đổi |
| FRED | `GET /fred/series/observations`, `output_type=3` | (series_id, observation_date, realtime_start) | Có sẵn; **thêm `CPIAUCSL`** |
| DefiLlama chain TVL | `GET https://api.llama.fi/v2/historicalChainTvl/{chain}` | (chain, tvl_date, fetched_date) | **Mới, P0** |
| DefiLlama tổng TVL | `GET https://api.llama.fi/v2/historicalChainTvl` | (chain = `ALL`, tvl_date, fetched_date) | **Mới, P0** |
| DefiLlama stablecoin, protocol | `/stablecoincharts/*`, `/protocol/{slug}` | — | P2; xác minh base URL trước khi làm |

### 3.2 Dữ kiện DefiLlama đã kiểm chứng (22/10/2026)

- Endpoint chain TVL **miễn phí, không cần API key** (tài liệu: `https://api-docs.defillama.com/llms-free.txt`).
- Response: mảng `[{"date": <unix giây, 00:00 UTC>, "tvl": <USD>}]`.
- TVL theo định nghĩa của DefiLlama **không tính liquid staking và phần bị đếm trùng**. Đó không phải volume, không phải
  "dòng tiền vào". Ghi định nghĩa này vào semantic layer.
- Chain cho P0 (khớp với 4 core asset; ánh xạ chain → đồng tiền là danh sách **tuyển chọn**, không suy ra từ ticker khi thêm
  tài sản mới, Mục 3.7):

| Chain slug | Liên quan tới | Ngày đầu có TVL > 0 | Giá trị 22/10/2026 |
|---|---|---|---|
| `Ethereum` | ETH | 2018-02-12 | ~$50,6B |
| `Solana` | SOL | 2021-03-17 | ~$6,0B |
| `BSC` | BNB | 2020-10-30 | ~$5,8B |
| `Bitcoin` | BTC | 2021-03-20 | ~$4,4B |
| tổng (`/v2/historicalChainTvl`) | toàn thị trường | — | — |

- **Điểm cuối cùng mang ngày hôm nay**: coi là giá trị **chưa chốt** (đang cập nhật trong ngày). Chỉ nạp `tvl_date < ngày
  UTC hiện tại` — cùng nguyên tắc bỏ nến Binance chưa đóng.
- **Đầu lịch sử có `tvl = 0`** (ví dụ Ethereum 2017-09-27 → 2018-02-11): đó là "chưa có dữ liệu", không phải TVL bằng 0. Bỏ
  các dòng trước ngày đầu tiên có TVL > 0. Sau ngày đó, thiếu dữ liệu là NULL/không có dòng, **không** điền 0.
- Không có rate limit công bố trong tài liệu miễn phí: dùng `retrying_http.get_json` hiện có, một request mỗi chain mỗi lần
  chạy, timeout 30 s.

### 3.3 Chính sách ghi dữ liệu (giữ pattern hiện tại)

- **Dùng `merge_loader` (TableSpec + MERGE theo grain)** cho mọi bảng RAW mới. Không tạo kho payload thứ hai ở P0.
- **Binance giữ nguyên:** nến bị sửa được MERGE cập nhật, dấu vết là `ingested_at` + `batch_id`. Đây là lựa chọn có chủ ý
  (giá đã chốt hiếm khi đổi; lịch sử sửa không phục vụ câu hỏi nào).
- **FRED và DefiLlama giữ mọi phiên bản:** một giá trị mới hoặc bị sửa là **một dòng mới** (grain có ngày công bố/ngày lấy),
  không ghi đè.
- Mọi bảng RAW mới có `ingested_at`, `batch_id`; chạy lại cùng dữ liệu không tạo dòng mới (DATA-02).

### 3.4 Thay đổi dbt (mở rộng, không tạo song song)

| Đối tượng | Hành động | Grain |
|---|---|---|
| `RAW.RAW_DEFILLAMA_CHAIN_TVL` (mới, `01_raw_tables.sql` hoặc file `03_*.sql`) | `chain, tvl_date, fetched_date, tvl_usd, is_backfill, ingested_at, batch_id` | chain + tvl_date + fetched_date |
| `stg_defillama_chain_tvl` (mới, view) | `valid_to` bằng `LEAD(fetched_date)` theo (chain, tvl_date), giống `stg_fred_observation` | như RAW |
| `dim_chain` (mới, seed `defillama_chains.csv`) | chain_id, chain_slug, related_symbol, description | chain |
| `fct_chain_tvl` (mới, table) | mọi phiên bản TVL | chain + tvl_date + fetched_date |
| `mart_chain_tvl_daily` (mới, table) | `tvl_usd` (mới nhất), `tvl_change_7d`, `is_retrospective`, `fetched_date` | date + chain |
| `mart_macro_daily` (mở rộng) | thêm `cpi_index`, `cpi_source_month`, `cpi_available_date`, `cpi_days_since_release` theo đúng luật PIT hiện có | market_date |
| `mart_cpi_monthly` (mới) | mỗi tháng: giá trị công bố lần đầu, ngày công bố lần đầu, giá trị mới nhất, `mom_change_first_release` | observation_month |
| `mart_market_macro_daily` (mở rộng) | thêm `tvl_usd` của chain liên quan (qua `dim_chain`), `treasury_10y_change_bps` | trade_date + symbol |
| `seeds/macro_indicators.csv` | thêm `CPI` → `CPIAUCSL` | — |

Bắt buộc giữ:

- Test `equal_rowcount` giữa `mart_asset_daily` và `mart_market_macro_daily` (chống fan-out khi join thêm TVL).
- `mart_known_answers` mở rộng: thêm ít nhất 1 giá trị TVL và 1 giá trị CPI đã kiểm tra tay với nguồn.
- Freshness cho `raw_defillama_chain_tvl` (`loaded_at_field: cast(tvl_date as timestamp_tz)`). Đã triển khai với **warn
  36 h, error 60 h** thay cho 30/48 h của bản đầu: chỉ nạp ngày đã kết thúc, nên lúc 00:30 UTC điểm mới nhất (hôm qua) đã cũ
  ~24,5 giờ; 30 h sẽ cảnh báo nhầm khi DAG chạy trễ vài giờ.
- Mô tả cột đầy đủ cho mọi cột MART mới (đi vào prompt qua `persist_docs`).

Tên cột trong bảng trên là thiết kế ban đầu. Tên đã triển khai (nguồn chuẩn: `dbt/models/marts/_marts.yml`) khác ở:
`mart_macro_daily` dùng `cpi_month, cpi_release_date, cpi_yoy_change, cpi_mom_change`; `mart_cpi_monthly` dùng `cpi_month,
release_date, cpi_index, cpi_mom_change, cpi_yoy_change, latest_cpi_index, is_revised`; `mart_chain_tvl_daily` thêm
`related_symbol, tvl_change_1d`; `mart_market_macro_daily` dùng `chain, chain_tvl_usd, chain_tvl_change_7d, defi_tvl_usd,
defi_tvl_change_7d, cpi_month, cpi_yoy_change`. Task mới dùng tên đã triển khai.

### 3.5 Point-in-time cho TVL: tự tạo vintage

DefiLlama không công bố lịch sử sửa đổi, và có thể tính lại TVL quá khứ khi đổi phương pháp. Thiết kế:

- **Lần nạp đầu (backfill):** lưu toàn bộ lịch sử với `fetched_date` = ngày nạp và `is_backfill = true`. Mọi giá trị này là
  **retrospective**: không được trình bày là "đã biết vào ngày đó".
- **Mỗi lần nạp hằng ngày:** lấy toàn bộ chuỗi, nhưng chỉ **thêm dòng** khi (a) `tvl_date` chưa có, hoặc (b) giá trị khác giá
  trị mới nhất đang lưu cho cùng (chain, tvl_date) quá ngưỡng sai số tương đối 1e-6. Đây là cùng ý nghĩa với `output_type=3`
  của FRED ("chỉ giá trị mới hoặc bị sửa"), nên bảng không phình theo số ngày chạy.
- **Mart:** `mart_chain_tvl_daily` mặc định dùng giá trị mới nhất, kèm `is_retrospective = (fetched_date > tvl_date + 1 ngày)`.
  Câu hỏi "as-known" chỉ hợp lệ cho các ngày có dữ liệu thu từ lúc pipeline bắt đầu chạy hằng ngày; báo cáo phải nói rõ.
- Vì logic thêm dòng có điều kiện "khác giá trị mới nhất", loader TVL cần một câu SQL riêng (không chỉ `build_merge_sql`): stage
  → so với bản mới nhất theo (chain, tvl_date) bằng `QUALIFY ROW_NUMBER()` → INSERT các dòng mới/khác. Viết hàm thuần dựng SQL và
  test như `build_merge_sql`.

### 3.6 Airflow

- Thêm task `load_defillama` chạy song song với `load_binance`, `load_fred`, trước `check_source_freshness`.
- Cập nhật `tests/dags/test_dag_integrity.py` (đồ thị downstream mới).
- Lệnh `make load-defillama` và `scripts/load_defillama.py` theo đúng khuôn `scripts/load_fred.py`.
- (T1.5) DAG mới `finsight_asset_onboarding` và task làm mới danh mục Binance: Mục 3.8. Hai DAG dùng chung Airflow pool
  `binance_api` (1 slot) và `dbt` (1 slot) để không gọi Binance song song quá mức và không chạy hai `dbt build` cùng lúc.

### 3.7 Dynamic Asset Universe (T1.5)

Mục tiêu: người dùng tự chọn đồng tiền; hệ thống chỉ nạp những đồng **được chọn và hợp lệ**, bằng đúng
client/extractor/loader/sync, MERGE, watermark và dbt hiện có. Không viết lại ingestion, không nạp toàn bộ Binance.

**Dữ kiện Binance đã kiểm chứng (25/10/2026):**

- `GET /api/v3/exchangeInfo?symbol=ETHUSDT` trả `symbol`, `status` (`TRADING`), `baseAsset` (`ETH`), `quoteAsset` (`USDT`),
  `isSpotTradingAllowed`, `filters`; giới hạn `REQUEST_WEIGHT` 6.000/phút.
- Toàn sàn có 1.383 cặp spot đang giao dịch, 516 cặp có quote USDT. Response đầy đủ nặng 6–15 MB: **không gọi trong HTTP
  request của người dùng**; làm mới danh mục bằng job và tra theo từng symbol khi xác minh.
- `exchangeInfo` không có tên đầy đủ hay định danh coin xuyên sàn: `baseAsset` chỉ duy nhất **trong Binance**.

**Định danh (tránh nhầm token cùng ký hiệu):**

| Khái niệm | Ví dụ | Quy tắc |
|---|---|---|
| Coin identity (`asset_key`) | `BINANCE:ETH` | `exchange:baseAsset`; mọi bảng mới khoá theo đây hoặc theo pair, không theo ticker trần |
| Ticker | `ETH` | Chỉ để hiển thị/tìm kiếm; nhiều nguồn có thể dùng cùng ticker cho token khác nhau |
| Trading pair (`symbol`) | `ETHUSDT` | Grain hiện có của RAW/MART; MVP chỉ nhận quote `USDT`, spot, `status = TRADING` |
| Chain (TVL) | `Ethereum` | Chỉ qua `dim_chain` tuyển chọn; **không** gán TVL cho token vì trùng tên/ticker với một chain |

**Nguồn tập trung — dùng lại cấu trúc có sẵn, chỉ thêm phần thiếu:**

- `dbt/seeds/binance_assets.csv` giữ 4 core asset (lịch sử từ 2019, `is_core = true`), như hiện tại.
- Thêm schema `FINSIGHT.CONTROL` (SQL trong `infra/snowflake/03_control_access.sql` + `04_control_tables.sql`, chủ dự án chạy) cho trạng thái vận hành, không
  phải dữ liệu thị trường:

| Bảng | Grain / key | Trường tối thiểu |
|---|---|---|
| `CONTROL.BINANCE_SYMBOL` | `symbol` | `base_asset, quote_asset, status, is_spot, refreshed_at` (chỉ cặp USDT spot TRADING; làm mới mỗi ngày) |
| `CONTROL.ASSET_REGISTRY` | `symbol` | `asset_key, base_asset, quote_asset, display_name, status, backfill_start, requested_at, ready_at, data_through, last_error, attempts, updated_at` |
| `CONTROL.WATCHLIST` | `watchlist_name + symbol` | `watchlist_name` (ví dụ `default`, `defi`), `added_at`; tối đa 3 watchlist, mỗi watchlist 10 dòng. Chưa có dòng nào → `default` = 4 core asset |
| `CONTROL.DAILY_BRIEF` (T3.5) | `brief_date + watchlist_name` | `window_days, status, markdown, response_json, cost_usd, seconds, data_as_of, created_at`; MERGE theo key (chạy lại cùng ngày ghi đè) |
| `CONTROL.API_USAGE` (T6.5) | `usage_date` (UTC) | `llm_cost_usd, llm_calls, requests`; một dòng mỗi ngày, cho trần chi phí Mục 6.3 |
| `CONTROL.REQUEST_LOG` (T6.5) | `request_id` | Các trường log ở Mục 6.4 |

- `ASSET_REGISTRY.status`: `requested → validating → backfilling → ready`, hoặc `unsupported` (không phải USDT spot TRADING,
  không có nến), `error` (job lỗi, có `last_error`, cho phép thử lại), `disabled` (chủ sở hữu tắt). Trạng thái hiển thị cho người
  dùng: `ready`, `loading` (requested/validating/backfilling), `unsupported`, `stale` (ready nhưng ngày mới nhất trong MART
  cũ hơn hôm qua − 1 ngày), `error`.
- dbt: thêm source `control.asset_registry`; `dim_asset` = seed ∪ registry `ready` (cột mới `asset_key`, `is_core`,
  `data_from`); model mới `mart_asset_universe` (đọc được bởi role agent: `symbol, asset_key, base_asset, display_name,
  is_core, chain_slug, data_from, data_through, status`) để agent, resolver và UI dùng **cùng một** danh sách.
- Danh sách nạp hằng ngày (`sync.py`) = core ∪ registry `ready`; khi CONTROL chưa tồn tại (test offline, môi trường mới),
  rơi về `MVP_SYMBOLS` và ghi log cảnh báo.

### 3.8 Onboarding và backfill có kiểm soát (T1.5)

Khi người dùng thêm một đồng chưa có dữ liệu, **HTTP request chỉ ghi yêu cầu** (registry `requested`, watchlist) và trả về
ngay; mọi việc dài chạy trong Airflow:

```text
POST /watchlist (thêm ARBUSDT)
  → API: ARBUSDT có trong CONTROL.BINANCE_SYMBOL? không → 422 unsupported
         đã ready? → thêm vào watchlist, xong
         chưa có → INSERT registry (requested) nếu chưa có dòng (idempotent), thêm vào watchlist,
                   kích hoạt DAG onboarding ngay (Airflow REST API), trả status "loading"
DAG finsight_asset_onboarding (kích hoạt theo yêu cầu + lịch dự phòng mỗi ngày 01:30 UTC, max_active_runs=1, pool binance_api/dbt)
  1. Nhận việc: UPDATE ... SET status='validating' WHERE symbol IN (≤ 3 dòng requested) AND status='requested' (khoá bằng điều kiện)
  2. Xác minh: GET exchangeInfo?symbol=…  (TRADING, spot, quote USDT) → sai: unsupported
  3. Kiểm tra dữ liệu đã có: watermark hiện có trong RAW (get_watermark) → chỉ nạp phần thiếu
  4. Backfill: load_window(symbol, backfill_start → now) bằng code hiện có (nến đã đóng, cửa sổ tháng, MERGE)
  5. dbt build --select stg_binance_kline+ dim_asset+ (pool dbt) → mart có dữ liệu
  6. Đánh dấu ready + data_through; từ đây đồng này vào lịch nạp hằng ngày
  lỗi ở bất kỳ bước → status error, last_error (không chứa secret), attempts+1; tối đa 3 lần tự thử lại
```

Bất biến phải giữ: idempotent (chạy lại không trùng dòng, MERGE theo grain); watermark + lookback như hiện tại; không nạp nến
chưa đóng; không có hai job cùng nạp một symbol (khoá trạng thái + `max_active_runs=1`); retry/backoff qua `retrying_http`;
một đồng chỉ `ready` khi MART đã có dữ liệu của nó.

**Kích hoạt ngay:** API gọi `POST /api/v2/dags/finsight_asset_onboarding/dagRuns` của Airflow 3 (xác minh endpoint và cách
lấy token trên phiên bản Airflow đang chạy; cấu hình `AIRFLOW_API_URL` + thông tin đăng nhập Airflow trong `.env`, không log).
Kích hoạt lỗi hoặc Airflow không chạy → request vẫn thành công với `loading`, ghi cảnh báo; lần chạy dự phòng hằng ngày sẽ nhận
yêu cầu (không chạy mỗi giờ: mỗi lần đọc registry đánh thức warehouse, xem thay đổi #29). Nhờ
khoá trạng thái ở bước 1, kích hoạt nhiều lần không gây nạp trùng. Chạy `make add-asset SYMBOL=LINKUSDT` (CLI) cũng đi qua cùng
đường này.

**Token gốc của một chain:** khi đồng mới là token gốc của một chain có TVL trên DefiLlama (ví dụ AVAX → Avalanche), hệ thống
**không tự ánh xạ** theo ticker. Job onboarding chỉ ghi gợi ý vào log của job; việc thêm dòng vào
`dbt/seeds/defillama_chains.csv` (và nhờ Mục 2.7, vào danh sách nạp TVL) là thay đổi có review như code, kèm kiểm tra slug
trên DefiLlama và một known-answer TVL.

### 3.9 Giới hạn và chi phí (MVP, cấu hình được)

| Giới hạn | Giá trị | Lý do |
|---|---|---|
| Số watchlist | 3 | Đủ cho vài chủ đề (ví dụ core, DeFi, layer 1); mỗi watchlist có thể có brief theo lịch |
| Đồng mỗi watchlist | 10 | Báo cáo đọc được; tối đa 45 cặp tương quan |
| Tài sản active toàn hệ thống (core + registry) | 20 | Prompt Quick SQL in danh sách tài sản; chi phí lưu trữ và thời gian nạp hằng ngày |
| Backfill mặc định cho đồng mới | 365 ngày (tối đa 730) | Đủ cho volatility/drawdown/tương quan; ~8.760 nến/năm/đồng |
| Onboarding mỗi lần chạy DAG | 3 đồng | Giữ trọng số Binance thấp (một backfill 365 ngày ≈ 9 request klines) |
| Yêu cầu đồng mới mỗi ngày (toàn hệ thống) | 10 | Chặn vòng lặp do lỗi client hoặc script, không phải chống người dùng |

Vượt giới hạn → API trả lỗi rõ ràng (409/429), không âm thầm cắt bớt.

---

## 4. Metric catalog (T2)

### 4.1 Mở rộng `semantic/metrics.yml`, không tạo catalog thứ hai

Mỗi metric hiện đã có `id, name, synonyms, sql, unit, definition, pitfalls`. Thêm các trường (cập nhật `src/semantic/layer.py`,
giữ `extra="forbid"`):

| Trường | Ý nghĩa |
|---|---|
| `grain` | `asset_day`, `chain_day`, `day`, `month`, `period` |
| `sources` | `binance`, `fred`, `defillama` |
| `template` | SQL tham số hoá cho research mode (Mục 5.3); NULL nếu metric chỉ dùng trong Quick SQL |
| `params` | tên, kiểu, miền giá trị hợp lệ (ví dụ `symbol ∈ dim_asset`, `window_days ∈ [7, 365]`) |
| `min_observations` | số quan sát tối thiểu; ít hơn → `insufficient_data` |
| `pit_mode` | `as_known` hoặc `latest` hoặc `retrospective` |
| `golden_case` | một bộ tham số + giá trị đúng đã kiểm tra tay (dùng cho dbt/pytest) |

### 4.2 Metric mới hoặc chuẩn hoá

| Metric ID | Công thức | Quy tắc |
|---|---|---|
| `daily_return` (có) | close_t / close_(t−1) − 1 | Daily close từ nến đã đóng theo ngày UTC |
| `period_return` (có) | `EXP(SUM(log_return)) − 1` | Không cộng `daily_return` |
| `volatility_30d` (có) | `STDDEV_SAMP(log_return)` 30 dòng × `SQRT(365)` | NULL khi < 30 return |
| `max_drawdown` | `MIN(close / running_max(close) − 1)` trong kỳ | Ghi rõ kỳ quan sát; running max tính từ đầu kỳ |
| `yield_change_bps` | (yield_t − yield_(t−1)) × 100 | 4,10% → 4,20% là +10 bps, không phải +10% |
| `return_correlation` | `CORR(return_a, return_b)` | Chỉ trên ngày cả hai có return; trên **return**, không trên giá; báo n; n < 30 → `insufficient_data` |
| `tvl_change_7d` | tvl(d) / tvl(d − 7 ngày lịch) − 1 | Join theo ngày lịch, không theo "7 dòng trước"; thiếu → NULL |
| `forward_return_nd` | close(t+n) / close(t) − 1 cho các ngày sự kiện t | Sự kiện phải **đã biết** vào ngày t (giá trị PIT); báo số **sự kiện**, cảnh báo cửa sổ chồng nhau |
| `cpi_mom_change` | CPI tháng m / CPI tháng m−1 − 1 theo **giá trị công bố lần đầu** | Chỉ gán cho ngày ≥ ngày công bố; không forward-fill trước ngày công bố |

### 4.3 Luật chống JOIN sai và look-ahead bias

- Không join hai fact khác grain. Tổng hợp mỗi bên về cùng grain (asset-day, chain-day) trước khi join; test số dòng.
- Crypto 24/7, macro có ngày nghỉ: luật as-of hiện tại (`realtime_start <= X <= realtime_end`) áp dụng cho DFF, DGS10, CPI.
  Dữ liệu FRED chỉ có độ phân giải ngày; không khẳng định biết giá trị theo giờ (giữ ghi chú giả định trong
  `mart_macro_daily.sql`).
- Phân biệt `as_known` (FRED, TVL thu hằng ngày) với `latest`/`retrospective` (TVL backfill). Báo cáo bắt buộc ghi chế độ.
- TVL và giá: chỉ mô tả tương quan, không kết luận nhân quả; báo n, tỉ lệ thiếu, độ trễ đã chọn.
- So sánh nhiều tổ hợp (nhiều tài sản × nhiều ngưỡng) dễ ra kết quả "có ý nghĩa" do ngẫu nhiên; báo cáo ghi số tổ hợp đã thử.

### 4.4 Verified queries cần thêm (`semantic/verified_queries.yml`)

1. Max drawdown BTC trong một năm.
2. Tương quan return BTC–ETH trong một năm, có n.
3. Daily return BTC vào những ngày lợi suất 10 năm tăng > 10 bps (giá trị PIT).
4. Return ETH so với `tvl_change_7d` của Ethereum, join theo ngày, không fan-out.
5. CPI MoM (công bố lần đầu) so với return crypto theo tháng, chỉ dùng tháng đã công bố.

Không trùng câu nào với `eval/gold_questions.jsonl` hoặc bộ câu research (đã có test kiểm tra trùng; mở rộng test cho bộ mới).
Trạng thái 25/10/2026: **chưa làm** (Mục 2.6) — thực hiện trong T2.5, kèm chạy lại `make eval` vì đổi ngữ cảnh prompt.

### 4.5 Catalog cho tài sản động (T2.5)

- Kiểu tham số `symbol` chỉ nhận tài sản `ready` trong `mart_asset_universe` (thay cho `coverage.assets` cố định). Tài sản
  `loading/unsupported/error` → `TaskError` có tên, không chạy SQL.
- Kiểu tham số mới `symbol_list`: 1–10 symbol `ready`, không trùng; render thành `IN ('A', 'B')` bằng literal đã kiểm.
- Kết quả **nhiều dòng**: metric khai báo `row_key` (ví dụ `SYMBOL`, hoặc cặp `SYMBOL_A, SYMBOL_B`); evidence lưu
  `rows: [{row_key…, values…, n}]`; grounding đối chiếu với mọi giá trị của các dòng được dẫn. Template một dòng hiện có giữ
  nguyên hợp đồng.
- Đồng mới niêm yết có ít lịch sử: `min_observations` áp cho **từng dòng**; dòng thiếu dữ liệu trả `insufficient_data` cho
  riêng đồng đó, không kéo cả báo cáo về lỗi.
- Không gán chỉ số không phù hợp: metric TVL chỉ nhận chain trong `dim_chain`; metric vĩ mô không nhận symbol.

Metric mới (template + golden case kiểm chứng độc lập như 10 metric hiện có):

| Metric ID | Đầu ra (mỗi dòng) | Ghi chú |
|---|---|---|
| `watchlist_snapshot` | `SYMBOL, LAST_CLOSE, PERIOD_RETURN, ANNUALIZED_VOLATILITY, MAX_DRAWDOWN, N_DAYS, DATA_THROUGH` | Một truy vấn cho cả watchlist; công thức giống metric đơn đã có |
| `return_correlation_matrix` | `SYMBOL_A, SYMBOL_B, RETURN_CORRELATION, N_DAYS` | Mọi cặp (a < b); n < 30 → `insufficient_data` cho cặp đó |
| `risk_signals` | `SYMBOL, SIGNAL_ID, SIGNAL_DATE, VALUE, THRESHOLD, UNIT` | Đọc tín hiệu đã tính trong `mart_risk_signal_daily` (Mục 4.6) |
| `data_status` | `SYMBOL, STATUS, DATA_FROM, DATA_THROUGH, DAYS_STALE` | Độ tươi và độ phủ để báo cáo nói rõ giới hạn |

### 4.6 Risk signals bằng luật (T2.5)

Tín hiệu là **luật cố định do code tính trong dbt**, có định nghĩa, đơn vị, cửa sổ, số quan sát tối thiểu và test. LLM chỉ
đọc kết quả, không tính và không đặt ra tín hiệu mới. Ngưỡng nằm trong seed `dbt/seeds/risk_signal_rules.csv` (review như
code); model `mart_risk_signal_daily` (grain `trade_date + symbol + signal_id`, chỉ dòng có tín hiệu bật).

| `signal_id` | Định nghĩa | Đơn vị / ngưỡng mặc định | Cửa sổ, tối thiểu |
|---|---|---|---|
| `abnormal_move` | \|daily_return\| / STDDEV_SAMP(daily_return của 90 ngày **trước** ngày đó) | σ ≥ 3 | 90 ngày, ≥ 60 quan sát |
| `volatility_spike` | volatility_30d / median(volatility_30d của 180 ngày trước) | tỉ lệ ≥ 1,5 | 180 ngày, ≥ 120 quan sát |
| `drawdown_alert` | close / MAX(close trong 90 ngày gần nhất) − 1 | fraction ≤ −0,20 | 90 ngày, ≥ 30 quan sát |
| `tvl_drop` | `chain_tvl_change_7d` của chain được ánh xạ | fraction ≤ −0,15 | Chỉ chain trong `dim_chain`, ≥ 30 ngày TVL; ghi `is_retrospective` |
| `high_correlation` | `return_correlation` 30 ngày giữa hai đồng **trong cùng watchlist** | ≥ 0,90 | Tính khi tạo brief (phụ thuộc watchlist), n ≥ 25 |

Quy tắc: cửa sổ chỉ dùng dữ liệu **trước hoặc bằng** ngày tín hiệu (không nhìn tương lai); thiếu quan sát → không bật, không
bịa giá trị; `tvl_drop` không áp cho token không có chain ánh xạ. Test bắt buộc: một known-answer cho mỗi luật trên một ngày
lịch sử đã tính tay (Coding Agent tìm và kiểm bằng phép tính độc lập, không giả định trước ngày nào), test ngưỡng biên,
test "không đủ quan sát → không có dòng".

**Hiệu chỉnh ngưỡng:** return crypto có đuôi dày, nên ngưỡng như 3σ có thể bật thường xuyên hơn phân phối chuẩn gợi ý. Ngưỡng
mặc định là điểm bắt đầu, không phải kết luận. T2.5 phải thống kê **tần suất bật** trên dữ liệu thật cho từng luật và từng
đồng (số ngày bật / số ngày đủ quan sát) và ghi vào tài liệu. Luật bật quá nhiều (ví dụ > 5% số ngày) là tín hiệu ồn: chỉnh
ngưỡng trong seed như một thay đổi có review, ghi lý do. Không chỉnh ngưỡng để làm khớp known-answer.

**Cách trình bày:** tín hiệu mô tả dữ liệu lịch sử, không phải dự báo hay khuyến nghị. Mỗi phần risk signals trong UI và
báo cáo kết thúc bằng câu "Tín hiệu mô tả dữ liệu lịch sử theo luật cố định, không phải khuyến nghị đầu tư" (theo ngôn ngữ báo
cáo), do code thêm, không do writer viết.

---

## 5. Research workflow (T3)

### 5.1 Luồng xử lý

```text
Question → Router ──► QUICK_SQL → graph hiện tại (không đổi) → Answer
                 └──► RESEARCH  → Planner (LLM, Structured Outputs: tasks = [{metric_id, params}])
                                 → Resolver (kiểm metric_id + params với catalog; ngoài catalog → báo hạn chế)
                                 → Renderer (template → SQL) → SQLGuard → Executor (role chỉ đọc)
                                 → Calculator (Python thuần, nếu metric cần hậu xử lý)
                                 → Evidence builder → Writer (LLM, Structured Outputs) → Grounding check (code)
                                 → ResearchAnswer
```

- Đặt trong `src/agents/research/` (graph riêng `research_graph.py`, nodes riêng). **Không sửa** `graph.py` của Quick SQL ngoài
  việc dùng chung hàm.
- Router gọi ở cấp `answer_*`; `POST /ask` giữ hành vi hiện tại (luôn Quick SQL) để tương thích ngược.
- Trạng thái (Mục 2.6): router được thay bằng chế độ người dùng chọn tường minh (tab/endpoint); ghi trong gap log. Nếu sau này
  thêm router, giữ hợp đồng ở Mục 5.3 và đo routing accuracy (Mục 7.2).
- Pulse: Daily Brief đi qua cùng graph với một **kế hoạch cố định do code dựng** thay cho Planner (Mục 5.7).

### 5.2 Vì sao metric-first

Research mode **không để LLM sinh SQL tự do** cho các con số trong báo cáo:

- LLM chỉ chọn `metric_id` và tham số; SQL lấy từ template đã kiểm chứng → cùng câu hỏi cho cùng số, test được bằng golden case.
- Evidence (SQL, nguồn, cửa sổ, n) có sẵn từ template, không phải suy ra.
- Câu hỏi ngoài catalog: dùng Quick SQL làm dự phòng **chỉ khi** kết quả được gắn nhãn "ngoài catalog, chưa kiểm chứng" trong báo
  cáo; không trộn vào findings chính.

### 5.3 Contracts từng node

| Node | Input → Output | Guardrail |
|---|---|---|
| Router | question → `quick_sql` \| `research` | Luật trước (từ khoá: "báo cáo", "tương quan", "so với", "khi ... thì", nhiều nguồn); LLM chỉ khi mơ hồ; mặc định `quick_sql` |
| Planner | question + danh sách metric (id, mô tả, params) → 1..4 task | Structured Outputs strict; `metric_id` là enum từ catalog; tối đa 4 task |
| Resolver | task → task hợp lệ hoặc lỗi có tên | Kiểm params theo miền (`symbol ∈ dim_asset`, khoảng ngày trong dữ liệu, `window_days`); không tự bịa công thức |
| Renderer | task → SQL | Chỉ thay tham số đã kiểm vào template (không nối chuỗi tuỳ ý); kết quả vẫn đi qua `SQLGuard` |
| Executor | SQL → rows + metadata (thời gian, số dòng, `data_as_of`) | `agent_warehouse()` hiện có: role chỉ đọc, timeout 30 s, ≤ 100 dòng (cấu hình riêng nếu metric cần nhiều dòng hơn để hậu xử lý, tối đa 5.000) |
| Calculator | rows → số liệu tổng hợp | Python thuần, có unit test; không gọi LLM |
| Evidence builder | kết quả → evidence items | Mỗi item: `id, metric_id, params, sql, sources, data_window, n, value, unit, pit_mode` |
| Writer | question + evidence → findings + caveats | Structured Outputs; mỗi finding phải dẫn `evidence_ids`; được dùng số **chỉ** từ evidence |
| Grounding check | findings + evidence → pass / fail | Code (Mục 5.4) |

### 5.4 Grounding check (bắt buộc, bằng code)

- Trích mọi con số trong `claim` của findings (kể cả dạng %, bps, "B"/"tỷ").
- Mỗi con số phải khớp một `value` trong evidence được dẫn, sau khi quy đổi đơn vị và làm tròn (sai số tương đối ≤ 0,5% hoặc
  đúng tới chữ số đã hiển thị).
- Không khớp → gọi lại Writer **một lần** kèm danh sách số sai; vẫn sai → bỏ finding đó, `status = partial`, ghi lý do.
- Không dùng LLM-as-judge cho kiểm tra số.

### 5.5 Ngân sách và chính sách lỗi

| Giới hạn | Giá trị mặc định (cấu hình được) |
|---|---|
| Task mỗi câu hỏi | 4 |
| Câu SQL mỗi câu hỏi | 8 |
| Lần gọi LLM mỗi câu hỏi | 6 (router 0–1, planner 1, repair ≤ 2, writer ≤ 2) |
| Thời gian | 60 s (research), 30 s mỗi SQL |
| Chi phí LLM | $0,01 mỗi câu research |
| Daily Brief (Mục 5.7) | ≤ 10 task, ≤ 10 SQL, 0 lần gọi planner, ≤ 2 lần gọi writer, 90 s, $0,02 |
| Daily Brief theo lịch | ≤ 3 brief mỗi ngày (một cho mỗi watchlist), tức ≤ $0,06/ngày; tính vào trần chi phí ngày (Mục 6.3) |

- Retry chỉ: lỗi mạng tạm thời, `SQL compilation error`, vi phạm guard sửa được (giữ `FINAL_VIOLATIONS` hiện có, tối đa 2 lần).
- Dừng an toàn khi: thiếu dữ liệu (`insufficient_data`), dữ liệu quá cũ (dựa `data_as_of` và freshness), timeout, metric không
  xác định, vượt ngân sách. Không tự dựng số thay thế.
- Không multi-agent; graph có conditional edges, mỗi node một trách nhiệm.

### 5.6 Output contract (`src/models/schemas.py`, model mới `ResearchResponse`)

```json
{
  "mode": "research",
  "question": "...",
  "status": "complete | partial | insufficient_data | error",
  "analysis_window": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
  "data_as_of": "YYYY-MM-DD",
  "findings": [{"claim": "...", "evidence_ids": ["ev1"]}],
  "evidence": [{"id": "ev1", "metric_id": "return_correlation", "params": {"a": "BTCUSDT", "b": "ETHUSDT"},
                "sql": "SELECT ...", "sources": ["Binance"], "data_window": "2025-01-01..2025-12-31",
                "n": 364, "value": 0.81, "unit": "ratio", "pit_mode": "latest"}],
  "caveats": ["Correlation does not imply causation", "..."],
  "plan": [{"metric_id": "...", "params": {}, "status": "done | failed | skipped", "reason": null}],
  "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
  "total_seconds": 0.0
}
```

Số liệu thiếu là `null` kèm lý do, **không bao giờ** là `0.0`. Ví dụ trên chỉ minh hoạ hình dạng, không phải kết quả thật.

Pulse (T2.5): evidence của metric nhiều dòng thêm `rows: [{"key": {"symbol": "ETHUSDT"}, "values": [...], "n": 30}]`; evidence
một dòng giữ hình dạng hiện có, nên client cũ không vỡ. `status` thêm giá trị `declined` (đã có trong code hiện tại).

### 5.7 Daily Brief (T3.5)

Không tạo agent mới. Brief = research workflow hiện có với kế hoạch do **code** dựng từ watchlist, nên các phần đã kiểm
chứng (resolver, template, SQLGuard, role chỉ đọc, writer, grounding, caveat tự động, report Markdown) được dùng lại nguyên vẹn.

```text
BriefRequest(symbols ≤ 10 hoặc watchlist_name, window_days 7–365, mặc định 30)
  → build_brief_plan (code, không LLM):
      data_status(symbols)                       # độ tươi, độ phủ
      watchlist_snapshot(symbols, window)        # hiệu suất, volatility, drawdown
      return_correlation_matrix(symbols, window) # nếu ≥ 2 đồng
      risk_signals(symbols, window)              # tín hiệu đã tính bằng luật
      macro_rate_change(window), inflation_change(window)
      tvl_change(chain, window) cho chain được ánh xạ với các đồng trong watchlist (≤ 4)
  → execute → write → check (graph research hiện có, bỏ qua node plan)
  → BriefResponse = ResearchResponse + sections cố định
```

Báo cáo gồm, theo thứ tự: market overview, watchlist performance (bảng từ `watchlist_snapshot`), risk signals (từng tín hiệu
kèm luật, ngưỡng, giá trị), bối cảnh crypto–macro, findings + caveats, evidence + nguồn + SQL, độ tươi dữ liệu, thời gian chạy
và chi phí LLM. Writer chỉ viết findings và caveats như hiện nay; **các bảng và danh sách tín hiệu do code dựng**, nên brief
vẫn dùng được khi writer lỗi hoặc grounding loại hết findings (`status = partial`, phần bảng giữ nguyên — đây cũng là chế độ
"không dùng LLM" cho product evaluation, Mục 7.5).

Đồng `loading/stale/error` trong watchlist: vẫn tạo brief cho các đồng sẵn sàng; phần "Data status" nêu rõ đồng nào bị loại và vì
sao. Cuối báo cáo có câu "không phải khuyến nghị đầu tư" do code thêm (Mục 4.6).

**Hai chế độ, cùng một hàm `generate_brief`:**

- **Theo yêu cầu:** `POST /brief`, nút **Generate Daily Brief**, `make brief WATCHLIST=default`.
- **Theo lịch (P1.5, không cần cloud):** task `generate_daily_brief` trong DAG `finsight_daily` hiện có, chạy **sau**
  `dbt_build_marts` (chỉ khi dữ liệu đã build xong). Mỗi watchlist một brief, `window_days` = 30. Kết quả MERGE vào
  `CONTROL.DAILY_BRIEF`; UI và `GET /briefs` đọc từ đó, nên mở máy buổi sáng là có brief. Gửi brief qua kênh riêng
  (Discord/Telegram) **hoãn sang P2** theo quyết định của chủ sở hữu (25/10/2026): MVP chỉ xem trong UI.
- Task brief chạy bằng venv FinSight trong image Airflow (đã cài `requirements.txt`); truy vấn vẫn dùng `FINSIGHT_AGENT` chỉ
  đọc MART (mount khóa read-only như API), ghi `CONTROL.DAILY_BRIEF` bằng role pipeline. Cần `OPENAI_API_KEY` trong môi trường
  Airflow; không in ra log.
- Brief lỗi → task Airflow báo lỗi (Mục 6.4), dữ liệu đã nạp không bị ảnh hưởng. Vượt trần chi phí ngày → lưu brief chế độ không
  LLM (bảng + evidence, `partial`) thay vì bỏ qua.

---

## 6. API, UI, báo cáo (T4)

- `POST /research` (mới), cùng quy ước với `/ask`: hàm `def` (threadpool), `Depends` để test, 422 cho input sai, 503 cho lỗi
  phụ thuộc, `status` trong body cho kết quả không hoàn chỉnh.
- `POST /ask`, `GET /health`: không đổi; test cũ phải xanh (APP-01).
- Streamlit: thêm tab **Research** cạnh màn hình hiện có. Hiển thị theo thứ tự: trạng thái + `data_as_of` → findings → bảng/biểu
  đồ từng evidence → SQL từng evidence → caveats → kế hoạch đã chạy (từng bước, trạng thái) → chi phí/thời gian. Nút tải Markdown.
- Timeout UI cho research: 120 s hiện tại đủ với ngân sách 60 s; hiển thị spinner, giữ cơ chế khoá nút bằng `session_state`.
- Báo cáo Markdown: câu hỏi, khoảng thời gian, timezone (UTC), nguồn + thời điểm lấy dữ liệu, 3–5 findings, bảng evidence (metric,
  giá trị, đơn vị, n, SQL), caveats (độ trễ công bố, TVL retrospective, mẫu nhỏ, tương quan ≠ nhân quả), phần `partial` nếu có.
- Log một dòng mỗi câu research (giống `answer_question`): mode, status, số task, số SQL, chi phí, thời gian. Không log prompt
  chứa dữ liệu nhạy cảm.

### 6.1 Watchlist UI và Daily Brief (T4.5)

Thêm tab **Watchlist & Brief** vào Streamlit (UI vẫn là thin client, không import `src/`, không giữ khóa Snowflake/OpenAI):

- Ô tìm kiếm đồng tiền (theo ticker/pair, dữ liệu từ `CONTROL.BINANCE_SYMBOL` qua API; không gọi Binance từ UI).
- Thêm/xoá đồng trong watchlist; hiển thị trạng thái từng đồng: `ready`, `loading`, `unsupported`, `stale`, `error` (kèm lý
  do ngắn); đồng `loading` tự làm mới trạng thái khi người dùng bấm "Refresh" (không polling liên tục).
- Chọn khoảng thời gian nghiên cứu (7, 30, 90, 365 ngày hoặc tuỳ chọn).
- Nút **Generate Daily Brief** (khoá trong lúc chạy như các nút hiện có) → hiển thị báo cáo theo Mục 5.7 → tải Markdown.
- Chọn watchlist (tối đa 3, có tên); mặc định mở brief theo lịch mới nhất của watchlist đó (`GET /briefs`), kèm ngày dữ liệu
  và trạng thái; xem lại brief các ngày trước.
- Một chủ sở hữu: watchlist lưu trong `CONTROL.WATCHLIST` theo tên; không có đăng ký/đăng nhập (Mục 6.3).
- Dòng nhỏ hiển thị chi phí LLM hôm nay so với trần ngày (`GET /usage/today`).
- Mở rộng danh sách tài sản **không** nới SQLGuard, quyền Snowflake hay giới hạn chi phí truy vấn: agent vẫn chỉ đọc MART.

### 6.2 API mới (T4.5)

Mọi endpoint trừ `GET /health` đi qua **cùng một** dependency FastAPI kiểm tra truy cập (Mục 6.3); không có vai trò.

| Endpoint | Hành vi |
|---|---|
| `GET /assets/search?q=` | Tìm trong `CONTROL.BINANCE_SYMBOL` + trạng thái registry; ≤ 20 kết quả |
| `GET /assets/{symbol}` | Trạng thái dữ liệu (`mart_asset_universe` + registry) |
| `POST /assets/{symbol}/retry`, `POST /assets/{symbol}/disable` | Thử lại onboarding lỗi / tắt tài sản |
| `GET /watchlists`, `GET /watchlists/{name}`, `PUT /watchlists/{name}`, `DELETE /watchlists/{name}` | Đọc/ghi watchlist có tên; thêm đồng chưa có dữ liệu → tạo yêu cầu onboarding và kích hoạt DAG (Mục 3.8), trả `loading` |
| `POST /brief` | Daily Brief theo yêu cầu (Mục 5.7); `def` (threadpool), 422/503 như `/ask` |
| `GET /briefs?watchlist=&limit=`, `GET /briefs/{date}?watchlist=` | Brief đã lưu trong `CONTROL.DAILY_BRIEF` (theo lịch hoặc theo yêu cầu) |
| `POST /assets/check` | Kiểm tra coin gõ tự do (`{"text": "link, avax arbb"}`), không ghi gì: từng coin có trên Binance không, thêm sẽ làm gì, gợi ý khi gõ nhầm |
| `POST /watchlists/{name}/add` | Thêm các coin đúng vào watchlist, báo từng coin sai hoặc vượt giới hạn; coin sai không chặn coin khác |
| `GET /usage/today` | Chi phí LLM hôm nay, số lần gọi, trần ngày còn lại |
| `GET /health/data` | Ngày dữ liệu mới nhất từng nguồn, brief hôm nay đã có chưa, tài sản `stale/error` (Mục 6.4) |
| `POST /ask`, `POST /research`, `GET /health` | Giữ nguyên hợp đồng; chỉ thêm kiểm tra truy cập (health: công khai) |

Ghi CONTROL qua một kết nối riêng dùng role mới `FINSIGHT_APP` (chỉ SELECT/INSERT/UPDATE trên schema `CONTROL`, không quyền
RAW/STAGING/CORE, không quyền ghi MART; khóa riêng, mount read-only như khóa agent). Role này vẫn cần dù chỉ có một người dùng:
nó giữ `FINSIGHT_AGENT` chỉ đọc và không đưa khóa pipeline `FINSIGHT_ENGINEER` vào API. Câu hỏi của người dùng vẫn chạy bằng
`FINSIGHT_AGENT` chỉ đọc MART như hiện tại.

### 6.3 Bảo vệ truy cập và kiểm soát chi phí cho một chủ sở hữu (T6.5)

FinSight Pulse có **một chủ sở hữu**: không đăng ký, đăng nhập, mật khẩu hay vai trò (Mục 9.1). Điều cần bảo vệ là (1) endpoint
không bị người lạ gọi khi deploy, (2) chi phí OpenAI/Snowflake không vượt kiểm soát vì lỗi hay vòng lặp. Cấu hình bằng
`AUTH_MODE`:

| `AUTH_MODE` | Dùng khi | Cơ chế |
|---|---|---|
| `local` (mặc định) | Chạy trên máy chủ sở hữu | API và UI chỉ nghe trên loopback: `make run`/`make ui` bind `127.0.0.1`; `docker-compose.yml` publish `127.0.0.1:8000:8000` và `127.0.0.1:8501:8501` (hiện đang publish mọi địa chỉ). Không cần khóa |
| `deployed` | Chạy trên VM hoặc máy mở ra mạng | Lớp ngoài: reverse proxy HTTPS có basic auth (mật khẩu lưu dạng hash), **hoặc** chỉ truy cập qua mạng riêng (Tailscale/WireGuard); chọn một và ghi vào tài liệu vận hành. API không publish ra internet, chỉ proxy và UI gọi được. Lớp trong: một khóa dịch vụ `FINSIGHT_SERVICE_KEY` trong header `X-API-Key`, so sánh bằng `hmac.compare_digest`; UI giữ khóa ở phía server, không lộ ra trình duyệt |

- `deployed` mà thiếu `FINSIGHT_SERVICE_KEY` → API **không khởi động** (fail closed). Thiếu/sai khóa → 401, không nêu lý do
  nội bộ. Logic nằm trong một dependency FastAPI duy nhất, nên sau này muốn nhiều người dùng chỉ phải thay một chỗ (không
  chuẩn bị trước bảng hay vai trò cho việc đó).
- **Trần chi phí LLM toàn hệ thống mỗi ngày** (mặc định $1/ngày UTC, cấu hình được), tính từ `usage.cost_usd` đã có, lưu trong
  `CONTROL.API_USAGE`. Trước mỗi request dùng LLM, **giữ chỗ** bằng ngân sách tối đa của request (research $0,01, brief $0,02),
  sau đó ghi chi phí thật; không đủ chỗ → 429 kèm lý do. Các endpoint không gọi LLM (tìm kiếm, watchlist, brief đã lưu) vẫn
  chạy. Brief theo lịch tính vào cùng trần.
- **Rate limit toàn cục**, trong tiến trình (một instance): `/ask` 30/phút, `/research` và `/brief` 6/phút, `PUT /watchlists`
  30/giờ → 429 kèm `Retry-After`. Mục đích là chặn vòng lặp do lỗi client/script. Nhiều instance cần bộ đếm dùng chung: ghi
  gap log, không thêm Redis trước khi có nhu cầu thật.
- **Snowflake:** giữ timeout 30 s mỗi SQL và auto-suspend của warehouse; resource monitor theo tháng cho warehouse của
  FinSight (thông báo ở 80%, suspend ở 100%; hạn mức do chủ dự án chọn). Đã có sẵn: `FINSIGHT_MONTHLY_RM`, 20 credit/tháng,
  trong `infra/snowflake/00_setup.sql` (thay đổi #30).

### 6.4 Observability, giám sát, cảnh báo (T6.5)

- Request ID: middleware nhận/sinh `X-Request-ID`, trả lại trong response, gắn vào mọi dòng log và `QUERY_TAG` Snowflake.
- Log có cấu trúc (JSON): request_id, endpoint, mode, status, thời gian từng node LangGraph (reducer `timings` trong
  state), số SQL, SQL lỗi, số finding bị grounding loại, tokens, cost. Không log prompt đầy đủ, khóa hay dữ liệu nhạy cảm.
- Bảng `CONTROL.REQUEST_LOG` (ghi bất đồng bộ không chặn response; lỗi ghi log không làm hỏng request) để xem p50/p95, cost,
  tỉ lệ SQL lỗi, tỉ lệ grounding failure theo ngày bằng một truy vấn hoặc trang nhỏ trong Streamlit.
- Cảnh báo (MVP, không gửi ra ngoài): lỗi DAG hằng ngày, onboarding, task brief hiển thị trong Airflow UI; UI FinSight có
  dòng trạng thái hệ thống (`GET /health/data`: ngày dữ liệu mới nhất từng nguồn, brief hôm nay có chưa, chi phí so với trần);
  tài sản `stale` hiển thị trong UI. Gửi cảnh báo qua webhook (`ALERT_WEBHOOK_URL`, Discord/Telegram) **hoãn sang P2**.
  Không thêm Prometheus/Grafana trong MVP.
- Timeout/retry/fallback giữ như hiện có (30 s mỗi SQL, retry OpenAI của SDK, `retrying_http`); thêm: Binance/registry lỗi khi
  thêm tài sản → trạng thái `error`, không 500; brief khi writer lỗi → bảng + evidence (`partial`).

### 6.5 Deploy-ready (bắt buộc) và cloud deployment tối giản (tuỳ chọn) (T6.5)

**Bắt buộc — deploy-ready**, làm và kiểm được trên máy local:

- CI/CD: CI hiện có + job build image `api/ui` và `airflow`, gắn tag theo commit, đẩy lên registry (ví dụ GHCR); file compose
  cho môi trường deploy (`AUTH_MODE=deployed`, proxy, healthcheck) chạy theo tag; **rollback = chạy lại tag trước**. Chạy thử
  một lần: deploy tag A → tag B → rollback về A, ghi lại.
- Secrets: `.env` sinh từ secret manager/biến môi trường của nền tảng lúc deploy, private key Snowflake mount read-only, không
  bao giờ nằm trong image hay repo; xoay khóa dịch vụ/FRED/OpenAI có hướng dẫn trong tài liệu.
- Smoke test sau deploy: `/health`, một `/ask` có khóa dịch vụ, một request thiếu khóa → 401, một `/brief` với 2 đồng; thất bại
  → rollback.

**Tuỳ chọn — cloud:** chỉ khi chủ sở hữu cần dùng ngoài máy mình. Một máy ảo (ví dụ 2 vCPU / 8 GB) chạy Docker Compose: `api`,
`ui`, Airflow (LocalExecutor, như hiện tại) và reverse proxy HTTPS (ví dụ Caddy); Snowflake vẫn là dịch vụ ngoài. Không
Kubernetes, không microservices. Chi phí VM là cố định hằng tháng: ghi giá thật của nhà cung cấp đã chọn vào tài liệu vận
hành, không ước đoán. Khi chạy trên máy local, brief theo lịch chỉ có khi Airflow đang chạy; Airflow bắt kịp các ngày bị lỡ
như hiện nay, nhưng chỉ tạo brief cho ngày mới nhất (không tạo lại brief cho từng ngày cũ).

---

## 7. Evaluation (T5)

### 7.1 Bộ câu hỏi

- Giữ nguyên 21 câu Quick SQL hiện có; không chỉnh prompt để chữa câu holdout. Trạng thái sau T5 (Mục 2.6): bộ Quick SQL có 35
  câu (q01–q35), bộ research 21 câu (r01–r21); các task Pulse giữ nguyên cả hai bộ và chỉ thêm câu mới.
- **Viết thêm tối thiểu 30 câu mới, trong đó ít nhất 15 câu holdout**, và **viết xong (kèm đáp án) trước khi chạy agent lần
  nào**. Câu đã dùng để quyết định một thay đổi phải chuyển sang dev (quy tắc hiện có).
- Bộ research: `eval/research_questions.jsonl`, mỗi câu có `expected_route`, `expected_metrics` (danh sách metric_id), `expected_values`
  (giá trị đúng tính bằng SQL gold, kèm sai số), `must_refuse` cho câu ngoài phạm vi.
- Phân bố bắt buộc: Quick SQL mới (~10), research đa nguồn (~12), câu bẫy look-ahead/CPI/TVL retrospective (~4), từ chối + prompt
  injection (~4).

### 7.2 Chỉ số đo

| Chỉ số | Cách đo |
|---|---|
| Execution accuracy (Quick SQL) | `src/evaluation/compare.py` hiện có |
| Routing accuracy | route thực tế so với `expected_route` |
| Metric selection accuracy | tập `metric_id` trong plan so với `expected_metrics` |
| Value correctness | mỗi `expected_value` có evidence khớp trong sai số |
| Grounding rate | tỉ lệ finding qua grounding check ở lần đầu |
| Safe refusal | câu `must_refuse` không chạy SQL nào ngoài phạm vi |
| Latency p50/p95, cost | tách riêng Quick SQL và Research |

- Mọi tỉ lệ báo kèm Wilson 95% CI (dùng `wilson_interval` hiện có).
- So sánh trước/sau: cùng câu hỏi, cùng model, mỗi cấu hình 3 lần; báo phân phối, không chỉ một con số.
- Một lệnh: `make eval-research` (và `--gold-only` $0); xuất JSON vào `eval/results/` + bảng in ra terminal.

### 7.3 Ma trận kiểm thử bắt buộc

| ID | Tình huống | Kỳ vọng |
|---|---|---|
| DATA-01 | DefiLlama trả 429/5xx/timeout | Retry có backoff giới hạn; 4xx khác dừng ngay; không ghi batch dở dang |
| DATA-02 | Chạy load DefiLlama 2 lần cùng ngày | Không thêm dòng ở lần 2 |
| DATA-03 | TVL thiếu 3 ngày | Không có dòng/NULL; `tvl_change_7d` NULL; freshness cảnh báo nếu là ngày gần nhất |
| DATA-04 | Điểm TVL ngày hôm nay | Không được nạp |
| DATA-05 | TVL = 0 ở đầu lịch sử | Bị loại; không xuất hiện như giá trị 0 |
| DATA-06 | DefiLlama sửa TVL ngày cũ | Thêm dòng mới (fetched_date mới), dòng cũ giữ nguyên |
| DATA-07 | Nến Binance chưa đóng | Không dùng (test hiện có, giữ) |
| MET-01 | 10Y 4,10% → 4,20% | +10 bps |
| MET-02 | Join TVL vào `mart_market_macro_daily` | `equal_rowcount` vẫn pass |
| MET-03 | FRED sửa số về sau | As-of ngày cũ không dùng bản sửa (known-answer hiện có, giữ) |
| MET-04 | CPI tháng m trước ngày công bố | Không gán cho ngày trước ngày công bố |
| MET-05 | TVL backfill | `is_retrospective = true`, báo cáo ghi rõ |
| MET-06 | Tương quan với n < 30 | `insufficient_data` |
| AI-01 | LLM sinh DELETE/INSERT/nhiều câu | Guard chặn; role chỉ đọc vẫn chặn nếu guard sai (test integration hiện có, giữ) |
| AI-02 | SQL chạy được nhưng metric sai | Golden case phát hiện |
| AI-03 | Prompt injection trong câu hỏi | Không bỏ qua guard, không lộ secret, không chạy ngoài phạm vi |
| AI-04 | Planner chọn metric không có trong catalog | Resolver từ chối, báo hạn chế |
| AI-05 | Writer đưa số không có trong evidence | Grounding check bắt; `partial` |
| AI-06 | Vượt ngân sách | Dừng, `partial` hoặc `error` có lý do |
| APP-01 | `/ask`, UI cũ, mọi test cũ | Không regression |
| DYN-01 | Thêm cặp không phải USDT spot TRADING (hoặc không tồn tại) | 422 `unsupported`, không tạo job, không gọi Binance trong request |
| DYN-02 | Thêm cùng một đồng 2 lần / vào 2 watchlist | Một dòng registry, một job; mỗi watchlist một dòng |
| DYN-03 | Hai lần chạy DAG onboarding cùng nhận một yêu cầu | Chỉ một lần chuyển `requested → validating` thành công; không nạp trùng |
| DYN-04 | Backfill đồng mới | Đúng cửa sổ `backfill_start → now`, không nến chưa đóng, chạy lại = 0 dòng mới |
| DYN-05 | Đồng đã có một phần dữ liệu | Chỉ nạp từ watermark − lookback |
| DYN-06 | Đồng chỉ `ready` khi MART có dữ liệu | Trước đó API/UI báo `loading`, resolver từ chối |
| DYN-07 | Xoá khỏi watchlist | Không xoá dữ liệu RAW/MART; đồng vẫn nạp nếu còn trong watchlist khác hoặc là core |
| DYN-08 | Token trùng ticker với một chain, hoặc không có chain | Không có TVL (NULL), không ánh xạ theo tên |
| DYN-09 | Watchlist thứ 4; đồng thứ 11 trong một watchlist; quá 10 yêu cầu/ngày; vượt 20 tài sản active | 409/429 có lý do; không cắt bớt âm thầm |
| DYN-10 | Symbol động trong câu hỏi Quick SQL/Research | SQLGuard, allowlist và role agent không đổi; resolver chỉ nhận `ready` |
| DYN-11 | Binance `exchangeInfo` lỗi/429 khi xác minh | Retry có backoff; hết lượt → `error` có lý do, có thể retry |
| DYN-12 | Thêm đồng mới khi Airflow chạy / không chạy | Chạy: DAG onboarding được kích hoạt ngay; không chạy: request vẫn trả `loading`, có cảnh báo, lịch dự phòng nhận việc; kích hoạt 2 lần không nạp trùng |
| DYN-13 | Danh sách chain nạp TVL | Đọc từ `defillama_chains.csv`; thêm một dòng seed → chain mới được nạp, không sửa code |
| RISK-01 | Mỗi luật Mục 4.6 trên ngày lịch sử đã tính tay | Đúng giá trị, đúng bật/tắt |
| RISK-02 | Ngưỡng biên (bằng đúng ngưỡng) | Theo định nghĩa (≥/≤) trong seed |
| RISK-03 | Không đủ quan sát (đồng mới niêm yết) | Không có tín hiệu, không giá trị bịa |
| RISK-04 | Cửa sổ không dùng dữ liệu sau ngày tín hiệu | Test so với tính lại chỉ bằng dữ liệu tới ngày đó |
| RISK-05 | Tần suất bật trên dữ liệu thật | Có bảng tần suất theo luật × đồng trong tài liệu; luật > 5% số ngày có ghi chú hiệu chỉnh |
| RISK-06 | Hiển thị tín hiệu | Câu "không phải khuyến nghị" do code thêm, có trong UI và Markdown; writer không thể bỏ |
| BRIEF-01 | Brief 4 đồng, 30 ngày | Kế hoạch đúng như Mục 5.7, 0 lần gọi planner, mọi finding grounded |
| BRIEF-02 | Một đồng `stale`/`loading` trong watchlist | Brief cho các đồng còn lại, Data status nêu rõ, `partial` |
| BRIEF-03 | Writer lỗi hoặc mọi finding bị loại | Bảng + evidence vẫn có, `partial` |
| BRIEF-04 | Vượt ngân sách brief | Dừng có lý do (đóng luôn AI-06 cho research) |
| BRIEF-05 | Markdown export | Có đủ các phần Mục 5.7, SQL từng evidence |
| BRIEF-06 | Task `generate_daily_brief` sau `dbt_build_marts` | Mỗi watchlist một dòng `CONTROL.DAILY_BRIEF`; chạy lại cùng ngày ghi đè, không thêm dòng; marts lỗi → task không chạy |
| BRIEF-07 | Brief theo lịch lỗi hoặc chạm trần chi phí | Task báo lỗi rõ; dữ liệu đã nạp không bị ảnh hưởng; trần chi phí → brief không LLM (`partial`) được lưu |
| BRIEF-08 | Airflow bắt kịp nhiều ngày bị lỡ | Chỉ tạo brief cho ngày mới nhất |
| SEC-01 | `AUTH_MODE=deployed`: không khóa / khóa sai / thiếu `FINSIGHT_SERVICE_KEY` lúc khởi động; `AUTH_MODE=local` | 401 / 401 / API không khởi động; `local`: không cần khóa, compose chỉ publish `127.0.0.1`; không lộ lý do nội bộ |
| SEC-02 | Rate limit, trần chi phí ngày (kể cả nhiều request đồng thời) | 429 + `Retry-After`/lý do; không gọi LLM khi đã vượt; giữ chỗ ngân sách nên không vượt trần quá một request; endpoint không dùng LLM vẫn chạy |
| SEC-03 | Prompt injection trong tên/ghi chú tài sản, tham số symbol có ký tự SQL | Bị từ chối ở resolver/validation, không tới SQL |
| PROD-01 | 10 request đồng thời (fake LLM/warehouse) | Không lỗi, kết nối dùng chung an toàn, mỗi response có request_id |
| PROD-02 | OpenAI 500, Snowflake mất kết nối, Binance down | 503 hoặc trạng thái `error` có lý do; không traceback ra client |
| PROD-03 | Deploy rồi rollback (máy local hoặc VM) | Smoke test sau deploy; rollback về tag trước chạy được |

### 7.4 Definition of Done

- Toàn bộ test cũ xanh; `POST /ask` tương thích ngược.
- Fixture offline cho DefiLlama (response thật đã lưu, rút gọn), FRED CPI, Binance; unit test không cần mạng.
- dbt: test grain/unique/not-null/relationships/accepted values/freshness cho mọi model mới; known answers cho TVL và CPI.
- Ít nhất 3 câu research đa nguồn chạy end-to-end trên dữ liệu thật; nếu thiếu credentials, có replay offline **ghi rõ là replay**.
- Eval trước/sau có file kết quả thật; không hardcode số liệu.
- CI chạy unit, dbt parse, DAG integrity, Docker smoke cho code mới; live test tách riêng.
- README cập nhật: nguồn mới, kiến trúc, lệnh, kết quả mới kèm CI, giới hạn (TVL retrospective, mẫu nhỏ).

Bổ sung cho Pulse (T1.5–T6.5), mỗi tính năng có tiêu chí riêng:

- **Dynamic Asset Universe:** thêm một đồng ngoài 4 core (ví dụ LINKUSDT) từ UI → `loading` → `ready` trong một lần chạy DAG
  onboarding được kích hoạt ngay; hỏi Quick SQL/Research về đồng đó được; DYN-01…13 xanh; 8 vị trí hardcode ở Mục 2.7 đã
  thay hoặc giải thích.
- **Risk signals:** seed luật + `mart_risk_signal_daily` + RISK-01…06 xanh; mỗi tín hiệu hiển thị kèm luật, ngưỡng, giá trị;
  bảng tần suất bật đã ghi.
- **Daily Brief:** BRIEF-01…08 xanh; brief 4 đồng chạy end-to-end trên dữ liệu thật ≤ 90 s và ≤ $0,02; Markdown tải được;
  brief theo lịch có trong UI ít nhất 3 ngày liên tiếp trên máy chủ sở hữu (ghi lại ngày và chi phí).
- **Production:** SEC-01…03, PROD-01…03 xanh; request_id có trong log và response; `GET /health/data` phản ánh đúng dữ liệu cũ/brief thiếu;
  deploy + rollback chạy được ít nhất một lần (local hoặc VM), có ghi lại; SQL resource monitor có trong `infra/snowflake/`.
- **Evaluation:** bộ câu cũ và chính sách holdout giữ nguyên; product evaluation có file kết quả thật (Mục 7.5) hoặc ghi rõ
  chưa chạy — không có số ước đoán.

### 7.5 Product evaluation — chứng minh giá trị của AI (T5.5)

Giữ nguyên toàn bộ evaluation ở Mục 7.1–7.4 và chính sách holdout. Bổ sung một đánh giá ở mức **sản phẩm**: cùng một bộ nhiệm
vụ, ba cách làm.

| Cách | Mô tả | Đo cái gì |
|---|---|---|
| **A. Manual research** | Người làm tự lấy số từ Binance/FRED/DefiLlama (web hoặc API), bảng tính, tự viết nhận xét | Mốc ban đầu |
| **B. Dashboard + SQL + template, không LLM** | Chính các template và bảng của brief (Mục 5.7) chạy không có writer (chế độ `partial` khi tắt LLM) | Giá trị do **Data Engineering** (dữ liệu sạch, PIT, template) |
| **C. FinSight Pulse** | Brief/Research đầy đủ có writer + grounding | Giá trị **tăng thêm của AI** so với B |

- Bộ nhiệm vụ: `eval/product_tasks.jsonl`, 6–8 nhiệm vụ viết **trước** khi đo, ví dụ "đánh giá rủi ro 30 ngày cho BTC, ETH,
  SOL, LINK, nêu bối cảnh lãi suất"; mỗi nhiệm vụ có đáp án số (tính bằng template/SQL gold) và checklist nội dung bắt buộc.
  Mỗi nhiệm vụ có **3 biến thể tương đương** (cùng loại câu hỏi, khác đồng hoặc khác kỳ), mỗi cách làm A/B/C nhận một biến thể,
  để người làm không nhớ sẵn đáp án từ lần trước.
- Người tham gia: chủ sở hữu (bắt buộc). Thêm 1 người không xây hệ thống nếu có; nếu không có, kết quả ghi rõ giới hạn: người
  làm đã quen dữ liệu và hệ thống, nên thời gian của cả ba cách đều thấp hơn với người mới, và đây không phải nghiên cứu người
  dùng. Thứ tự cách làm xoay vòng giữa các nhiệm vụ để giảm hiệu ứng học.
- Chỉ số mỗi nhiệm vụ và cách làm:

| Chỉ số | Cách tính |
|---|---|
| Task completion rate | Nhiệm vụ hoàn thành đủ checklist / tổng nhiệm vụ |
| Time to complete | Thời gian đồng hồ từ lúc nhận nhiệm vụ tới lúc nộp báo cáo; báo median và p90 |
| Numerical correctness | Số đúng (trong sai số template) / số được nêu |
| Report quality, evidence coverage | Checklist nội dung đạt / tổng; claim định lượng có nguồn hoặc SQL / tổng claim định lượng |
| Chi phí | LLM (`usage.cost_usd`) + Snowflake (credit từ `QUERY_HISTORY` theo `QUERY_TAG` × đơn giá) + hạ tầng (chi phí tháng / số nhiệm vụ ước tính trong tháng, ghi rõ giả định) |
| Failure rate, fallback | Nhiệm vụ lỗi hoặc `partial` / tổng; fallback có giữ được bảng và evidence không |

- Công thức: tiết kiệm thời gian của Pulse so với thủ công = 1 − median(T_C) / median(T_A); **giá trị Data Engineering** =
  1 − median(T_B) / median(T_A); **giá trị tăng thêm của AI** = 1 − median(T_C) / median(T_B); tương tự cho chi phí mỗi nhiệm
  vụ. Độ đúng số của B và C phải bằng nhau (cùng template); nếu C thấp hơn B, AI đang làm hỏng số → lỗi nghiêm trọng.
- Báo cáo kèm cỡ mẫu và khoảng tin cậy (Wilson cho tỉ lệ; với thời gian, nêu khoảng min–max), ghi `eval/results/product_*.json`.
  **Không tạo kết quả khi chưa đo**; README chỉ ghi số sau khi đo thật.

---

## 8. Work packages

| Task | Công việc & file dự kiến | Điều kiện hoàn tất |
|---|---|---|
| T0 | `docs/upgrade_audit.md`, `docs/upgrade_baseline.md` | Mục 2.5 T0.1–T0.3 |
| T0.5 | `requirements.txt`, sửa tương thích, eval so sánh | Mục 2.5 T0.5 |
| T1 | `src/ingestion/defillama/{client,extractor,loader,sync}.py`, `scripts/load_defillama.py`, bảng RAW, `MVP_SERIES` + CPI, task Airflow, Makefile | Fixture + unit test; idempotent; DATA-01…06 |
| T2 | dbt models/seeds/tests Mục 3.4; `semantic/metrics.yml` + `layer.py`; verified queries Mục 4.4; mô tả cột MART | `dbt build` xanh; golden cases; MET-01…06 |
| T3 | `src/agents/research/*`, router, grounding check | AI-01…06; Quick SQL regression xanh |
| T4 | `POST /research`, `ResearchResponse`, tab Streamlit, Markdown export | APP-01; test `TestClient` + `AppTest` |
| T5 | Bộ câu hỏi mới (holdout viết trước), `make eval-research`, kết quả trước/sau | Mục 7 |
| T6 | README, `docs/architecture.md`, `docs/README.vi.md`, CI runner, release notes | Mục 2.4 xử lý xong; người khác clone và chạy được |

Trạng thái T0–T6: Mục 2.6. Work packages FinSight Pulse (theo thứ tự; mỗi task là vài commit nhỏ, test trước rồi code):

| Task | Công việc & file dự kiến | Điều kiện hoàn tất |
|---|---|---|
| T1.5 Dynamic Asset Universe | `infra/snowflake/03_control_access.sql` + `04_control_tables.sql` (schema `CONTROL`, role `FINSIGHT_APP`, các bảng Mục 3.7 — chủ dự án chạy); job làm mới `CONTROL.BINANCE_SYMBOL` (client Binance hiện có + `exchangeInfo`); `sync.py` đọc danh sách nạp (core ∪ ready, fallback `MVP_SYMBOLS`); `MVP_CHAINS` đọc từ seed; DAG `finsight_asset_onboarding` (kích hoạt theo yêu cầu + lịch mỗi giờ) + pools; `make add-asset`; dbt source CONTROL, `dim_asset` mở rộng, `mart_asset_universe`; thay 8 vị trí Mục 2.7 | DYN-01…13; test DAG cập nhật; `dbt build` xanh; Mục 7.4 (Dynamic Asset Universe) |
| T2.5 Risk signals + catalog | `layer.py` (`symbol_list`, `row_key`, outputs nhiều dòng); 4 metric Mục 4.5 + golden case; seed `risk_signal_rules.csv`, `mart_risk_signal_daily`; bảng tần suất bật; resolver theo universe; verified queries Mục 4.4 (còn mở) | RISK-01…06; golden case chạy trên Snowflake; `make eval` chạy lại sau khi đổi ngữ cảnh prompt, holdout không giảm |
| T3.5 Daily Brief | `build_brief_plan`, `generate_brief`, đường đi bỏ qua planner trong graph research, ngân sách brief, sections cố định + câu "không phải khuyến nghị" trong report; `make brief`; task `generate_daily_brief` trong `finsight_daily`, `CONTROL.DAILY_BRIEF` | BRIEF-01…08; AI-06 có test; test DAG cập nhật |
| T4.5 Watchlist API/UI | Endpoint Mục 6.2 (watchlist có tên, brief đã lưu, usage), kết nối `FINSIGHT_APP` cho CONTROL, kích hoạt DAG qua Airflow REST API, tab Watchlist & Brief | Test `TestClient` + `AppTest`; APP-01 vẫn xanh; kiểm tra tay trên trình duyệt (ghi lại) |
| T5.5 Regression + product eval | Bộ câu brief (dev/holdout, viết trước khi chạy), `eval/product_tasks.jsonl` (có biến thể), script tổng hợp Mục 7.5 | Kết quả thật trong `eval/results/`; không số ước đoán |
| T6.5 Production hardening | `AUTH_MODE` + khóa dịch vụ (Mục 6.3), compose publish `127.0.0.1` khi local, rate limit toàn cục, trần chi phí ngày có giữ chỗ, SQL resource monitor, request ID, log JSON + timing node, `CONTROL.REQUEST_LOG`, `CONTROL.API_USAGE`, `GET /health/data`, image + registry, compose deploy + rollback, tài liệu vận hành; VM là tuỳ chọn | SEC-01…03, PROD-01…03; deploy + rollback chạy thật một lần (local hoặc VM) |

### 8.1 Quy tắc thực thi

1. Mỗi task: đọc module liên quan, viết giải pháp ngắn trong commit message, theo pattern hiện có (client/extractor/loader/sync,
   TableSpec, DI bằng tham số, fake trong test).
2. Mỗi task có test mới và chạy lại test cũ; commit nhỏ.
3. Test mặc định không cần mạng/credentials; live test chỉ chạy khi có `.env`.
4. Yêu cầu không khả thi hoặc API khác mô tả → ghi gap log, chọn phương án tối giản, không âm thầm bỏ yêu cầu.
5. Đổi prompt, mô tả cột hoặc semantic layer = thí nghiệm: chạy eval trước/sau.
6. Mở rộng danh sách tài sản, thêm endpoint hay thêm role không được nới SQLGuard, quyền `FINSIGHT_AGENT` hay giới hạn chi phí
   truy vấn; mọi thay đổi quyền Snowflake nằm trong file SQL để chủ dự án chạy.
7. Mỗi tính năng mới phải có tiêu chí chấp nhận, test case và điều kiện hoàn tất trong Mục 7.3/7.4 trước khi viết code.

---

## 9. Ngoài phạm vi, tài liệu, handoff

### 9.1 Ngoài phạm vi

- Đặt lệnh, tư vấn đầu tư, khuyến nghị mua bán, dự đoán giá, thanh toán, email.
- Tài khoản và nhiều người dùng (đăng ký, đăng nhập, mật khẩu, vai trò, quota theo người dùng): FinSight Pulse là sản phẩm
  **một chủ sở hữu**. Bảo vệ ở Mục 6.3 (`AUTH_MODE`, khóa dịch vụ, trần chi phí) là bảo vệ hệ thống khi deploy, không phải
  tài khoản; nó nằm trong phạm vi.
- Nạp toàn bộ tài sản Binance; nguồn giá ngoài Binance; cặp không phải USDT spot trong MVP.
- Gửi brief cho người khác (email hàng loạt, kênh công khai). Brief theo lịch chỉ lưu trong `CONTROL.DAILY_BRIEF` (Mục 5.7).
- Thông báo qua Discord/Telegram (brief và cảnh báo): hoãn sang P2.
- Thuê VM chạy thường trực khi chủ sở hữu chưa cần dùng ngoài máy mình (Mục 6.5).
- Rate limit dùng chung nhiều instance (Redis), Prometheus/Grafana, Kubernetes, microservices, Kafka, Spark, multi-agent, MCP,
  vector database: chỉ khi có lý do kỹ thuật đo được, ghi gap log trước.
- Crawl trang có điều khoản cấm; tin tức chỉ khi có giấy phép và timestamp (P2).
- Dữ liệu khách hàng/ngân hàng.
- Tăng dữ liệu lên hàng trăm triệu dòng chỉ để làm đẹp portfolio.
- Ghi vào CV điều chưa có test/benchmark chứng minh.

### 9.2 Tài liệu chính thức

- Binance Spot Market Data: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
- FRED Observations: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- FRED Real-Time Periods: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
- DefiLlama API (free): https://api-docs.defillama.com/llms-free.txt
- dbt docs blocks: https://docs.getdbt.com/reference/resource-properties/description
- LangGraph: https://langchain-ai.github.io/langgraph/
- OpenAI Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
- Snowflake Query Profile: https://docs.snowflake.com/en/user-guide/ui-query-profile
- Binance Spot General endpoints (`exchangeInfo`): https://developers.binance.com/docs/binance-spot-api-docs/rest-api/general-endpoints
- FastAPI security: https://fastapi.tiangolo.com/tutorial/security/
- Airflow pools: https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html
- Airflow REST API (kích hoạt DAG run): https://airflow.apache.org/docs/apache-airflow/stable/stable-rest-api-ref.html
- Snowflake resource monitors: https://docs.snowflake.com/en/user-guide/resource-monitors

### 9.3 Handoff

```text
AGENT FINAL REPORT:
1) Repo audit (before) và khác biệt so với Mục 2.1
2) Dependency upgrade: phiên bản trước/sau, thay đổi tương thích, kết quả A/B model
3) Files/modules changed
4) New tables, grain, data contracts; dbt tests mới
5) Implemented features with proof (test names, screenshots)
6) Test commands & exact results (exit codes)
7) Eval trước/sau: accuracy (CI), routing, metric selection, grounding, latency p50/p95, cost
8) Risks, gap log, credential blockers
9) Commands to run the app and 3 demo research questions
10) P2 follow-ups (not implemented)
11) (Pulse) Asset universe: tài sản thêm thử, trạng thái từng bước onboarding, thời gian từ lúc thêm tới ready, 8 vị trí hardcode đã thay
12) (Pulse) Risk signals: luật, known-answer đã kiểm, bảng tần suất bật trên dữ liệu thật, ngưỡng đã chỉnh (nếu có) và lý do
13) (Pulse) Daily Brief: một brief mẫu (Markdown), thời gian, chi phí, phần partial nếu có; các ngày brief theo lịch đã chạy
14) (Pulse) Product evaluation A/B/C: kết quả thật hoặc "chưa chạy" — không ước đoán; số người tham gia và giới hạn
15) (Pulse) Production: AUTH_MODE local/deployed, khóa dịch vụ, rate limit, trần chi phí ngày, request_id, cảnh báo, deploy + rollback đã chạy (local/VM), file SQL (CONTROL, FINSIGHT_APP, resource monitor) cần chủ dự án chạy
```

---

## 10. Prompt ngắn để giao việc

Đọc toàn bộ `FinSight_AI_Research_Copilot_Upgrade_Spec.md` trong workspace. Bạn nâng cấp repository hiện tại, KHÔNG tạo repo mới,
làm việc trên `main`. T0–T6 đã triển khai (Mục 2.6): bắt đầu bằng T0 audit ngắn (đối chiếu Mục 2.1, 2.6, 2.7 với code, chạy
`make ci`, `make test`, `make eval-gold`, `make eval-research --gold-only`), rồi làm FinSight Pulse theo thứ tự T1.5 → T2.5 →
T3.5 → T4.5 → T5.5 → T6.5 (Mục 8), ưu tiên P1.5 rồi P1.6. Dùng lại code có sẵn (client/extractor/loader/sync, MERGE, watermark,
dbt, catalog, research graph, grounding, report); không tạo agent mới cho Daily Brief; brief theo lịch là một task trong DAG
`finsight_daily` hiện có. Sản phẩm một chủ sở hữu: không tài khoản, không vai trò; bảo vệ bằng `AUTH_MODE`, một khóa dịch vụ
và trần chi phí ngày (Mục 6.3); cloud VM là tuỳ chọn. Giữ nguyên luồng Text-to-SQL,
`POST /ask`, `POST /research`, SQLGuard, role `FINSIGHT_AGENT` chỉ đọc MART và mọi test cũ. Tín hiệu rủi ro do luật tính, không do
LLM; không dự đoán giá, không khuyến nghị. Không bịa API, đường dẫn, metric hay số liệu benchmark (kể cả product evaluation).
Thay đổi quyền Snowflake chỉ viết thành SQL để chủ dự án chạy. Thiếu credentials thì dùng fixture/mock cho test offline và ghi
blocker. Mỗi task phải có code, dbt/migration, test và tài liệu. Không push khi chưa được đồng ý. Kết thúc bằng báo cáo handoff
Mục 9.3 (gồm mục 11–15 cho Pulse).
