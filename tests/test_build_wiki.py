from pathlib import Path

import pytest

from scripts.build_wiki import (
    REPO_URL,
    PrivateSource,
    build,
    link_paths,
    public_paths,
    read_allowlist,
    render_doc,
    slug,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PAGES = {
    "Home.md",
    "Construct.md",
    "Rubric.md",
    "Method.md",
    "Running-the-harness.md",
    "Scenario-format.md",
    "Decisions.md",
    "Contributing-and-governance.md",
    "Roadmap.md",
    "_Sidebar.md",
    "_Footer.md",
}


def test_allowlist_is_the_mirror_allowlist() -> None:
    entries = read_allowlist(ROOT)
    assert "src" in entries and "docs/construct.md" in entries and "docs/wiki" in entries
    assert not any(entry.startswith(("docs/eoi", "docs/superpowers")) for entry in entries)


def test_public_paths_exclude_private_material() -> None:
    public = public_paths(ROOT)
    assert {"docs/construct.md", "src/kupuna_bench/run.py", "docs/wiki/Home.md"} <= public
    private_prefixes = ("docs/eoi/", "docs/superpowers/", "labels/melissa", "labels/jeremy", "results/run-")
    assert not any(path.startswith(private_prefixes) for path in public)
    assert "PIVOT.md" not in public and "HANDOFF.md" not in public
    assert not any("-ai-coding-" in path for path in public)


def test_link_paths_links_only_public_paths() -> None:
    public = {"docs/rubric.yaml", "docs/construct.md", "LICENSE"}
    page_for = {"docs/construct.md": "Construct"}
    text = "See `docs/rubric.yaml`, `docs/construct.md`, `docs/eoi/Q13-measure-why.md`, `docs/`, and `uv`."
    out = link_paths(text, public, page_for)
    assert f"[`docs/rubric.yaml`]({REPO_URL}/blob/main/docs/rubric.yaml)" in out
    assert "[`docs/construct.md`](Construct)" in out
    assert "`docs/eoi/Q13-measure-why.md`" in out
    assert "docs/eoi" not in out.replace("`docs/eoi/Q13-measure-why.md`", "")
    assert f"[`docs/`]({REPO_URL}/tree/main/docs)" in out
    assert "`uv`" in out and "(uv)" not in out


def test_slug_matches_github_anchors() -> None:
    title = "ADR-004: One `run` call, one `regrade` call, frozen values, no files"
    assert slug(title) == "adr-004-one-run-call-one-regrade-call-frozen-values-no-files"


def test_render_refuses_private_source() -> None:
    with pytest.raises(PrivateSource):
        render_doc(ROOT, "docs/eoi/Q13-measure-why.md", "abc1234", public_paths(ROOT), {})


def test_build_writes_every_page_and_names_the_commit(tmp_path: Path) -> None:
    (tmp_path / "stale.md").write_text("old page", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    written = build(ROOT, tmp_path, commit="abc1234", date="2026-09-08")
    assert {path.name for path in written} == EXPECTED_PAGES
    assert not (tmp_path / "stale.md").exists() and (tmp_path / ".git").is_dir()
    footer = (tmp_path / "_Footer.md").read_text(encoding="utf-8")
    assert "abc1234" in footer and "2026-09-08" in footer
    decisions = (tmp_path / "Decisions.md").read_text(encoding="utf-8")
    assert "## ADR-008" in decisions and "(#adr-008-public-mirror-with-a-fresh-history)" in decisions
    construct = (tmp_path / "Construct.md").read_text(encoding="utf-8")
    assert "working commit `abc1234`" in construct
    for path in written:
        text = path.read_text(encoding="utf-8")
        assert "blob/main/docs/eoi" not in text and "blob/main/PIVOT.md" not in text
        assert "{{" not in text
