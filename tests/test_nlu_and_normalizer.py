"""
NLU-01..NLU-32: NLU pipeline and normalizer tests.
Covers: normalize_text, profanity, teencode, diacritics, resolve_date_hint,
        TEENCODE dict, RESTORE_PHRASES dict, NluResult schema validation.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

from database import VN_TZ
from services.normalizer import PROFANITY, RESTORE_PHRASES, TEENCODE, normalize_text
from services.temporal import resolve_date_hint
from services.nlu import NluResult
from test_ai_layer import llm, reply, understand


NOW_VN = datetime(2026, 9, 7, 10, 0, tzinfo=VN_TZ)


# ---- NLU-01: normalize_text removes profanity -----------------------------
@pytest.mark.parametrize("word", list(PROFANITY)[:5])
def test_NLU01_profanity_removed_from_text(word):
    """Contract: normalize_text removes profanity words from output."""
    result = normalize_text(f"xếp lịch {word} học")
    assert word not in result.text
    assert result.profanity_found is True


# ---- NLU-02: profanity_found is False when no profanity -------------------
def test_NLU02_no_profanity_flag_when_clean():
    """Contract: profanity_found is False when input has no profanity."""
    result = normalize_text("xếp 2 tiếng học bài ngày mai")
    assert result.profanity_found is False


# ---- NLU-03: Teencode ko -> không ------------------------------------------
@pytest.mark.parametrize("teencode,canonical", [
    ("ko", "không"), ("dc", "được"), ("vs", "với"),
    ("hnay", "hôm nay"), ("cn", "chủ nhật"),
    ("t2", "thứ 2"), ("t7", "thứ 7"),
])
def test_NLU03_teencode_expansion(teencode, canonical):
    """Contract: TEENCODE words are expanded to canonical Vietnamese."""
    result = normalize_text(f"xếp {teencode} lịch")
    assert canonical in result.text


# ---- NLU-04: RESTORE_PHRASES applies diacritics ---------------------------
@pytest.mark.parametrize("raw,canonical", [
    ("tieng", "tiếng"),
    ("lich", "lịch"),
    ("ngay mai", "ngày mai"),
    ("tuan nay", "tuần này"),
    ("buoi toi", "buổi tối"),
])
def test_NLU04_restore_phrases_add_diacritics(raw, canonical):
    """Contract: RESTORE_PHRASES correctly restores diacritics."""
    result = normalize_text(f"xep {raw} hoc")
    assert canonical in result.text


# ---- NLU-05: Emoji are stripped -------------------------------------------
def test_NLU05_emoji_stripped_from_text():
    """Contract: emoji characters are removed from normalized text."""
    result = normalize_text("xếp lịch 😀😀 ngày mai")
    assert "😀" not in result.text


# ---- NLU-06: Control characters are stripped -------------------------------
def test_NLU06_control_chars_stripped():
    """Contract: null bytes and control chars are removed."""
    result = normalize_text("xếp\x00lịch\x1b học")
    assert "\x00" not in result.text
    assert "\x1b" not in result.text


# ---- NLU-07: HTML/script tags are stripped ---------------------------------
def test_NLU07_html_tags_stripped():
    """Contract: HTML markup is stripped from normalized text."""
    result = normalize_text("xếp lịch học <script>alert(1)</script>")
    assert "<script>" not in result.text


# ---- NLU-08: Multiple spaces collapsed ------------------------------------
def test_NLU08_multiple_spaces_collapsed():
    """Contract: consecutive whitespace is collapsed to a single space."""
    result = normalize_text("xếp   2   tiếng   học")
    assert "  " not in result.text


# ---- NLU-09: NFC normalization applied ------------------------------------
def test_NLU09_nfc_normalization():
    """Contract: output is in NFC Unicode normalization form."""
    import unicodedata
    raw = unicodedata.normalize("NFD", "tiếng Việt")
    result = normalize_text(raw)
    assert unicodedata.is_normalized("NFC", result.text)


# ---- NLU-10: Repeated chars compressed (3+ -> 2) --------------------------
def test_NLU10_repeated_chars_compressed():
    """Contract: 3+ consecutive identical chars are compressed to 2."""
    result = normalize_text("xếppppp lịch")
    assert "ppp" not in result.text


# ---- NLU-11: Original text is preserved in NormalizedText -----------------
def test_NLU11_original_preserved():
    """Contract: NormalizedText.original holds the unmodified input."""
    raw = "xep 2 tieng hoc bai"
    result = normalize_text(raw)
    assert result.original == raw


# ---- NLU-12: normalize_text never raises ----------------------------------
@pytest.mark.parametrize("raw", [
    "", "   ", None, "xếp lịch", "123", "!@#$%^&*()", "\n\t\r",
])
def test_NLU12_normalize_text_never_raises(raw):
    """Contract: normalize_text(raw) must not raise for any string input."""
    try:
        normalize_text(raw or "")
    except Exception as e:
        pytest.fail(f"normalize_text raised {type(e).__name__}: {e}")


# ---- NLU-13: NluResult duration validator clamps 15-720 ------------------
@pytest.mark.parametrize("raw,expected", [
    (60, 60),
    (14, None),   # < 15 -> rejected
    (721, None),  # > 720 -> rejected
    (15, 15),
    (720, 720),
    (None, None),
])
def test_NLU13_nlu_result_duration_validator(raw, expected):
    """Contract: NluResult._validate_duration returns None outside [15, 720]."""
    result = NluResult(intent="schedule_task", duration_minutes=raw)
    assert result.duration_minutes == expected


# ---- NLU-14: NluResult priority validator clamps 1-3 ---------------------
@pytest.mark.parametrize("raw,expected", [
    (1, 1), (2, 2), (3, 3),
    (0, None), (4, None), (-1, None), (None, None),
])
def test_NLU14_nlu_result_priority_validator(raw, expected):
    """Contract: NluResult._validate_priority returns None outside [1, 3]."""
    result = NluResult(intent="schedule_task", priority=raw)
    assert result.priority == expected


# ---- NLU-15: Intent fallback to 'unknown' ---------------------------------
def test_NLU15_unknown_intent_default():
    """Contract: NluResult defaults intent to 'unknown' when not specified."""
    result = NluResult()
    assert result.intent == "unknown"


# ---- NLU-16: fallback_mode default is False --------------------------------
def test_NLU16_fallback_mode_default_false():
    """Contract: NluResult.fallback_mode defaults to False."""
    result = NluResult(intent="schedule_task")
    assert result.fallback_mode is False


# ---- NLU-17: Vague date sets needs_clarification via API ------------------
def test_NLU17_vague_date_needs_clarification_via_api(client, alice):
    """Contract: vague date in prompt triggers needs_clarification=True in NLU response."""
    res = understand(client, alice, "xếp 2 tiếng học sớm")
    assert res.status_code == 200
    n = res.json()["nlu"]
    assert n["needs_clarification"] is True


# ---- NLU-18: Missing duration triggers clarification ----------------------
def test_NLU18_missing_duration_needs_clarification(client, alice):
    """Contract: prompt without duration triggers needs_clarification=True."""
    n = understand(client, alice, "xếp lịch học bài ngày mai").json()["nlu"]
    assert n["needs_clarification"] is True


# ---- NLU-19: AI fallback gives duration from prompt text ------------------
def test_NLU19_fallback_extracts_duration_from_text(client, alice):
    """Contract: when AI is down, fallback rule extracts duration from '3 tiếng'."""
    res = understand(client, alice, "xếp 3 tiếng làm đồ án ngày mai")
    assert res.status_code == 200
    n = res.json()["nlu"]
    assert n["fallback_mode"] is True
    assert n["duration_minutes"] == 180


# ---- NLU-20: Fallback source is 'rules' ------------------------------------
def test_NLU20_fallback_source_is_rules(client, alice):
    """Contract: when AI is down, NLU source is 'rules' not 'llm'."""
    n = understand(client, alice, "xếp 2 tiếng học").json()["nlu"]
    assert n["source"] == "rules"


# ---- NLU-21: AI schema validation failure falls back ----------------------
def test_NLU21_bad_ai_json_falls_back(client, alice, monkeypatch):
    """Contract: when AI returns invalid JSON, NLU falls back gracefully."""
    seen = llm(monkeypatch, lambda r: reply("Not JSON at all!"))
    n = understand(client, alice, "xếp 2 tiếng học bài").json()["nlu"]
    assert n["fallback_mode"] is True
    assert len(seen) == 2  # one retry (MAX_SCHEMA_RETRIES=1)


# ---- NLU-22: AI returns LLM source on success ----------------------------
def test_NLU22_llm_source_on_success(client, alice, monkeypatch):
    """Contract: when AI succeeds, NLU source is 'llm'."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
    }))
    n = understand(client, alice, "xếp 1 tiếng study").json()["nlu"]
    assert n["source"] == "llm"
    assert n["fallback_mode"] is False


# ---- NLU-23: Date hint from LLM is validated against prompt ---------------
def test_NLU23_llm_date_not_in_prompt_is_discarded(client, alice, monkeypatch):
    """Contract: LLM-invented date_hint not in prompt text is set to None."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
        "date_hint": "ngày 25 tháng 12",  # not in the prompt
    }))
    n = understand(client, alice, "xếp 1 tiếng study").json()["nlu"]
    assert n["date_hint"] is None
    assert n["date_assumed"] is True


# ---- NLU-24: duration from text overrides LLM if they differ (overestimate) -
def test_NLU24_text_duration_overrides_llm_hallucination(client, alice, monkeypatch):
    """Contract: when LLM hallucinated lower duration, text-extracted value is used."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 30,  # LLM says 30 but text says 2 tiếng = 120
    }))
    n = understand(client, alice, "xếp 2 tiếng study").json()["nlu"]
    assert n["duration_minutes"] == 120


# ---- NLU-25: Profanity in API prompt flags profanity_found ----------------
def test_NLU25_profanity_flagged_in_api_response(client, alice):
    """Contract: prompt with vcl/vl sets profanity_found=True in API NLU response."""
    n = understand(client, alice, "xếp 2 tiếng học vcl").json()["nlu"]
    assert n["profanity_found"] is True


# ---- NLU-26: normalize_text changes list records applied changes ----------
def test_NLU26_changes_list_records_modifications():
    """Contract: NormalizedText.changes lists what was modified."""
    result = normalize_text("ko bik dc")
    assert len(result.changes) > 0  # at least teencode changes recorded


# ---- NLU-27: TEENCODE dict is non-empty and all lowercase ----------------
def test_NLU27_teencode_dict_all_lowercase():
    """Contract: all TEENCODE keys are lowercase strings."""
    for k in TEENCODE:
        assert k == k.lower(), f"TEENCODE key '{k}' is not lowercase"


# ---- NLU-28: RESTORE_PHRASES dict values have diacritics -----------------
def test_NLU28_restore_phrases_values_have_diacritics():
    """Contract: RESTORE_PHRASES values are non-trivially Vietnamese with diacritics."""
    # At least some values must contain diacritics (non-ASCII)
    any_diacritics = any(not v.isascii() for v in RESTORE_PHRASES.values())
    assert any_diacritics


# ---- NLU-29: resolve_date_hint "thứ hai" -> Monday ------------------------
def test_NLU29_resolve_weekday_thu_hai():
    """Contract: 'thứ hai' resolves to a Monday."""
    result = resolve_date_hint("thứ hai", NOW_VN)
    # Monday is weekday 0
    assert result.start.weekday() == 0


# ---- NLU-30: resolve_date_hint "thứ bảy" -> Saturday ---------------------
def test_NLU30_resolve_weekday_thu_bay():
    """Contract: 'thứ bảy' resolves to a Saturday."""
    result = resolve_date_hint("thứ bảy", NOW_VN)
    assert result.start.weekday() == 5  # Saturday


# ---- NLU-31: resolve_date_hint "chủ nhật" -> Sunday ---------------------
def test_NLU31_resolve_chu_nhat():
    """Contract: 'chủ nhật' resolves to a Sunday."""
    result = resolve_date_hint("chủ nhật", NOW_VN)
    assert result.start.weekday() == 6  # Sunday


# ---- NLU-32: NluResult with float duration is rounded to int --------------
def test_NLU32_float_duration_rounded():
    """Contract: NluResult accepts float duration and rounds to nearest int."""
    result = NluResult(intent="schedule_task", duration_minutes=90.7)
    assert result.duration_minutes == 91
