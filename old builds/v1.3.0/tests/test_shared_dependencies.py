"""Regression coverage for shared Windows dependency checks; never touches PATH or pip."""
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import shared_dependencies as dep


def test_nested_requirement_files_are_collected_without_duplicates(tmp_path):
    runtime = tmp_path / "requirements.txt"
    runtime.write_text("PySide6>=6.7,<7\nbeautifulsoup4>=4.12,<5\n", encoding="utf-8")
    build = tmp_path / "requirements-build.txt"
    build.write_text("-r requirements.txt\n-r requirements.txt\npytest>=8,<10\n", encoding="utf-8")
    found = dep.load_requirements(build)
    assert [req.name for req in found] == ["PySide6", "beautifulsoup4", "pytest"]


def test_unsatisfied_packages_reports_missing_and_wrong_versions(monkeypatch):
    from pip._vendor.packaging.requirements import Requirement

    def mock_version(name):
        if name == "present":
            return "1.4.2"
        if name == "old":
            return "2.0"
        raise dep.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(dep.metadata, "version", mock_version)
    result = dep.unsatisfied([
        Requirement("present>=1,<2"), Requirement("old>=3,<4"), Requirement("missing>=1")
    ])
    assert len(result) == 2
    assert "old: installed 2.0" in result[0]
    assert "missing: not installed" == result[1]


def test_satisfied_dependencies_never_call_pip_install(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("pytest>=8,<10\n", encoding="utf-8")
    monkeypatch.setattr(dep, "check_interpreter", lambda: None)
    monkeypatch.setattr(dep, "ensure_pip", lambda: None)
    monkeypatch.setattr(dep, "unsatisfied", lambda _: [])
    monkeypatch.setattr(dep, "add_scripts_to_user_path", lambda: None)
    monkeypatch.setattr(dep.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("pip install should not run when already satisfied")))
    monkeypatch.setattr(sys, "argv", ["shared_dependencies.py", str(req)])
    assert dep.main() == 0


def test_missing_dependencies_install_to_user_site_and_recheck(monkeypatch, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("pytest>=8,<10\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(dep, "check_interpreter", lambda: None)
    monkeypatch.setattr(dep, "ensure_pip", lambda: None)
    monkeypatch.setattr(dep, "unsatisfied", lambda _: ["pytest: not installed"])
    monkeypatch.setattr(dep, "add_scripts_to_user_path", lambda: None)
    monkeypatch.setattr(dep.subprocess, "run", lambda args, **kwargs: (calls.append(args), SimpleNamespace(returncode=0, stdout=""))[1])
    monkeypatch.setattr(sys, "argv", ["shared_dependencies.py", str(req)])
    assert dep.main() == 0
    assert calls[0][:6] == [sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check"]
    assert calls[0][-2:] == ["-r", str(req.resolve())]
    assert calls[1][-1] == "--verify-only"
