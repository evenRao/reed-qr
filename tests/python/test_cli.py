"""Exercise onboarding from installed packages and damaged native installations."""

import json
import subprocess
import sys

import pytest
import reed_qr
from reed_qr import cli


def test_module_welcome_and_quiet_import():
    welcome = subprocess.run(
        [sys.executable, "-I", "-m", "reed_qr"], capture_output=True, text=True, check=True
    )
    assert "reed-qr guide" in welcome.stdout
    assert "reed-qr doctor" in welcome.stdout
    assert not welcome.stderr
    imported = subprocess.run(
        [sys.executable, "-I", "-c", "import reed_qr"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert not imported.stdout and not imported.stderr


def test_offline_guide_and_version(capsys):
    assert cli.main(["guide"]) == 0
    guide = capsys.readouterr().out
    assert "order:12345 exact_bytes" in guide
    assert "asyncio.run(main())" in guide
    assert "LiveKit" in guide
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])
    assert exit_info.value.code == 0
    assert reed_qr.__version__ in capsys.readouterr().out


def test_doctor_checks_native_roundtrip_and_emits_json(capsys):
    assert cli.main(["doctor", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["native"]["status"] == "pass"
    assert checks["roundtrip"]["status"] == "pass"


def test_doctor_fails_on_distribution_version_mismatch(monkeypatch, capsys):
    monkeypatch.setattr(cli.metadata, "version", lambda name: "0.0.0")
    assert cli.main(["doctor", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert any(
        check["name"] == "package" and check["status"] == "fail" for check in report["checks"]
    )


@pytest.mark.parametrize("opens", [True, False, OSError("No browser available")])
def test_docs_browser_is_explicit_and_failure_keeps_link(monkeypatch, capsys, opens):
    calls = []

    def open_browser(url):
        calls.append(url)
        if isinstance(opens, Exception):
            raise opens
        return opens

    monkeypatch.setattr(cli.webbrowser, "open", open_browser)
    assert cli.main(["docs"]) == 0
    assert not calls
    assert cli.DOCUMENTATION in capsys.readouterr().out
    assert cli.main(["docs", "--open"]) == (0 if opens is True else 1)
    output = capsys.readouterr()
    assert cli.DOCUMENTATION in output.out
    assert calls == [cli.DOCUMENTATION]
    assert ("Could not open a browser" in output.err) == (opens is not True)


def test_help_and_diagnostics_survive_missing_native_extension():
    program = """
import importlib.abc
import sys

class BlockNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "reed_qr._native":
            raise ImportError("Native extension unavailable for this test")

sys.meta_path.insert(0, BlockNative())
from reed_qr.cli import main
assert main(["guide"]) == 0
assert main(["docs"]) == 0
assert main(["doctor", "--json"]) == 1
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program], capture_output=True, text=True, check=True
    )
    assert "Native extension unavailable for this test" in result.stdout
    assert not result.stderr


def test_public_exports_preserve_identity():
    for name in reed_qr.__all__:
        assert name in dir(reed_qr)
        assert getattr(reed_qr, name) is getattr(reed_qr, name)
    with pytest.raises(AttributeError):
        _ = reed_qr.missing_api
