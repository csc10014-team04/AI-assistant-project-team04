"""P2-1 evaluation: run the labelled prompts through understand_prompt and report adherence / accuracy.

usage (live vLLM):  python tools/eval_nlu.py            # target: schema adherence >= 98%, 0 temporal hallucinations
       (rules only): python tools/eval_nlu.py --rules   # deterministic fallback quality, no model needed
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if "LLM_TIMEOUT_SECONDS" not in os.environ and "--rules" not in sys.argv:
    os.environ["LLM_TIMEOUT_SECONDS"] = "20.0"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import VN_TZ  # noqa: E402
from services import nlu  # noqa: E402
from services.normalizer import normalize_text  # noqa: E402

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=VN_TZ)  # fixed Monday so expected windows are reproducible
DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "nlu_eval.jsonl"


def evaluate(rules_only: bool = False) -> dict[str, int | float]:
    cases = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts: dict[str, int] = {
        "n": len(cases),
        "llm_ok": 0,
        "fallback": 0,
        "intent_ok": 0,
        "duration_ok": 0,
        "hint_ok": 0,
        "bad_dates": 0,
    }
    for c in cases:
        if rules_only:
            r = nlu.rule_based_understand(normalize_text(c["prompt"]).text)
        else:
            r = nlu.understand_prompt(c["prompt"], NOW)
        counts["fallback" if r.fallback_mode else "llm_ok"] += 1
        counts["intent_ok"] += int(r.intent == c["intent"])
        counts["duration_ok"] += int(r.duration_minutes == c["duration_minutes"])
        counts["hint_ok"] += int((r.date_hint or None) == c["date_hint"])
        if r.date_hint and r.date_hint.lower() not in normalize_text(c["prompt"]).text.lower():
            counts["bad_dates"] += 1  # a date phrase that is not in the prompt = temporal hallucination
    stats: dict[str, int | float] = dict(counts)
    stats["schema_adherence_pct"] = round(100 * counts["llm_ok"] / counts["n"], 1)
    for k in ("intent_ok", "duration_ok", "hint_ok"):
        stats[k.replace("_ok", "_acc_pct")] = round(100 * counts[k] / counts["n"], 1)
    return stats


if __name__ == "__main__":
    print(json.dumps(evaluate("--rules" in sys.argv), indent=2))
