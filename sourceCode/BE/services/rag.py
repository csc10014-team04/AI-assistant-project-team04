# owner: Database & AI (P2-2 RAG pipeline: file text -> chunks -> embeddings -> per-user encrypted vector index)
import json
import math
import os
import re
import threading
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path

from services.ai_logging import log_ai_failure
from services.privacy import decrypt_text, encrypt_text

RAG_DIR = Path(os.getenv("RAG_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data" / "rag")))
EMBED_DIM = 512
CHUNK_CHARS = 400
CHUNK_OVERLAP = 80
MIN_SCORE = 0.12  # below this the retrieval is treated as a miss and logged for prompt tuning


def fold(text: str) -> str:
    """lowercase + strip Vietnamese diacritics so 'đồ án' and 'do an' embed identically."""
    nfd = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """
    deterministic offline embedding (feature hashing of word unigrams/bigrams + char trigrams, L2-normalised).
    no network and no model download, so personal schedule text never leaves the host (P1-2). swap this one
    function for a sentence-transformer if a GPU budget is available; the index format stays the same.
    """
    words = re.findall(r"\w+", fold(text))
    feats = list(words) + [f"{a}_{b}" for a, b in zip(words, words[1:])]
    for w in words:
        padded = f"^{w}$"
        feats += [padded[i : i + 3] for i in range(len(padded) - 2)]
    vec = [0.0] * dim
    for f in feats:
        h = zlib.crc32(f.encode("utf-8"))
        vec[h % dim] += 1.0 if (h >> 16) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    split extracted timetable text into chunks: whole lines are kept together (a timetable row is never cut),
    lines are packed up to `size` chars, and the last `overlap` chars are repeated into the next chunk.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    chunks: list[str] = []
    current = ""
    for line in lines:
        line = line[:size]
        if current and len(current) + len(line) + 1 > size:
            chunks.append(current)
            current = current[-overlap:].split("\n", 1)[-1] if overlap else ""
        current = f"{current}\n{line}".strip("\n") if current else line
    if current:
        chunks.append(current)
    return chunks


@dataclass
class Hit:
    text: str
    score: float
    source: str


class VectorIndex:
    """per-owner vector store persisted as one Fernet-encrypted JSON file (local encryption, P1-2)."""

    _lock = threading.Lock()

    def __init__(self, owner_id: int, directory: Path | None = None) -> None:
        self.owner_id = owner_id
        self.path = (directory or RAG_DIR) / f"owner_{int(owner_id)}.idx"
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        plain = decrypt_text(self.path.read_text(encoding="ascii"))
        return json.loads(plain) if plain else []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(encrypt_text(json.dumps(self._items)), encoding="ascii")

    def __len__(self) -> int:
        return len(self._items)

    def replace_source(self, source: str, chunks: list[str]) -> int:
        """re-import safe: drop all chunks previously indexed from `source`, then add the new ones."""
        with self._lock:
            self._items = [i for i in self._items if i["source"] != source]
            self._items += [{"source": source, "text": c, "vec": embed(c)} for c in chunks]
            self._save()
        return len(chunks)

    def drop_sources_starting_with(self, prefix: str) -> int:
        """remove every chunk whose source name starts with `prefix`; returns how many were removed."""
        with self._lock:
            kept = [i for i in self._items if not i["source"].startswith(prefix)]
            removed = len(self._items) - len(kept)
            if removed:
                self._items = kept
                self._save()
        return removed

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self.path.unlink(missing_ok=True)

    def search(self, query: str, k: int = 3) -> list[Hit]:
        q = embed(query)
        scored = [Hit(i["text"], sum(a * b for a, b in zip(q, i["vec"])), i["source"]) for i in self._items]
        return sorted(scored, key=lambda h: h.score, reverse=True)[:k]


def ingest_file(owner_id: int, file_bytes: bytes, filename: str, directory: Path | None = None) -> int:
    """
    input: owner_id, raw bytes of a .pdf/.png/.jpg/.csv/.md/.txt timetable, original filename.
    core logic: parser.extract_raw_text_from_file (pdf text layer / OCR for images) -> chunk -> embed -> index.
    output: number of chunks indexed. Extraction failure or empty text is logged as RAG_EXTRACTION_FAILED and
            raises ValueError so the API can tell the user instead of silently indexing nothing.
    """
    from services.parser import extract_raw_text_from_file  # lazy: pulls optional pdf/ocr deps

    try:
        text = extract_raw_text_from_file(file_bytes, filename)
    except Exception as exc:  # parser raises on unsupported / OCR-less environments
        log_ai_failure("RAG_EXTRACTION_FAILED", f"file:{filename}", f"{type(exc).__name__}: {exc}", user_id=owner_id)
        raise ValueError(f"cannot extract text from {filename}: {exc}") from exc
    chunks = chunk_text(text)
    if not chunks:
        log_ai_failure("RAG_EXTRACTION_FAILED", f"file:{filename}", "extracted text was empty", user_id=owner_id)
        raise ValueError(f"no readable text found in {filename}")
    return VectorIndex(owner_id, directory).replace_source(filename, chunks)


TIMETABLE_SOURCE_PREFIX = "timetable-"
_WEEKDAY_VN = {"MON": "Thứ 2", "TUE": "Thứ 3", "WED": "Thứ 4", "THU": "Thứ 5", "FRI": "Thứ 6", "SAT": "Thứ 7", "SUN": "Chủ nhật"}


def describe_timetable_row(row) -> str:
    """one human-readable line for a committed timetable row (a duck-typed ParsedCsvRow / CsvRowPayload)."""
    day = _WEEKDAY_VN.get(getattr(getattr(row, "weekday", None), "value", getattr(row, "weekday", None)) or "", "")
    kind = getattr(row.kind, "value", row.kind)
    where = f", phòng {row.room}" if getattr(row, "room", None) else ""
    code = f"{row.course_code} " if getattr(row, "course_code", "") else ""
    when = f"{day} " if day else ""
    return (f"{code}{row.title} ({kind}): {when}{row.start_time:%H:%M}-{row.end_time:%H:%M}{where}, "
            f"từ {row.first_date.isoformat()} đến {row.last_date.isoformat()}")


def index_timetable_rows(owner_id: int, batch_id: str, rows: list, replace_previous: bool = False,
                         directory: Path | None = None) -> int:
    """
    P1-4: index structured timetable data (the rows a student just confirmed) as searchable text so the AI can
    retrieve "what classes do I have on Monday" context instead of relying on static parsing.
    Each import batch is its own source, so importing a second file does not erase the first; a replacing
    import first drops every earlier timetable source (same rule as the database re-import).
    """
    index = VectorIndex(owner_id, directory)
    if replace_previous:
        index.drop_sources_starting_with(TIMETABLE_SOURCE_PREFIX)
    chunks = chunk_text(chr(10).join(describe_timetable_row(r) for r in rows))
    return index.replace_source(f"{TIMETABLE_SOURCE_PREFIX}{batch_id}", chunks) if chunks else 0


def retrieve(owner_id: int, query: str, k: int = 3, directory: Path | None = None) -> list[Hit]:
    """top-k chunks for `query`; logs RAG_EMPTY_RETRIEVAL / RAG_LOW_SCORE so prompts can be tuned later."""
    index = VectorIndex(owner_id, directory)
    if len(index) == 0:
        return []  # user has not indexed anything; not a failure
    hits = [h for h in index.search(query, k) if h.score >= MIN_SCORE]
    if not hits:
        best = index.search(query, 1)
        log_ai_failure("RAG_LOW_SCORE" if best else "RAG_EMPTY_RETRIEVAL", query,
                       f"best score {best[0].score:.3f} < {MIN_SCORE}" if best else "empty index", user_id=owner_id,
                       retrieved_context=[b.text for b in best])
    return hits
