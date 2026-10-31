"""Offline onboarding and installation diagnostics for REED QR."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import webbrowser
from importlib import metadata, resources

from . import __version__

DOCUMENTATION = "https://github.com/evenRao/reed-qr#readme"
ISSUES = "https://github.com/evenRao/reed-qr/issues"
WELCOME = f"""REED QR {__version__} - Getting started

Encode and decode QR codes locally with Python and Rust.

  reed-qr guide          Read the step-by-step offline guide
  reed-qr doctor         Check the installation and a QR round trip
  reed-qr docs           Print the documentation link
  reed-qr docs --open    Open the documentation in your browser

Use `python -m reed_qr` in place of `reed-qr` if the command is not on PATH.
In a uv project, prefix commands with `uv run`.

Documentation: {DOCUMENTATION}
"""


def _doctor(*, as_json: bool) -> int:
    checks: list[dict[str, str]] = []

    def record(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    supported = platform.python_implementation() == "CPython" and (
        (3, 11) <= sys.version_info[:2] < (3, 16)
    )
    record(
        "python",
        "pass" if supported else "fail",
        f"{platform.python_implementation()} {platform.python_version()} ({sys.executable})",
    )
    record("platform", "info", platform.platform())
    try:
        installed = metadata.version("reed-qr")
    except metadata.PackageNotFoundError:
        record("package", "fail", "Package metadata missing; install reed-qr in this environment.")
    else:
        record(
            "package",
            "pass" if installed == __version__ else "fail",
            f"Installed distribution {installed}; Python API {__version__}",
        )

    try:
        from .api import decode_frame, decode_image, encode_text

        record("native", "pass", "Rust extension loaded.")
    except Exception as error:
        record("native", "fail", f"{type(error).__name__}: {error}")
    else:
        try:
            payload = "REED QR installation check"
            image = encode_text(payload)
            for results in (decode_image(image.to_png()), decode_frame(image.as_frame())):
                if len(results) != 1 or results[0].text != payload:
                    raise RuntimeError("Decoded text did not match the generated QR code.")
            record("roundtrip", "pass", "Generated a QR code and decoded its PNG and Gray8 frame.")
        except Exception as error:
            record("roundtrip", "fail", f"{type(error).__name__}: {error}")

    try:
        livekit = metadata.version("livekit")
    except metadata.PackageNotFoundError:
        record("livekit", "info", "Not installed (optional); base QR operations do not need it.")
    else:
        record("livekit", "info", f"RTC SDK {livekit} installed; room connectivity was not tested.")

    ok = all(check["status"] != "fail" for check in checks)
    if as_json:
        print(json.dumps({"ok": ok, "version": __version__, "checks": checks}, indent=2))
    else:
        print(f"REED QR {__version__} - Installation check\n")
        for check in checks:
            print(f"[{check['status'].upper()}] {check['name']}: {check['detail']}")
        print("\nInstallation check passed." if ok else "\nInstallation check failed.")
        if not ok:
            print("Check that pip and Python use the same environment and a compatible wheel.")
            print(f"Troubleshooting: {DOCUMENTATION}")
            print(f"Report a problem: {ISSUES}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """Print help, read the bundled guide, or check the local installation."""
    parser = argparse.ArgumentParser(
        prog="reed-qr",
        description="Local QR processing: getting started and installation checks.",
        epilog="Also available as: python -m reed_qr <command>",
    )
    parser.add_argument("--version", action="version", version=f"REED QR {__version__}")
    commands = parser.add_subparsers(dest="command", title="commands")
    commands.add_parser("guide", help="Read the bundled step-by-step guide (works offline)")
    doctor = commands.add_parser("doctor", help="Check the native extension and a QR round trip")
    doctor.add_argument("--json", action="store_true", help="Print a machine-readable report")
    docs = commands.add_parser("docs", help="Print the online documentation link")
    docs.add_argument("--open", action="store_true", help="Open the link in your default browser")
    args = parser.parse_args(argv)
    if args.command == "guide":
        print(resources.files("reed_qr").joinpath("GETTING_STARTED.md").read_text(encoding="utf-8"))
    elif args.command == "doctor":
        return _doctor(as_json=args.json)
    elif args.command == "docs":
        print(DOCUMENTATION, flush=True)
        if args.open:
            try:
                opened = webbrowser.open(DOCUMENTATION)
            except (webbrowser.Error, OSError):
                opened = False
            if not opened:
                print(
                    "Could not open a browser. Copy the link above into your browser.",
                    file=sys.stderr,
                )
                return 1
    else:
        print(WELCOME)
    return 0
