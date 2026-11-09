# [pic: khoi] p2-6 vietnamese text & teencode normalization (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import re
import unicodedata
from dataclasses import dataclass, field

# whole-word teencode / abbreviation -> canonical Vietnamese
TEENCODE: dict[str, str] = {
    "ko": "không", "k": "không", "hok": "không", "hong": "không", "khong": "không",
    "dc": "được", "đc": "được", "duoc": "được", "vs": "với", "voi": "với",
    "bik": "biết", "wa": "quá", "z": "vậy", "ntn": "như thế nào",
    "hnay": "hôm nay", "hqua": "hôm qua",
    "t2": "thứ 2", "t3": "thứ 3", "t4": "thứ 4", "t5": "thứ 5", "t6": "thứ 6", "t7": "thứ 7",
    "cn": "chủ nhật", "dl": "deadline", "pls": "please", "plz": "please",
    "mk": "mình", "trc": "trước",
}

# non-diacritic phrase -> diacritic phrase (longest keys applied first)
RESTORE_PHRASES: dict[str, str] = {
    "sap xep": "sắp xếp", "xep lich": "xếp lịch", "xep cho": "xếp cho", "xep": "xếp",
    "lich": "lịch", "tieng": "tiếng", "gio": "giờ", "phut": "phút",
    "do an": "đồ án", "bai tap": "bài tập", "hoc bai": "học bài", "on thi": "ôn thi",
    "lam": "làm", "bai": "bài", "hoc": "học", "doc sach": "đọc sách", "hom nay": "hôm nay", "ngay mai": "ngày mai", "ngay kia": "ngày kia",
    "tuan nay": "tuần này", "tuan sau": "tuần sau", "cuoi tuan": "cuối tuần",
    "thang sau": "tháng sau", "cuoi thang": "cuối tháng", "chu nhat": "chủ nhật",
    "thu hai": "thứ hai", "thu ba": "thứ ba", "thu tu": "thứ tư", "thu nam": "thứ năm",
    "thu sau": "thứ sáu", "thu bay": "thứ bảy",
    "buoi sang": "buổi sáng", "buoi chieu": "buổi chiều", "buoi toi": "buổi tối",
    "nhe": "nhé", "giup": "giúp", "minh": "mình", "xoa": "xóa", "huy": "hủy",
    "doi": "dời", "chuyen": "chuyển", "quan trong": "quan trọng", "gap": "gấp",
    "nop": "nộp", "hop": "họp",
}

PROFANITY = {"dm", "đm", "dmm", "đmm", "vcl", "vl", "cc", "clm", "đéo", "deo", "cút", "đụ", "lồn", "cặc", "shit", "fuck"}

_ALLOWED = re.compile(r"[^\w\s.,:;!?/()%+\-–']", re.UNICODE)
_EMOJI_SYMBOLS = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
_REPEAT = re.compile(r"(.)\1{2,}")  # "xếpppp" -> "xếpp"


@dataclass
class NormalizedText:
    text: str
    original: str
    profanity_found: bool = False
    changes: list[str] = field(default_factory=list)


def _word_sub(text: str, mapping: dict[str, str], changes: list[str], tag: str) -> str:
    """replace whole words/phrases (case-insensitive), longest keys first, recording each change."""
    for key in sorted(mapping, key=len, reverse=True):
        value = mapping[key]
        if key == value:
            continue
        pattern = re.compile(rf"(?<![\w]){re.escape(key)}(?![\w])", re.IGNORECASE)
        new_text, n = pattern.subn(value, text)
        if n:
            changes.append(f"{tag}:{key}->{value}")
            text = new_text
    return text


def normalize_text(raw: str) -> NormalizedText:
    """
    input: raw (str) user prompt, possibly without diacritics, teencode, emoji or profanity.
    core logic: NFC -> drop emoji/unsupported symbols -> squeeze repeated letters -> remove profanity ->
                restore diacritics for known scheduling phrases -> teencode dictionary -> collapse spaces.
    output: NormalizedText(text, original, profanity_found, changes). Never raises.
    typical flow: "xep lich 3 tieng lam do an ko buoi toi nhe" -> "xếp lịch 3 tiếng làm đồ án không buổi tối nhé".
    """
    changes: list[str] = []
    text = unicodedata.normalize("NFC", raw or "")
    stripped = _ALLOWED.sub(" ", _EMOJI_SYMBOLS.sub(" ", text))
    if stripped != text:
        changes.append("special_chars_removed")
    text = _REPEAT.sub(r"\1\1", stripped)

    profanity = False
    kept: list[str] = []
    for word in text.split():
        if word.lower().strip(".,!?") in PROFANITY:
            profanity = True
            continue
        kept.append(word)
    if profanity:
        changes.append("profanity_removed")
    text = " ".join(kept)

    text = _word_sub(text, RESTORE_PHRASES, changes, "diacritics")
    text = _word_sub(text, TEENCODE, changes, "teencode")
    text = re.sub(r"\s+", " ", text).strip()
    return NormalizedText(text=text, original=raw, profanity_found=profanity, changes=changes)
