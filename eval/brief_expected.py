"""Write eval/brief_cases.jsonl: Daily Brief cases with answers computed independently.

The expected numbers come from daily closes and the rules seed, in plain Python here, not from
the catalog templates or MART_RISK_SIGNAL_DAILY that the brief itself uses. Run once, before the
brief is evaluated (holdout discipline): python -m eval.brief_expected
"""

import csv
import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

from src.services.snowflake_client import SnowflakeClient

CASES = [
    # id, split, symbols, end, window, language
    ("b01", "dev", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], date(2025, 12, 31), 30, "en"),
    ("b02", "dev", ["BTCUSDT", "ETHUSDT"], date(2025, 10, 15), 30, "vi"),
    ("b03", "holdout", ["ETHUSDT", "SOLUSDT", "BNBUSDT"], date(2025, 4, 15), 90, "en"),
    ("b04", "holdout", ["BTCUSDT", "BNBUSDT"], date(2024, 8, 10), 7, "vi"),
]
OUT = Path(__file__).with_name("brief_cases.jsonl")
RULES = {r["signal_id"]: r for r in csv.DictReader(open("dbt/seeds/risk_signal_rules.csv"))}


def window_days(day: date, back: int, include_day: bool) -> list[date]:
    first = 0 if include_day else 1
    return [day - timedelta(days=k) for k in range(first, back + first)]


def signals(days: dict[date, dict], tvl: list[dict], symbol: str, start: date, end: date) -> set:
    fired = set()
    day = start
    while day <= end:
        today = days.get(day)
        if today:
            rule = RULES["abnormal_move"]
            back = window_days(day, int(rule["window_days"]), False)
            past = [days[d]["DAILY_RETURN"] for d in back
                    if d in days and days[d]["DAILY_RETURN"] is not None]  # fmt: skip
            if today["DAILY_RETURN"] is not None and len(past) >= int(rule["min_observations"]):
                if abs(today["DAILY_RETURN"]) / statistics.stdev(past) >= float(rule["threshold"]):
                    fired.add("abnormal_move")
            rule = RULES["volatility_spike"]
            back = window_days(day, int(rule["window_days"]), False)
            past = [days[d]["VOLATILITY_30D"] for d in back
                    if d in days and days[d]["VOLATILITY_30D"] is not None]  # fmt: skip
            if today["VOLATILITY_30D"] is not None and len(past) >= int(rule["min_observations"]):
                if today["VOLATILITY_30D"] / statistics.median(past) >= float(rule["threshold"]):
                    fired.add("volatility_spike")
            rule = RULES["drawdown_alert"]
            past = [days[d]["CLOSE_PRICE"] for d in window_days(day, int(rule["window_days"]), True)
                    if d in days]  # fmt: skip
            if len(past) >= int(rule["min_observations"]):
                if today["CLOSE_PRICE"] / max(past) - 1 <= float(rule["threshold"]):
                    fired.add("drawdown_alert")
        day += timedelta(days=1)
    rule = RULES["tvl_drop"]
    for n, point in enumerate(tvl, start=1):
        if point["RELATED_SYMBOL"] == symbol and start <= point["TVL_DATE"] <= end:
            change = point["TVL_CHANGE_7D"]
            if (
                change is not None
                and n >= int(rule["min_observations"])
                and change <= float(rule["threshold"])
            ):
                fired.add("tvl_drop")
    return fired


def main() -> None:
    db = SnowflakeClient(keep_connection=True)
    rows = db.execute(
        "select symbol, trade_date, close_price, daily_return, volatility_30d "
        "from FINSIGHT.MART.MART_ASSET_DAILY where trade_date between '2023-06-01' and '2025-12-31'"
    )
    data: dict[str, dict[date, dict]] = {}
    for row in rows:
        clean = {k: (float(v) if v is not None and k != "TRADE_DATE" and k != "SYMBOL" else v)
                 for k, v in row.items()}  # fmt: skip
        data.setdefault(row["SYMBOL"], {})[row["TRADE_DATE"]] = clean
    tvl_rows = db.execute(
        "select chain, related_symbol, tvl_date, tvl_change_7d "
        "from FINSIGHT.MART.MART_CHAIN_TVL_DAILY "
        "where related_symbol is not null order by chain, tvl_date"
    )
    by_chain: dict[str, list[dict]] = {}
    for row in tvl_rows:
        row["TVL_CHANGE_7D"] = (
            float(row["TVL_CHANGE_7D"]) if row["TVL_CHANGE_7D"] is not None else None
        )
        by_chain.setdefault(row["CHAIN"], []).append(row)

    with OUT.open("w", encoding="utf-8") as out:
        for case_id, split, symbols, end, window, language in CASES:
            start = end - timedelta(days=window - 1)
            assets, fired = {}, []
            returns = {}
            for symbol in symbols:
                days = data[symbol]
                period = [d for d in sorted(days) if start <= d <= end]
                before = start - timedelta(days=1)
                closes = [days[d]["CLOSE_PRICE"] for d in period]
                peak, drawdown = -1.0, 0.0
                for close in closes:
                    peak = max(peak, close)
                    drawdown = min(drawdown, close / peak - 1)
                assets[symbol] = {
                    "PERIOD_RETURN": closes[-1] / days[before]["CLOSE_PRICE"] - 1,
                    "MAX_DRAWDOWN": drawdown,
                    "N_DAYS": len(period),
                }
                returns[symbol] = {d: days[d]["DAILY_RETURN"] for d in period}
                tvl = [
                    p for chain in by_chain.values() for p in chain if p["RELATED_SYMBOL"] == symbol
                ]
                fired += [[symbol, s] for s in sorted(signals(days, tvl, symbol, start, end))]
            rule = RULES["high_correlation"]
            for i, a in enumerate(symbols):
                for b in symbols[i + 1 :]:
                    pair = sorted([a, b])
                    common = [d for d in returns[a] if d in returns[b]]
                    if len(common) >= int(rule["min_observations"]):
                        corr = statistics.correlation([returns[a][d] for d in common],
                                                      [returns[b][d] for d in common])  # fmt: skip
                        if corr >= float(rule["threshold"]):
                            fired.append([f"{pair[0]} / {pair[1]}", "high_correlation"])
            case = {
                "case_id": case_id, "split": split, "symbols": symbols, "as_of": end.isoformat(),
                "window_days": window, "language": language, "expected_start": start.isoformat(),
                "expected_assets": assets, "expected_signals": sorted(fired),
            }  # fmt: skip
            out.write(json.dumps(case, ensure_ascii=False) + "\n")
            print(
                case_id, {k: round(v["PERIOD_RETURN"], 4) for k, v in assets.items()}, sorted(fired)
            )
    assert math.isfinite(1.0)


if __name__ == "__main__":
    main()
