"""Ask the model to state the findings of the evidence, and add the caveats code can know.

The writer receives numbers already computed by verified SQL, with fractions also given as
percents, so it never has to do arithmetic. Its output is checked by grounding.py afterwards.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

from src.agents.sql_generation import PROMPTS_DIR
from src.semantic.retriever import normalize
from src.services.llm import LLMClient, LLMUsage

PERCENT_UNITS = {"fraction", "fraction_per_year"}

WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["findings", "caveats"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Written:
    findings: list[dict[str, Any]]
    caveats: list[str]
    usage: LLMUsage
    seconds: float


@lru_cache
def writer_prompt() -> str:
    return (PROMPTS_DIR / "research_writer.md").read_text(encoding="utf-8")


def for_writer(item: dict[str, Any]) -> dict[str, Any]:
    """The evidence as the writer sees it: rounded values, fractions also as percents."""

    values = []
    for output in item["values"]:
        value = output["value"]
        shown: dict[str, Any] = {
            "name": output["column"].lower(),
            "meaning": output["description"],
            "unit": output["unit"],
        }
        if value is None or isinstance(value, str):
            shown["value"] = value
        else:
            shown["value"] = float(f"{value:.6g}")
        if isinstance(value, float) and output["unit"] in PERCENT_UNITS:
            shown["as_percent"] = f"{value * 100:.2f}%"
        values.append(shown)
    return {
        "id": item["id"],
        "metric": item["metric_name"],
        "metric_definition": " ".join(item.get("definition", "").split()),
        "params": item["params"],
        "n": item["n"],
        "values": values,
    }


# Letters only Vietnamese uses; a question without accents gets the English caveats.
VIETNAMESE = re.compile(r"[ăâđêôơưàảãạáằẳẵặắầẩẫậấèẻẽẹéềểễệếìỉĩịíòỏõọóồổỗộốờởỡợớùủũụúừửữựứỳỷỹỵý]")

CAVEATS = {
    "en": {
        "as_of": "Data up to {day} (UTC); today is not included.",
        "retrospective": "DeFi TVL history is DefiLlama's current (retrospective) view of past "
        "days, not what was known at the time; DefiLlama may still revise it.",
        "correlation": "Correlation describes co-movement, not cause.",
        "events": "{n} yield-move event(s): returns over overlapping windows are not independent, "
        "so a few events are weak evidence.",
        "small": "Small sample for {metric} (n={n}).",
        "stale_macro": "The newest 10-year yield describes {source}, {days} days before the end of "
        "the period: FRED published nothing newer, so the last value was carried forward.",
    },
    "vi": {
        "as_of": "Dữ liệu đến hết ngày {day} (UTC); không gồm ngày hôm nay.",
        "retrospective": "Lịch sử TVL DeFi là số liệu DefiLlama hiện tính lại cho các ngày cũ, "
        "không phải con số đã biết vào lúc đó; DefiLlama vẫn có thể sửa.",
        "correlation": "Tương quan chỉ mô tả hai chuỗi cùng biến động, không chứng minh "
        "nguyên nhân.",
        "events": "Chỉ có {n} sự kiện biến động lợi suất; lợi nhuận đo trên các cửa sổ chồng lên "
        "nhau không độc lập, nên đây là bằng chứng yếu.",
        "small": "Mẫu nhỏ cho {metric} (n={n}).",
        "stale_macro": "Lợi suất 10 năm mới nhất là số liệu của ngày {source}, cách cuối kỳ {days} "
        "ngày: FRED chưa công bố số mới hơn nên giá trị cũ được giữ nguyên.",
    },
}


def language_of(question: str) -> str:
    return "vi" if VIETNAMESE.search(question.lower()) else "en"


def automatic_caveats(
    evidence: list[dict[str, Any]], data_as_of: date | None, language: str = "en"
) -> list[str]:
    """Limits that follow from the evidence itself; shown whatever the writer says."""

    text = CAVEATS[language]
    caveats = []
    if data_as_of:
        caveats.append(text["as_of"].format(day=data_as_of.isoformat()))
    if any(item["pit_mode"] == "retrospective" for item in evidence):
        caveats.append(text["retrospective"])
    if any("correlation" in item["metric_id"] for item in evidence):
        caveats.append(text["correlation"])
    for item in evidence:
        if item["metric_id"] == "forward_return_after_yield_move":
            caveats.append(text["events"].format(n=item["n"]))
        elif item["n"] is not None and item["n"] < 30:
            caveats.append(text["small"].format(metric=item["metric_name"], n=item["n"]))
        stale = stale_days(item)
        if stale is not None:
            values = {v["column"]: v["value"] for v in item["values"]}
            source = values["TREASURY_10Y_END_SOURCE_DATE"]
            caveats.append(text["stale_macro"].format(source=source, days=stale))
    return list(dict.fromkeys(caveats))


# More than a long weekend plus a holiday without a new 10-year yield means FRED stopped publishing.
STALE_MACRO_DAYS = 5


def stale_days(item: dict[str, Any]) -> int | None:
    """Days the last 10-year yield of the evidence is older than its period end, if too many."""

    values = {v["column"]: v["value"] for v in item["values"]}
    source = values.get("TREASURY_10Y_END_SOURCE_DATE")
    end = item["params"].get("end_date")
    if not source or not end:
        return None
    days = (date.fromisoformat(end) - date.fromisoformat(source)).days
    return days if days > STALE_MACRO_DAYS else None


def new_caveats(written: list[str], shown: list[str]) -> list[str]:
    """The writer's caveats that do not repeat one already shown (same words, any language)."""

    def words(text: str) -> set[str]:
        return set(normalize(text).split())

    kept = []
    for caveat in written:
        mine = words(caveat)
        repeats = any(
            len(mine & words(other)) >= 0.5 * min(len(mine), len(words(other))) for other in shown
        )
        if not repeats:
            kept.append(caveat)
    return kept


def build_writer_message(
    question: str,
    evidence: list[dict[str, Any]],
    shown_caveats: list[str],
    rejected_numbers: list[str] | None = None,
) -> str:
    body = json.dumps([for_writer(item) for item in evidence], ensure_ascii=False, indent=1)
    message = (
        f"# Question\n{question}\n\n"
        f"# Evidence\n{body}\n\n"
        "# Caveats already shown\n" + "\n".join(f"- {c}" for c in shown_caveats)
    )
    if rejected_numbers:
        message += (
            "\n\n# Your previous findings were rejected\nThese numbers are not in the evidence: "
            + ", ".join(rejected_numbers)
            + ". Write the findings again using only numbers from the evidence."
        )
    return message


def write_findings(
    question: str,
    evidence: list[dict[str, Any]],
    shown_caveats: list[str],
    llm: LLMClient,
    rejected_numbers: list[str] | None = None,
) -> Written:
    result = llm.generate_json(
        system_prompt=writer_prompt(),
        user_prompt=build_writer_message(question, evidence, shown_caveats, rejected_numbers),
        schema_name="research_findings",
        json_schema=WRITER_SCHEMA,
        max_output_tokens=900,
    )
    findings = [
        {"claim": f["claim"].strip(), "evidence_ids": list(f["evidence_ids"])}
        for f in result.data["findings"]
        if f["claim"].strip()
    ]
    caveats = [c.strip() for c in result.data["caveats"] if c.strip()]
    return Written(findings, caveats, result.usage, result.seconds)
