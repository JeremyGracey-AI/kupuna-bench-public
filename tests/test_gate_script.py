"""The local gate is the CI workflow: the same steps, one per line, run by a tracked pre-commit hook.

Post-mortem, 2026-09-08: a ruff error reached both mains because the gate was an `a && b` chain
inside a script, and a failing first command in a chain does not stop a shell under `set -e`.
The behavioral tests run the real script and the real hook with a stand-in `uv` on PATH.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "gate.sh"
HOOK = ROOT / ".githooks" / "pre-commit"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _without_out(command: str) -> str:
    """The plumbing run writes somewhere different in CI and locally; the path is not part of the step."""
    return re.sub(r"\s--out\s+\S+", "", command).strip()


def ci_steps() -> list[str]:
    """Every `run:` command of the CI job after Install, in order."""
    workflow = yaml.safe_load(CI.read_text(encoding="utf-8"))
    job = workflow["jobs"]["test"]
    steps = [step for step in job["steps"] if "run" in step and step.get("name") != "Install"]
    return [_without_out(step["run"]) for step in steps]


def gate_commands() -> list[str]:
    """Every non-comment, non-blank line of the gate script."""
    assert GATE.is_file(), "scripts/gate.sh is missing"
    lines = GATE.read_text(encoding="utf-8").splitlines()
    return [_without_out(line) for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _fake_uv(directory: Path, *, fail_on: str | None) -> dict[str, str]:
    """A stand-in `uv` that logs its arguments and fails when they mention `fail_on`."""
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / "uv.log"
    script = directory / "uv"
    fail_clause = f'case "$*" in *{fail_on}*) exit 1;; esac\n' if fail_on else ""
    script.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{log}"\n{fail_clause}exit 0\n', encoding="utf-8")
    script.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{directory}{os.pathsep}{env['PATH']}"
    return env


def _run_gate(env: dict[str, str], script: Path = GATE, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(script)], cwd=cwd, env=env, capture_output=True, text=True)


def test_gate_runs_every_ci_step_as_its_own_line() -> None:
    steps = ci_steps()
    assert len(steps) == 4, steps  # lint, types, tests, plumbing gate
    commands = gate_commands()
    for step in steps:
        assert step in commands, f"CI step {step!r} is not a line of scripts/gate.sh: {commands}"


def test_gate_and_ci_do_not_quiet_pytest_twice() -> None:
    """pyproject's addopts already has -q; a second -q hides the `N passed` summary line."""
    assert "-q" in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for command in ci_steps() + gate_commands():
        assert "pytest -q" not in command, command


def test_gate_runs_ci_steps_in_order_and_reports_green(tmp_path: Path) -> None:
    env = _fake_uv(tmp_path / "bin", fail_on=None)
    result = _run_gate(env)
    assert result.returncode == 0 and result.stdout.strip().endswith("gate: green"), result.stderr
    calls = (tmp_path / "bin" / "uv.log").read_text(encoding="utf-8").splitlines()
    assert [_without_out(f"uv {c}") for c in calls] == ci_steps()


def test_gate_stops_at_the_first_failing_step(tmp_path: Path) -> None:
    env = _fake_uv(tmp_path / "bin", fail_on="pyright")
    result = _run_gate(env)
    assert result.returncode != 0 and "gate: green" not in result.stdout
    calls = (tmp_path / "bin" / "uv.log").read_text(encoding="utf-8")
    assert "pyright" in calls and "pytest" not in calls and "kupuna-bench" not in calls


def test_gate_gates_its_own_tree_wherever_it_is_run_from(tmp_path: Path) -> None:
    env = _fake_uv(tmp_path / "bin", fail_on=None)
    result = _run_gate(env, cwd=tmp_path)  # a directory that is not a git repository
    assert result.returncode == 0, result.stderr


def _scratch_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    shutil.copy2(GATE, repo / "scripts" / "gate.sh")
    shutil.copy2(HOOK, repo / ".githooks" / "pre-commit")
    (repo / "note.txt").write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo


def _commit(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "commit", "-q", "-m", "gated"], cwd=repo, env=env, capture_output=True, text=True
    )


def test_hook_refuses_a_commit_when_the_gate_fails(tmp_path: Path) -> None:
    repo = _scratch_repo(tmp_path)
    result = _commit(repo, _fake_uv(tmp_path / "bin", fail_on="ruff"))
    assert result.returncode != 0
    head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo, capture_output=True)
    assert head.returncode != 0, "the commit must not exist"


def test_hook_gates_the_index_not_the_working_tree(tmp_path: Path) -> None:
    """Stage a file, then change it in the working tree without re-staging: the commit carries the staged
    content, so that is what the gate must see."""
    repo = _scratch_repo(tmp_path)
    marker = repo / "note.txt"
    marker.write_text("edited after staging\n", encoding="utf-8")
    env = _fake_uv(tmp_path / "bin", fail_on=None)
    # The stand-in uv records what the gated tree contains at the moment ruff runs.
    uv_log, tree_log = tmp_path / "bin" / "uv.log", tmp_path / "bin" / "tree.log"
    (tmp_path / "bin" / "uv").write_text(
        f'#!/usr/bin/env bash\necho "$*" >> "{uv_log}"\ncat note.txt >> "{tree_log}"\nexit 0\n',
        encoding="utf-8",
    )
    result = _commit(repo, env)
    assert result.returncode == 0, result.stderr
    assert "staged" in (tmp_path / "bin" / "tree.log").read_text(encoding="utf-8")
    assert "edited after staging" not in (tmp_path / "bin" / "tree.log").read_text(encoding="utf-8")


def test_gate_and_hook_are_executable() -> None:
    for script in (GATE, HOOK):
        assert script.is_file(), f"{script.relative_to(ROOT)} is missing"
        assert os.access(script, os.X_OK), f"{script.relative_to(ROOT)} is not executable"


def test_pre_commit_hook_installs_by_hooks_path_and_exports_the_index() -> None:
    text = HOOK.read_text(encoding="utf-8")
    assert "core.hooksPath" in text, "the hook must say how it is installed"
    assert "git checkout-index" in text and "scripts/gate.sh" in text
