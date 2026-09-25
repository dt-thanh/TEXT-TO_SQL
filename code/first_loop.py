"""
first_loop.py — Vòng lõi tối giản của dự án.
Chứng minh: câu hỏi tiếng Việt -> LLM sinh SQL -> chạy trên Snowflake -> in kết quả.

KHÔNG cần FastAPI, KHÔNG cần LangGraph. Chỉ chạy: python first_loop.py

Chuẩn bị:
  1) pip install snowflake-connector-python openai python-dotenv
  2) Tạo file .env cùng thư mục với nội dung:
        # Định danh account, xem trong URL Snowflake (dạng org-account hoặc abc123.region)
        SNOWFLAKE_ACCOUNT=xxxxx
        SNOWFLAKE_USER=ten_dang_nhap
        SNOWFLAKE_PASSWORD=mat_khau
        SNOWFLAKE_WAREHOUSE=WH_XS
        OPENAI_API_KEY=sk-...
"""

import os

import snowflake.connector
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # đọc các biến trong file .env vào môi trường

# ---------------------------------------------------------------------------
# 1) MÔ TẢ SCHEMA — "dạy" cho LLM biết database có bảng/cột gì.
#    LLM KHÔNG tự biết dữ liệu của bạn, nên phải đưa schema vào prompt.
#    Ở đây dùng dữ liệu mẫu TPC-H có sẵn trong MỌI tài khoản Snowflake.
# ---------------------------------------------------------------------------
SCHEMA = """
Các bảng (đang ở database SNOWFLAKE_SAMPLE_DATA, schema TPCH_SF1 — dùng tên bảng trần):
- CUSTOMER(C_CUSTKEY, C_NAME, C_ACCTBAL, C_NATIONKEY, C_MKTSEGMENT)
- ORDERS(O_ORDERKEY, O_CUSTKEY, O_TOTALPRICE, O_ORDERDATE, O_ORDERSTATUS)
- NATION(N_NATIONKEY, N_NAME, N_REGIONKEY)
Quan hệ:
- ORDERS.O_CUSTKEY = CUSTOMER.C_CUSTKEY
- CUSTOMER.C_NATIONKEY = NATION.N_NATIONKEY
"""

# ---------------------------------------------------------------------------
# 2) CÂU HỎI — tạm hardcode một câu để test. Sau này thay bằng input người dùng.
# ---------------------------------------------------------------------------
QUESTION = "Top 5 khách hàng có tổng giá trị đơn hàng cao nhất, kèm tên khách"

# ---------------------------------------------------------------------------
# 3) GỌI LLM SINH SQL
# ---------------------------------------------------------------------------
client = OpenAI()  # tự đọc OPENAI_API_KEY từ môi trường

prompt = f"""Bạn là chuyên gia viết Snowflake SQL.
Dựa vào schema dưới đây, viết MỘT câu SQL (chỉ SELECT) trả lời câu hỏi.
Chỉ trả về câu SQL, không giải thích, không markdown.

{SCHEMA}

Câu hỏi: {QUESTION}
SQL:"""

resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}],
    temperature=0,  # 0 = ổn định, ít ngẫu nhiên -> hợp cho sinh SQL
)

sql = resp.choices[0].message.content.strip()
# LLM đôi khi bọc SQL trong ```sql ... ``` -> gỡ bỏ cho sạch
sql = sql.replace("```sql", "").replace("```", "").strip()

print("=== SQL do LLM sinh ra ===")
print(sql)

# ---------------------------------------------------------------------------
# 4) CHẠY SQL TRÊN SNOWFLAKE & IN KẾT QUẢ
# ---------------------------------------------------------------------------
conn = snowflake.connector.connect(
    account=os.environ["SNOWFLAKE_ACCOUNT"],
    user=os.environ["SNOWFLAKE_USER"],
    password=os.environ["SNOWFLAKE_PASSWORD"],
    warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
    database="SNOWFLAKE_SAMPLE_DATA",  # trỏ sẵn vào dữ liệu mẫu
    schema="TPCH_SF1",
    # role=... : lần đầu cứ để trống -> dùng role mặc định cho đỡ vướng quyền
)

cur = conn.cursor()
cur.execute(sql)
rows = cur.fetchall()
cols = [c[0] for c in cur.description]

print("\n=== Kết quả ===")
print(" | ".join(cols))
for r in rows:
    print(r)

cur.close()
conn.close()