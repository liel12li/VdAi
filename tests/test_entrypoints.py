"""Entry points must work when run directly, not only via ``python -m vdai``.

These guard against the relative-import breakage that happens when a file
inside the package is executed as a plain script (e.g. the VS Code ▶ button).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_run_file_cli_directly():
    # Reproduces `python vdai/cli.py` (what the VS Code Run button does).
    result = _run("vdai/cli.py", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage: vdai" in result.stdout
    assert "no known parent package" not in result.stderr


def test_run_file_main_directly():
    result = _run("vdai/__main__.py", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage: vdai" in result.stdout


def test_run_module():
    result = _run("-m", "vdai", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage: vdai" in result.stdout


def test_run_py_launcher_help():
    result = _run("run.py", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage: vdai" in result.stdout


def test_run_py_from_other_directory(tmp_path):
    # Double-click simulation: invoked with an absolute path, cwd elsewhere.
    result = subprocess.run(
        [sys.executable, str(ROOT / "vdai" / "cli.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "usage: vdai" in result.stdout
