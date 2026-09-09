"""The built wheel must load the default rubric from outside the source tree (review finding 9)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def test_installed_wheel_loads_the_default_rubric(tmp_path: Path) -> None:
    built = _run(["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist")], ROOT)
    assert built.returncode == 0, built.stderr
    wheel = next((tmp_path / "dist").glob("*.whl"))
    venv = tmp_path / "venv"
    assert _run(["uv", "venv", "-q", str(venv)], tmp_path).returncode == 0
    python = venv / "bin" / "python"
    installed = _run(["uv", "pip", "install", "-q", "--python", str(python), str(wheel)], tmp_path)
    assert installed.returncode == 0, installed.stderr
    code = "from kupuna_bench.rubric import load_rubric; print(load_rubric().version)"
    out = _run([str(python), "-c", code], tmp_path)  # cwd outside the source tree
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "0.1.0"
