"""PH-01..PH-10: whole-repository health checks that catch merge accidents, broken wiring and stale docs."""
import ast
import re
import sys
from collections import Counter

import pytest

from conftest import BE_DIR, DEPLOY_DIR, FE_DIR, REPO_ROOT

SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "UniInfo"}


def files(pattern: str):
    return [p for p in REPO_ROOT.rglob(pattern) if not SKIP_PARTS & set(p.parts)]


def test_PH01_no_git_conflict_markers_in_any_text_file():
    bad = []
    for p in files("*"):
        if not p.is_file() or p.suffix.lower() in {".png", ".jpg", ".docx", ".pdf", ".svg", ".idx", ".ico"}:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"^(<<<<<<< |>>>>>>> )", text, re.MULTILINE):
            bad.append(str(p.relative_to(REPO_ROOT)))
    assert bad == []


def test_PH02_every_python_file_compiles():
    bad = []
    for p in files("*.py"):
        try:
            compile(p.read_text(encoding="utf-8-sig"), str(p), "exec")
        except SyntaxError as exc:
            bad.append((str(p.relative_to(REPO_ROOT)), exc.lineno))
    assert bad == []


def test_PH03_no_module_defines_the_same_class_or_function_twice():
    """a later definition silently replaces the earlier one: the typical leftover of a bad merge (calendar_screen.py had two)."""
    dup = {}
    for p in files("*.py"):
        if "tests" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        counts = Counter(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        twice = [k for k, v in counts.items() if v > 1]
        if twice:
            dup[str(p.relative_to(REPO_ROOT))] = twice
    assert dup == {}


def test_PH04_frontend_only_calls_api_client_methods_that_exist_with_valid_arguments():
    tree = ast.parse((FE_DIR / "api_client.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "APIClient")
    methods = {n.name: [a.arg for a in n.args.args[1:]] for n in cls.body if isinstance(n, ast.FunctionDef)}
    problems = []
    for f in FE_DIR.glob("*.py"):
        if f.name == "api_client.py":
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8-sig"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "api":
                name = n.func.attr
                if name in methods:
                    unknown = {k.arg for k in n.keywords if k.arg} - set(methods[name])
                    if unknown or len(n.args) > len(methods[name]):
                        problems.append((f.name, n.lineno, name, unknown))
                elif name not in {"base_url", "store", "access_token", "user_id", "display_name"}:
                    problems.append((f.name, n.lineno, name, "no such method"))
    assert problems == []


def test_PH05_no_undefined_names_in_the_frontend_or_backend():
    flakes = pytest.importorskip("pyflakes.api")
    import io

    from pyflakes.reporter import Reporter

    out = io.StringIO()
    for folder in (FE_DIR, BE_DIR / "routers", BE_DIR / "services"):
        for f in folder.glob("*.py"):
            flakes.check(f.read_text(encoding="utf-8-sig"), str(f), Reporter(out, out))
    undefined = [l for l in out.getvalue().splitlines() if "undefined name" in l]
    assert undefined == []


def test_PH06_backend_third_party_imports_are_in_requirements():
    std = set(sys.stdlib_module_names)
    local = {p.stem for p in BE_DIR.glob("*.py")} | {"routers", "services", "tools", "database", "models", "main"}
    alias = {"jwt": "pyjwt", "PIL": "pillow", "multipart": "python_multipart", "starlette": "fastapi"}
    req = (BE_DIR / "requirements.txt").read_text(encoding="utf-8")
    have = {re.split(r"[<>=\[ ;#]", l.strip())[0].lower().replace("-", "_") for l in req.splitlines() if l.strip() and not l.startswith("#")}
    optional = {"sentence_transformers"}  # behind ENABLE_NEURAL_SEARCH_FALLBACK, documented as optional
    missing = set()
    for f in list(BE_DIR.glob("*.py")) + list((BE_DIR / "routers").glob("*.py")) + list((BE_DIR / "services").glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8-sig"))):
            names = [a.name.split(".")[0] for a in n.names] if isinstance(n, ast.Import) else \
                    [n.module.split(".")[0]] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else []
            for m in names:
                if m not in std and m not in local and m not in optional and alias.get(m, m).lower().replace("-", "_") not in have:
                    missing.add(m)
    assert missing == set()


def test_PH07_dockerfiles_have_no_bom_and_their_start_command_exists():
    for df in DEPLOY_DIR.glob("*/Dockerfile"):
        raw = df.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{df} starts with a byte-order mark"
        cmd = re.search(r'CMD \["uvicorn", "(\w+):(\w+)"', raw.decode("utf-8"))
        assert cmd, f"{df} does not start uvicorn"
        module = df.parent / f"{cmd.group(1)}.py"
        assert module.is_file() and re.search(rf"^{cmd.group(2)}\s*=", module.read_text(encoding="utf-8"), re.MULTILINE), f"{df}: {cmd.group(1)}:{cmd.group(2)} not found"


def test_PH08_compose_port_of_each_service_matches_the_port_its_container_listens_on():
    compose = (DEPLOY_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    for service, host_port in (("frontend", 80), ("backend", 8080)):
        dockerfile = (DEPLOY_DIR / service / "Dockerfile").read_text(encoding="utf-8")
        listens = int(re.search(r"--port\", \"(\d+)\"", dockerfile).group(1))
        assert f'"{host_port}:{listens}"' in compose, f"{service}: compose maps to a port the container does not listen on"


def test_PH09_no_readme_is_empty():
    empty = [str(p.relative_to(REPO_ROOT)) for p in files("README.md") if p.stat().st_size < 40]
    assert empty == []


def test_PH10_readmes_list_the_current_team_of_five():
    text = "\n".join(p.read_text(encoding="utf-8") for p in files("README.md"))
    assert "Phạm Phúc Nguyên" not in text and "P.Nguyên" not in text and "Phúc Nguyên" not in text
    for member in ("Ngô Vũ Khôi Nguyên", "Huỳnh Nhật Duy", "Nguyễn Tường Lâm", "Đinh Quang Thịnh", "Trương Anh Khôi"):
        assert member in (REPO_ROOT / "README.md").read_text(encoding="utf-8"), member
