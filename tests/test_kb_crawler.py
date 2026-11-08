"""KB-01..KB-10: knowledge-base collector (offline, no network): extraction, link rules, robots, privacy, loader."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("bs4")
from conftest import REPO_ROOT  # noqa: E402

CRAWLER_DIR = REPO_ROOT / "sourceCode" / "Database" / "knowledgebase" / "crawler"
sys.path.insert(0, str(CRAWLER_DIR))
import kb_crawler as kb  # noqa: E402
import load_into_backend_kb as loader  # noqa: E402

CFG = __import__("json").loads((CRAWLER_DIR.parent / "sources.json").read_text(encoding="utf-8"))

PAGE = """<html><head><title>Đội ngũ giảng viên - Khoa CNTT</title></head><body>
<nav><ul><li>Trang chủ</li><li>Tin tức</li></ul></nav>
<div class="breadcrumb">Home / Staff</div>
<main><h1>Đội ngũ giảng viên</h1>
<p>Khoa gồm các bộ môn: Khoa học máy tính, Công nghệ tri thức, Mạng máy tính.</p>
<ul><li>GS.TS. Lê Hoài Bắc</li><li>PGS.TS. Đinh Điền - liên hệ dd@example.edu hoặc 0901 234 567</li></ul>
<table><tr><th>Môn</th><th>Số tín chỉ</th></tr><tr><td>Cấu trúc dữ liệu</td><td>4</td></tr></table>
<script>var secret = 1;</script></main><footer>Copyright 2026</footer></body></html>"""


def test_KB01_extract_keeps_content_and_drops_menus_scripts_and_footers():
    title, text = kb.extract_page(PAGE)
    assert title.startswith("Đội ngũ giảng viên")
    assert "# Đội ngũ giảng viên" in text and "- GS.TS. Lê Hoài Bắc" in text and "Cấu trúc dữ liệu | 4" in text
    for noise in ("Trang chủ", "Copyright", "secret", "Home / Staff"):
        assert noise not in text


def test_KB02_emails_and_phone_numbers_are_redacted():
    _, text = kb.extract_page(PAGE)
    assert "dd@example.edu" not in text and "0901 234 567" not in text and "[email removed]" in text and "[phone removed]" in text


def test_KB03_fold_removes_vietnamese_accents():
    assert kb.fold("Giảng viên Đại học") == "giang vien dai hoc"


def test_KB04_staff_and_course_links_outrank_news_links():
    kw = CFG["priority_keywords"]
    staff = kb.link_score("https://x.edu.vn/gioi-thieu/doi-ngu-giang-vien", "Đội ngũ giảng viên", kw)
    news = kb.link_score("https://x.edu.vn/tin-tuc/hop-mat-cuoi-nam", "Tin tức", kw)
    assert staff > news


@pytest.mark.parametrize("url,ok", [
    ("https://www.fit.hcmus.edu.vn/gioi-thieu/doi-ngu", True),
    ("https://fit.hcmus.edu.vn/gioi-thieu", True),                      # www and bare host are the same site
    ("https://www.fit.hcmus.edu.vn/search?q=abc", False),              # query strings are crawl traps
    ("https://www.fit.hcmus.edu.vn/files/chuong-trinh.pdf", False),    # files are not collected
    ("https://www.fit.hcmus.edu.vn/admin/login", False),
    ("https://facebook.com/fit", False),                                # other site
    ("mailto:a@b.c", False),
])
def test_KB05_which_urls_may_be_visited(url, ok):
    assert kb.is_candidate_url(url, "www.fit.hcmus.edu.vn", CFG) is ok


def test_KB06_links_are_resolved_and_fragments_and_mail_links_ignored():
    html = '<a href="/a#top">A</a><a href="b">B</a><a href="mailto:x@y.z">M</a><a href="javascript:void(0)">J</a>'
    assert kb.extract_links(html, "https://s.edu.vn/dir/") == [("https://s.edu.vn/a", "A"), ("https://s.edu.vn/dir/b", "B")]


def test_KB07_slug_is_filesystem_safe_unique_and_stable():
    a = kb.slugify("https://s.edu.vn/Giới-thiệu/Đội ngũ")
    assert a == kb.slugify("https://s.edu.vn/Giới-thiệu/Đội ngũ") and a != kb.slugify("https://s.edu.vn/Giới-thiệu/Đội-ngũ-2")
    assert all(c.isalnum() or c == "-" for c in a)


def test_KB08_robots_disallow_and_crawl_delay_are_honoured(monkeypatch):
    class Stub(kb.Fetcher):
        def get(self, url, attempts=3):
            return 200, "text/plain", "User-agent: *\nDisallow: /admin/\nCrawl-delay: 10\n"

    rp = kb.load_robots("https://s.edu.vn/", Stub("ua", 1000, 0))
    assert rp.can_fetch("ua", "https://s.edu.vn/gioi-thieu") and not rp.can_fetch("ua", "https://s.edu.vn/admin/x")
    assert rp.crawl_delay("ua") == 10


def test_KB09_html_error_page_instead_of_robots_means_nothing_is_disallowed():
    class Stub(kb.Fetcher):
        def get(self, url, attempts=3):
            return 200, "text/html; charset=utf-8", "<html>Page Not Found</html>"  # some sites answer 200 + HTML

    assert kb.load_robots("https://s.edu.vn/", Stub("ua", 1000, 0)).can_fetch("ua", "https://s.edu.vn/anything")


def test_KB10_loader_indexes_pages_so_retrieval_finds_them(tmp_path):
    from services import rag
    from services.search_engine import ACADEMIC_KB_OWNER_ID

    data = tmp_path / "data" / "fit"
    data.mkdir(parents=True)
    title, text = kb.extract_page(PAGE)
    (data / "doi-ngu.md").write_text(f"---\nsource_url: https://x\n---\n\n# {title}\n\n{text}\n", encoding="utf-8")
    rag_dir = tmp_path / "kb"
    assert loader.load(tmp_path / "data", dry_run=True) == {"pages": 1, "chunks": 0, "failed": []}
    out = loader.load(tmp_path / "data", rag_dir=rag_dir)
    assert out["pages"] == 1 and out["chunks"] >= 1 and out["failed"] == []
    hits = rag.retrieve(ACADEMIC_KB_OWNER_ID, "ai là giảng viên của khoa", k=1, directory=rag_dir)
    assert hits and hits[0].source == "fit__doi-ngu.md" and "Lê Hoài Bắc" in hits[0].text
    again = loader.load(tmp_path / "data", rag_dir=rag_dir)  # second run replaces, never duplicates
    assert len(rag.VectorIndex(ACADEMIC_KB_OWNER_ID, rag_dir)) == again["chunks"]


def test_KB11_non_ascii_links_are_percent_encoded_so_requests_cannot_crash():
    links = kb.extract_links('<a href="/gioi-thieu/tổ-bộ-môn">x</a>', "https://s.edu.vn/")
    assert links[0][0] == "https://s.edu.vn/gioi-thieu/t%E1%BB%95-b%E1%BB%99-m%C3%B4n"
    assert all(ord(c) < 128 for c in links[0][0]) and kb.ascii_url("https://s.edu.vn/a%20b") == "https://s.edu.vn/a%20b"
