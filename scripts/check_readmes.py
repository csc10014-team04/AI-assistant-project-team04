"""
Check every README.md in the repository.

    python scripts/check_readmes.py            # report problems, exit code 1 when there are any
    python scripts/check_readmes.py --list     # also print every README with its size

What it checks
  1. no README.md is empty (fewer than 40 characters)
  2. no README names a person who left the team (see FORMER_MEMBERS)
  3. the root README lists the current team (see TEAM)
  4. every relative link `[text](path)` and every `path` written in backticks that looks like a repo path points to a file or folder that exists

Keep TEAM and FORMER_MEMBERS up to date when the group changes; the test `tests/test_project_health.py` uses the same rules.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__"}

TEAM = ["Ngô Vũ Khôi Nguyên", "Huỳnh Nhật Duy", "Nguyễn Tường Lâm", "Đinh Quang Thịnh", "Trương Anh Khôi"]  # five members
FORMER_MEMBERS = ["Phạm Phúc Nguyên", "Phúc Nguyên", "P.Nguyên"]

LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def readmes() -> list[Path]:
    return sorted(p for p in ROOT.rglob("README.md") if not SKIP_PARTS & set(p.parts))


def broken_links(readme: Path) -> list[str]:
    bad = []
    text = readme.read_text(encoding="utf-8")
    for target in LINK_RE.findall(text):
        if target.startswith("file:"):
            bad.append(target + "  (absolute file:// path: use a relative link)")
            continue
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = target.split("#", 1)[0]
        if path and not (readme.parent / path).exists():
            bad.append(target)
    return bad


def problems() -> list[str]:
    found: list[str] = []
    for r in readmes():
        rel = r.relative_to(ROOT)
        text = r.read_text(encoding="utf-8")
        if len(text.strip()) < 40:
            found.append(f"{rel}: empty README")
        for name in FORMER_MEMBERS:
            if name in text:
                found.append(f"{rel}: mentions former member '{name}'")
        for target in broken_links(r):
            found.append(f"{rel}: broken link -> {target}")
    root_text = (ROOT / "README.md").read_text(encoding="utf-8")
    for member in TEAM:
        if member not in root_text:
            found.append(f"README.md: team member missing: {member}")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for r in readmes():
            print(f"{r.stat().st_size:7d}  {r.relative_to(ROOT)}")
    issues = problems()
    for line in issues:
        print("PROBLEM:", line)
    print(f"{len(issues)} problem(s) in {len(readmes())} README files")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
