"""Benchmark Quick SQL as a conversation (eval/chat_conversations.jsonl, written before any run).

Every turn of a conversation runs for real: the agent answers, the rewriter turns follow-ups into
standalone questions. Only the LAST turn is graded: its kind (answer, smalltalk, declined) and,
for an answer, its result against the gold SQL (src/evaluation/compare.py, as `make eval`).

    python -m eval.run_chat_eval              # ~$0.002 per turn
    python -m eval.run_chat_eval --gold-only  # every gold SQL still runs: $0
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from eval.run_eval import RESULTS_DIR, wilson_interval
from src.agents.chat import Turn, chat, to_turn
from src.agents.text_to_sql import agent_warehouse
from src.common.config import get_settings
from src.common.logging_config import setup_logging
from src.evaluation.compare import results_match

CONVERSATIONS = Path(__file__).with_name("chat_conversations.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-only", action="store_true")
    args = parser.parse_args(argv)
    setup_logging(get_settings().log_level)
    cases = [json.loads(line) for line in CONVERSATIONS.read_text(encoding="utf-8").splitlines()]
    warehouse = agent_warehouse()

    if args.gold_only:
        for case in cases:
            if case.get("expected_sql"):
                rows = warehouse.execute(case["expected_sql"])
                print(case["conversation_id"], rows[:2])
        return 0

    results, cost = [], 0.0
    for case in cases:
        history: list[Turn] = []
        reply = None
        for message in case["turns"]:
            reply = chat(message, history)
            history.append(Turn(**to_turn(reply)))
            cost += reply.usage.cost_usd + (reply.answer.usage.cost_usd if reply.answer else 0)
        passed = reply.kind == case["expected_kind"]
        detail = f"kind={reply.kind}"
        if passed and reply.kind == "answer":
            gold = warehouse.execute(case["expected_sql"])
            match = results_match(gold, reply.answer.rows)
            passed, detail = match.matched, match.reason
        results.append({"conversation_id": case["conversation_id"], "split": case["split"],
                        "passed": passed, "detail": detail, "kind": reply.kind,
                        "understood_as": reply.standalone or reply.message,
                        "sql": reply.answer.sql if reply.answer else None})  # fmt: skip
        verdict = "pass" if passed else "FAIL"
        print(f"{case['conversation_id']} {case['split']:7} {verdict}  {detail}")
        print(f"    last turn understood as: {reply.standalone or reply.message!r}")

    report = {"run_at": datetime.now(UTC).isoformat(), "model": get_settings().llm_model,
              "cost_usd": cost, "results": results}  # fmt: skip
    for split in ("dev", "holdout"):
        part = [r for r in results if r["split"] == split]
        passed = sum(r["passed"] for r in part)
        low, high = wilson_interval(passed, len(part))
        report[split] = {"passed": passed, "total": len(part), "ci95": [low, high]}
        print(f"{split}: {passed}/{len(part)} [{low:.0%}-{high:.0%}]")
    print(f"cost ${cost:.4f}")
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"chat_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Report: {path}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
