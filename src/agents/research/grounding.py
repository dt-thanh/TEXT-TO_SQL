"""Check that every number in a research finding comes from the evidence it cites.

The writer (an LLM) phrases findings; it must not compute or invent numbers. This check is plain
code, not a second LLM: it reads every number in a claim and accepts it only if it matches a value
of a cited evidence item (after unit conversion and the rounding the claim shows), a sample size,
a parameter of the analysis, or a number the question itself contains (e.g. "10 bps", "2025").

    "ETH rose 4.5% (n=239)"  with evidence 0.04483 (fraction) and n 239  → grounded
    "ETH rose 7.1%"          with evidence 0.04483                       → not grounded
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# "4.5%", "-10", "28,456,740,243", "1.2 billion", "53,7 %", "+12 bps", "28,5 tỷ"
NUMBER = re.compile(
    r"(?<![\w.,])([+\-−]?\d(?:[\d.,]*\d)?)\s*"
    r"(%|bps|basis points?|b\b|bn\b|billion|tỷ|m\b|million|triệu|k\b|thousand|nghìn)?",
    re.IGNORECASE,
)
SCALES = {
    "b": 1e9, "bn": 1e9, "billion": 1e9, "tỷ": 1e9,
    "m": 1e6, "million": 1e6, "triệu": 1e6,
    "k": 1e3, "thousand": 1e3, "nghìn": 1e3,
}  # fmt: skip
# A claim may round; it may not be off by more than this share of the value.
RELATIVE_TOLERANCE = 0.005


@dataclass(frozen=True)
class Mention:
    """One number as written in a claim."""

    text: str
    value: float  # with its scale applied: "1.2 billion" → 1.2e9
    decimals: int  # digits after the decimal point, i.e. how much the writer rounded
    scale: float  # 1e9 for "billion"/"B"/"tỷ", 1 when there is no word
    is_percent: bool


def normalize_number(raw: str) -> str:
    """Plain "1234.5" from English or Vietnamese writing.

    Groups of exactly three digits after a separator are thousands ("28,456,740,243",
    "28.456.740.243"); otherwise the separator is the decimal point ("53.7", "53,7").
    """

    groups = re.split(r"[.,]", raw)
    separators = re.findall(r"[.,]", raw)
    if not separators:
        return raw
    if len(set(separators)) == 2:  # "1,234.5" or "1.234,5": the last one is the decimal point
        last = raw.rfind(separators[-1])
        return re.sub(r"[.,]", "", raw[:last]) + "." + raw[last + 1 :]
    if len(separators) > 1 or (len(groups[-1]) == 3 and separators[0] == ","):
        return "".join(groups)  # thousands separators only
    return groups[0] + "." + groups[1]


def mentions(text: str) -> list[Mention]:
    found = []
    for match in NUMBER.finditer(text):
        raw, suffix = match.group(1), (match.group(2) or "").lower()
        digits = normalize_number(raw.replace("−", "-"))
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = SCALES.get(suffix, 1.0)
        value = float(digits) * scale
        found.append(Mention(match.group(0).strip(), value, decimals, scale, suffix == "%"))
    return found


def close_to(mention: Mention, value: float, scale: float = 1.0) -> bool:
    """Does the written number equal `value` as rounded in the text (or within 0.5%)?"""

    shown = value * scale
    half_step = 0.5 * 10 ** (-mention.decimals) * mention.scale
    tolerance = max(half_step, RELATIVE_TOLERANCE * abs(shown)) + 1e-12
    return abs(abs(mention.value) - abs(shown)) <= tolerance


FRACTION_UNITS = {"fraction", "fraction_per_year", "ratio"}


def percent_scale(mention: Mention, unit: str) -> float | None:
    """How a written number may relate to a result of this unit, or None if it cannot.

    A percent is a fraction × 100 (0.045 → 4.5%) or a value already in percent (yields). It is
    never a count, an amount or basis points: "-41 bps" written as "41%" is a different claim.
    """

    if not mention.is_percent:
        return 1.0
    if unit in FRACTION_UNITS:
        return 100.0
    return 1.0 if unit == "percent" else None


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return float(value)
    return None


def allowed_numbers(question: str, evidence: list[dict[str, Any]]) -> list[float]:
    """Numbers a claim may repeat without them being results: from the question and parameters."""

    numbers = [m.value for m in mentions(question)]
    for item in evidence:
        texts = [str(value) for value in item.get("params", {}).values()]
        # Dates among the results (e.g. the day the last yield describes) may be quoted too.
        outputs = [*item.get("values", [])]
        for row in item.get("rows", []):
            outputs += row["values"]
            texts += list(row["key"].values())  # symbols such as 1INCHUSDT carry digits
        texts += [v["value"] for v in outputs if isinstance(v.get("value"), str)]
        for text in texts:
            numbers += [m.value for m in mentions(text)]
    return numbers


def ungrounded(
    claim: str, cited: list[dict[str, Any]], question: str, all_evidence: list[dict[str, Any]]
) -> list[str]:
    """The numbers of `claim` that no cited evidence (or the question) accounts for."""

    results: list[tuple[float, str]] = []
    for item in cited:
        outputs = [*item.get("values", [])]
        for row in item.get("rows", []):
            outputs += row["values"]
            if as_float(row.get("n")) is not None:
                results.append((float(row["n"]), "count"))
        for output in outputs:
            number = as_float(output.get("value"))
            if number is not None:
                results.append((number, output.get("unit", "")))
        if as_float(item.get("n")) is not None:
            results.append((float(item["n"]), "count"))
    free = allowed_numbers(question, all_evidence)

    bad = []
    for mention in mentions(claim):
        matches_result = any(
            close_to(mention, number, scale)
            for number, unit in results
            if (scale := percent_scale(mention, unit)) is not None
        )
        matches_free = any(abs(mention.value - number) < 1e-9 for number in free)
        if not (matches_result or matches_free):
            bad.append(mention.text)
    return bad
