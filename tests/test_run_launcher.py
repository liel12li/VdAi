"""Tests for the root run.py launcher's dependency bootstrap (no real installs)."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

run = importlib.import_module("run")


def test_core_deps_present_skips_install(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "_pip_install", lambda *a, **k: calls.append(a) or True)
    monkeypatch.delenv("VDAI_NO_AUTOINSTALL", raising=False)
    # In the test environment all core deps are installed, so no pip call.
    run._ensure_dependencies()
    assert calls == []


def test_autoinstall_can_be_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "_pip_install", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr(run, "_missing", lambda deps: ["something>=1"])  # pretend missing
    monkeypatch.setenv("VDAI_NO_AUTOINSTALL", "1")
    run._ensure_dependencies()
    assert calls == []  # disabled → never installs


def test_missing_detects_absent_package():
    fake = {"definitely_not_installed_xyz": "definitely-not-installed-xyz>=1"}
    assert run._missing(fake) == ["definitely-not-installed-xyz>=1"]


def test_missing_empty_when_present():
    assert run._missing({"sys": "sys", "os": "os"}) == []


def test_ensure_halts_when_core_unfixable(monkeypatch):
    monkeypatch.delenv("VDAI_NO_AUTOINSTALL", raising=False)
    monkeypatch.setattr(run, "_missing", lambda deps: ["uvicorn>=0.29"])  # always missing
    monkeypatch.setattr(run, "_pip_install", lambda *a, **k: False)  # installs fail

    halted = {}
    def fake_halt(msg):
        halted["msg"] = msg
        raise SystemExit(1)
    monkeypatch.setattr(run, "_halt", fake_halt)

    with pytest.raises(SystemExit):
        run._ensure_dependencies()
    assert "uvicorn" in halted["msg"]
    assert "Python 3.12" in halted["msg"]


def test_requirements_signature_changes_with_optional(monkeypatch):
    sig1 = run._requirements_signature()
    monkeypatch.setitem(run.OPTIONAL_DEPS, "newpkg", "newpkg>=1.0")
    sig2 = run._requirements_signature()
    assert sig1 != sig2  # adding a dependency changes the fingerprint


def test_matching_stamp_skips_install(tmp_path, monkeypatch):
    monkeypatch.delenv("VDAI_NO_AUTOINSTALL", raising=False)
    stamp = tmp_path / ".deps_stamp"
    monkeypatch.setattr(run, "_deps_stamp_path", lambda: str(stamp))
    monkeypatch.setattr(run, "_missing", lambda deps: [])  # all present
    sig = run._requirements_signature()
    stamp.write_text(sig)

    calls = []
    monkeypatch.setattr(run, "_pip_install", lambda *a, **k: calls.append(a) or True)
    run._ensure_dependencies()
    assert calls == []  # up to date → no pip


def test_stale_stamp_installs_missing_optional(tmp_path, monkeypatch):
    monkeypatch.delenv("VDAI_NO_AUTOINSTALL", raising=False)
    stamp = tmp_path / ".deps_stamp"
    monkeypatch.setattr(run, "_deps_stamp_path", lambda: str(stamp))
    stamp.write_text("OLD-SIGNATURE")
    # core present, one optional missing
    monkeypatch.setattr(run, "_missing",
                        lambda deps: [] if deps is run.CORE_DEPS else ["browser_cookie3>=0.19"])
    calls = []
    monkeypatch.setattr(run, "_pip_install", lambda reqs, **k: calls.append(reqs) or True)
    run._ensure_dependencies()
    assert any("browser_cookie3>=0.19" in c for c in calls)
    assert stamp.read_text() == run._requirements_signature()  # re-stamped
