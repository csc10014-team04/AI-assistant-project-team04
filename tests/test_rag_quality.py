"""
QA: retrieval quality of the offline vector index (services.rag: feature-hashing embed + VectorIndex.search).

Standard / method : Cranfield-style IR evaluation (labelled queries -> relevant ids): Hit@k, Recall@k, MRR, nDCG@k
                    (Jarvelin & Kekalainen 2002; Manning/Raghavan/Schutze "Introduction to Information Retrieval" ch.8);
                    rejection of out-of-scope queries via MIN_SCORE (0.12). ISO/IEC 25010 Functional correctness.
Run               : cd sourceCode/BE && .venv\\Scripts\\python -m pytest "../../QA  docs/test_rag_quality.py" -v -s
Offline: no MySQL, no LLM, no network. The index is built in a temp folder; nothing is written to the repo.

Dataset (files next to this test): search_eval.jsonl = 72 answerable + 12 out-of-scope queries (plan minimum 50, +44%),
search_eval_corpus.jsonl = the documents, over two corpora:
  A) 24 timetable lines in the exact format produced by rag.describe_timetable_row (what the assistant really indexes)
  B) 20 short academic-regulation paragraphs (SYNTHETIC text written by QA; real regulations are not in the repo)
LIMITATION: queries and relevance labels were written by one person who knew the corpus, and the regulation text is
synthetic. Treat the numbers as a regression baseline and an upper bound, not as field accuracy. The hard group
("paraphrase") deliberately uses words that do not occur in the target text.
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pytest

BE_ROOT = next(p / "sourceCode" / "BE" for p in Path(__file__).resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())  # works wherever this file is placed
if str(BE_ROOT) not in sys.path:
    sys.path.insert(0, str(BE_ROOT))

from services.rag import MIN_SCORE, VectorIndex  # noqa: E402

# ------------------------------------------------------------------ dataset: search_eval.jsonl + search_eval_corpus.jsonl
DATA_DIR = Path(__file__).resolve().parent
_corpus = [json.loads(ln) for ln in (DATA_DIR / "search_eval_corpus.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
TIMETABLE = {c["id"]: c["text"] for c in _corpus if c["corpus"] == "A"}  # timetable lines (rag.describe_timetable_row format)
REGS = {c["id"]: c["text"] for c in _corpus if c["corpus"] == "B"}  # synthetic regulation paragraphs
_queries = [json.loads(ln) for ln in (DATA_DIR / "search_eval.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
Q = [(r["corpus"], r["group"], r["query"], set(r["relevant"])) for r in _queries if r["in_scope"]]
OUT_OF_SCOPE = [r["query"] for r in _queries if not r["in_scope"]]
N_ANSWERABLE = len(Q)

# regression floors (observed value minus >= 5 percentage points; see the printed report). Raise them when retrieval improves.
#   observed 2026-11-18 on 72 queries: Hit@1 .85, Hit@3 .90, MRR .88, nDCG@3 .87, out-of-scope rejection .25 (the weak spot)
FLOORS = {"hit1": 0.80, "hit3": 0.85, "mrr": 0.83, "ndcg3": 0.82, "reject": 0.20}


# ------------------------------------------------------------------ metrics
def ndcg_at(ranked: list[str], rel: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(ranked[:k]) if r in rel)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(rel))))
    return dcg / ideal if ideal else 0.0


@pytest.fixture(scope="module")
def indexes(tmp_path_factory):
    d = tmp_path_factory.mktemp("rag")
    a, b = VectorIndex(1, d), VectorIndex(2, d)
    for sid, text in TIMETABLE.items():
        a.replace_source(sid, [text])
    for sid, text in REGS.items():
        b.replace_source(sid, [text])
    return {"A": a, "B": b}


@pytest.fixture(scope="module")
def results(indexes):
    rows = []
    for corpus, group, query, rel in Q:
        hits = indexes[corpus].search(query, 5)
        ranked = [h.source for h in hits]
        rank = next((i + 1 for i, r in enumerate(ranked) if r in rel), None)
        rows.append({"corpus": corpus, "group": group, "query": query, "rel": rel, "ranked": ranked,
                     "top_score": hits[0].score, "rank": rank,
                     "hit1": bool(ranked[:1] and ranked[0] in rel), "hit3": any(r in rel for r in ranked[:3]),
                     "recall3": len(set(ranked[:3]) & rel) / len(rel), "rr": 1 / rank if rank else 0.0,
                     "ndcg3": ndcg_at(ranked, rel, 3)})
    return rows


def mean(rows, key):
    return sum(float(r[key]) for r in rows) / len(rows) if rows else float("nan")


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


# ------------------------------------------------------------------ tests
class TestDataset:
    def test_answerable_query_count_exceeds_plan_minimum(self):
        assert N_ANSWERABLE >= 55  # plan minimum 50, +10%
        assert len(OUT_OF_SCOPE) >= 12

    def test_every_relevant_id_exists_in_a_corpus(self):
        for corpus, _, q, rel in Q:
            ids = set(TIMETABLE) if corpus == "A" else set(REGS)
            assert rel <= ids, f"{q}: unknown id in {rel - ids}"

    def test_corpus_chunks_fit_in_one_chunk_each(self):
        assert all(len(t) <= 400 for t in [*TIMETABLE.values(), *REGS.values()])


class TestRetrievalQuality:
    def test_report_and_floors(self, results, indexes):
        by_group = defaultdict(list)
        for r in results:
            by_group[r["group"]].append(r)
        n = len(results)
        k1 = sum(r["hit1"] for r in results)
        lo, hi = wilson(k1, n)
        print(f"\n[rag] {n} answerable queries over 2 corpora (A timetable 24 chunks, B regulations 20 chunks)")
        print(f"{'group':<11}{'n':>4}{'Hit@1':>8}{'Hit@3':>8}{'Rec@3':>8}{'MRR':>8}{'nDCG@3':>8}")
        for g in ["exact", "code", "room", "noaccent", "weekday", "paraphrase"]:
            rs = by_group[g]
            print(f"{g:<11}{len(rs):>4}{mean(rs, 'hit1'):>8.2f}{mean(rs, 'hit3'):>8.2f}{mean(rs, 'recall3'):>8.2f}{mean(rs, 'rr'):>8.2f}{mean(rs, 'ndcg3'):>8.2f}")
        print(f"{'ALL':<11}{n:>4}{mean(results, 'hit1'):>8.2f}{mean(results, 'hit3'):>8.2f}{mean(results, 'recall3'):>8.2f}{mean(results, 'rr'):>8.2f}{mean(results, 'ndcg3'):>8.2f}")
        print(f"Hit@1 = {k1}/{n} = {k1 / n:.1%}  Wilson 95% CI [{lo:.1%}, {hi:.1%}]")
        misses = [r for r in results if not r["hit3"]]
        print(f"queries with the right chunk NOT in top 3 ({len(misses)}):")
        for r in misses:
            print(f"   [{r['corpus']}/{r['group']}] {r['query']!r}  wanted={sorted(r['rel'])}  got={r['ranked'][:3]}  top_score={r['top_score']:.2f}")
        assert mean(results, "hit1") >= FLOORS["hit1"]
        assert mean(results, "hit3") >= FLOORS["hit3"]
        assert mean(results, "rr") >= FLOORS["mrr"]
        assert mean(results, "ndcg3") >= FLOORS["ndcg3"]

    def test_easy_groups_are_nearly_perfect(self, results):
        easy = [r for r in results if r["group"] in {"exact", "code", "room"}]
        assert mean(easy, "hit3") >= 0.85

    def test_scores_are_cosine_in_range(self, results):
        assert all(-1.0001 <= r["top_score"] <= 1.0001 for r in results)

    def test_ranking_is_deterministic(self, indexes):
        a = [h.source for h in indexes["A"].search("Giải tích 1 ở phòng nào", 5)]
        assert a == [h.source for h in indexes["A"].search("Giải tích 1 ở phòng nào", 5)]


class TestOutOfScopeRejection:
    def test_rejection_and_false_rejection_rates(self, results, indexes):
        rejected = total = 0
        leaks = []
        for q in OUT_OF_SCOPE:
            for name in ("A", "B"):
                total += 1
                best = indexes[name].search(q, 1)[0]
                if best.score < MIN_SCORE:
                    rejected += 1
                else:
                    leaks.append((name, q, round(best.score, 2), best.source))
        false_rej = [r for r in results if r["top_score"] < MIN_SCORE]
        print(f"\n[rag] out-of-scope rejected: {rejected}/{total} = {rejected / total:.1%} (MIN_SCORE={MIN_SCORE})")
        for leak in leaks:
            print(f"   answered although out of scope: {leak}")
        print(f"[rag] answerable queries wrongly rejected (top score < {MIN_SCORE}): {len(false_rej)}/{len(results)}")
        for r in false_rej:
            print(f"   {r['query']!r} top_score={r['top_score']:.2f}")
        # threshold sweep: what MIN_SCORE would separate in-scope from out-of-scope on this dataset?
        oos_scores = [indexes[n].search(q, 1)[0].score for q in OUT_OF_SCOPE for n in ("A", "B")]
        print("[rag] threshold sweep   min_score  out-of-scope rejected  answerable wrongly rejected")
        for t in (0.12, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40):
            rej = sum(s < t for s in oos_scores) / len(oos_scores)
            wrong = sum(r["top_score"] < t for r in results) / len(results)
            print(f"                          {t:>8.2f}  {rej:>20.0%}  {wrong:>26.0%}")
        assert total >= 24
        assert rejected / total >= FLOORS["reject"]

    def test_empty_query_scores_zero(self, indexes):
        assert all(h.score == 0.0 for h in indexes["A"].search("", 3))
