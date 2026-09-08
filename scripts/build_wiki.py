"""Render the public wiki from repository documents.

The wiki is a rendering, never a source of truth (docs/decisions/ADR-009-generated-wiki.md). Every
page is built from files that the public-mirror allowlist in scripts/export_mirror.sh already
exports; a page whose source is not on that list cannot be built, so nothing the mirror excludes can
reach the wiki.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
from pathlib import Path

REPO_URL = "https://github.com/JeremyGracey-AI/kupuna-bench-public"  # moves with the mirror (ADR-001)

DOC_PAGES: dict[str, str] = {
    "Construct": "docs/construct.md",
    "Rubric": "docs/rubric.md",
    "Method": "docs/method.md",
    "Contributing-and-governance": "CONTRIBUTING.md",
}
TEMPLATE_PAGES = ("Home", "Running-the-harness", "Scenario-format", "Roadmap", "_Sidebar", "_Footer")
TEMPLATE_DIR = "docs/wiki"
DECISIONS_DIR = "docs/decisions"
GOVERNANCE_SECTION = """
## Governance documents

- AI use: `AI-USE.md` records what was AI-assisted, what is human, and who is accountable.
- Security and dual-use reports: `SECURITY.md`.
- Code of conduct: `CODE_OF_CONDUCT.md`.
- Decision records: [Decisions](Decisions).
"""

_ALLOWLIST_RE = re.compile(r"ALLOWLIST=\((.*?)\)", re.S)
_PATH_TOKEN_RE = re.compile(r"`((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+/?)`")


class PrivateSource(ValueError):
    """A page would be built from a file the mirror does not export."""


def read_allowlist(root: Path) -> list[str]:
    text = (root / "scripts" / "export_mirror.sh").read_text(encoding="utf-8")
    match = _ALLOWLIST_RE.search(text)
    if match is None:
        raise RuntimeError("scripts/export_mirror.sh has no ALLOWLIST=( ... ) block")
    return match.group(1).split()


def public_paths(root: Path) -> set[str]:
    """Every file the mirror exports, expanded from the allowlist exactly as the export expands it."""
    paths: set[str] = set()
    for entry in read_allowlist(root):
        target = root / entry
        if target.is_dir():
            for file in target.rglob("*"):
                if file.is_file() and "__pycache__" not in file.parts:
                    paths.add(file.relative_to(root).as_posix())
        elif target.is_file():
            paths.add(entry)
    return {p for p in paths if not (p.startswith("docs/memos/") and "-ai-coding-" in p)}


def _require_public(path: str, public: set[str]) -> None:
    if path not in public:
        raise PrivateSource(f"{path} is not on the public-mirror allowlist; the wiki cannot render it")


def slug(title: str) -> str:
    """GitHub's heading anchor for a title."""
    text = re.sub(r"[^a-z0-9 -]", "", title.replace("`", "").lower())
    return text.strip().replace(" ", "-")


def link_paths(text: str, public: set[str], page_for: dict[str, str]) -> str:
    """Backticked repository paths become links: wiki pages for rendered docs, blob or tree URLs otherwise."""
    trees: set[str] = set()
    for path in public:
        parts = path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            trees.add("/".join(parts[:depth]))

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token in page_for:
            return f"[`{token}`]({page_for[token]})"
        if token in public:
            return f"[`{token}`]({REPO_URL}/blob/main/{token})"
        if token.endswith("/") and token.rstrip("/") in trees:
            return f"[`{token}`]({REPO_URL}/tree/main/{token.rstrip('/')})"
        return match.group(0)

    return _PATH_TOKEN_RE.sub(replace, text)


def first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def source_line(path: str, commit: str) -> str:
    kind = "tree" if path.endswith("/") else "blob"
    return (
        f"_Source: [`{path}`]({REPO_URL}/{kind}/main/{path.rstrip('/')}) at working commit `{commit}`. "
        "Edit the source, not this page; every export regenerates the wiki._\n"
    )


def _with_source(text: str, path: str, commit: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join([*lines[: index + 1], "", source_line(path, commit), *lines[index + 1 :]])
    return source_line(path, commit) + "\n" + text


def render_doc(root: Path, path: str, commit: str, public: set[str], page_for: dict[str, str]) -> str:
    _require_public(path, public)
    text = _with_source((root / path).read_text(encoding="utf-8"), path, commit)
    return link_paths(text, public, page_for).rstrip() + "\n"


def render_decisions(root: Path, commit: str, public: set[str], page_for: dict[str, str]) -> str:
    files = sorted((root / DECISIONS_DIR).glob("ADR-*.md"))
    index: list[str] = []
    bodies: list[str] = []
    for file in files:
        rel = file.relative_to(root).as_posix()
        _require_public(rel, public)
        text = file.read_text(encoding="utf-8")
        title = first_heading(text)
        index.append(f"- [{title}](#{slug(title)})")
        demoted = "\n".join(("#" + line) if line.startswith("#") else line for line in text.splitlines())
        bodies.append(demoted.rstrip() + "\n")
    head = "# Decision records\n\n" + source_line(DECISIONS_DIR + "/", commit) + "\n" + "\n".join(index)
    page = head + "\n\n---\n\n" + "\n---\n\n".join(bodies)
    return link_paths(page, public, page_for)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def build(root: Path, out: Path, commit: str, date: str) -> list[Path]:
    public = public_paths(root)
    page_for = {path: page for page, path in DOC_PAGES.items()}
    for file in sorted((root / DECISIONS_DIR).glob("ADR-*.md")):
        title = first_heading(file.read_text(encoding="utf-8"))
        page_for[file.relative_to(root).as_posix()] = f"Decisions#{slug(title)}"
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():
        if child.name == ".git":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    written: list[Path] = []
    for page, path in DOC_PAGES.items():
        text = render_doc(root, path, commit, public, page_for)
        if page == "Contributing-and-governance":
            text += link_paths(GOVERNANCE_SECTION, public, page_for)
        written.append(_write(out / f"{page}.md", text))
    written.append(_write(out / "Decisions.md", render_decisions(root, commit, public, page_for)))
    for page in TEMPLATE_PAGES:
        source = f"{TEMPLATE_DIR}/{page}.md"
        _require_public(source, public)
        text = (
            (root / source)
            .read_text(encoding="utf-8")
            .replace("{{REPO_URL}}", REPO_URL)
            .replace("{{COMMIT}}", commit)
            .replace("{{DATE}}", date)
        )
        written.append(_write(out / f"{page}.md", link_paths(text, public, page_for)))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="wiki checkout directory (its .git is kept)")
    parser.add_argument("--root", type=Path, default=None, help="repository root (default: git toplevel)")
    parser.add_argument("--commit", default=None, help="working commit to name (default: short HEAD)")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args(argv)
    toplevel = ["git", "rev-parse", "--show-toplevel"]
    found = subprocess.run(toplevel, capture_output=True, text=True, check=True).stdout.strip()
    root = args.root or Path(found)
    commit = args.commit or subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    for path in build(root, args.out, commit, args.date):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
