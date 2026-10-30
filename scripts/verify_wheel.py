"""Verify one built wheel with pip, uv pip, and uv add in isolated environments."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path


def run(*args: str, cwd: Path) -> None:
    # The consumer must not inherit this repository's active environment or project.
    environment = os.environ.copy()
    for name in ("VIRTUAL_ENV", "UV_PROJECT", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    if os.name == "nt":
        # Keep unrelated SDK DLLs from masking missing wheel dependencies.
        base = Path(sys.base_prefix)
        windows = Path(environment.get("SystemRoot", r"C:\Windows"))
        paths = [Path(args[0]).parent, base, base / "DLLs", windows / "System32", windows]
        if uv := shutil.which("uv"):
            paths.append(Path(uv).parent)
        environment["PATH"] = os.pathsep.join(dict.fromkeys(map(str, paths)))
    subprocess.run(args, cwd=cwd, check=True, env=environment)


def interpreter(environment: Path) -> str:
    return str(environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, help="Select a wheel when dist/ contains several")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    requires_python = tomllib.loads((root / "pyproject.toml").read_text())["project"][
        "requires-python"
    ]
    wheels = [arguments.wheel] if arguments.wheel else list((root / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Select a wheel with --wheel, or keep one wheel in dist/")
    if not wheels[0].is_file() or wheels[0].suffix != ".whl":
        raise SystemExit("The selected wheel must be an existing .whl file")
    wheel = str(wheels[0].resolve())
    smoke = str(root / "scripts" / "wheel_smoke.py")
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv must be installed to validate all installation workflows")
    with tempfile.TemporaryDirectory(prefix="reed-qr-wheel-") as temporary:
        scratch = Path(temporary)
        cache = str(scratch / "uv-cache")
        pip_environment = scratch / "pip-environment"
        venv.EnvBuilder(with_pip=True).create(pip_environment)
        pip_python = interpreter(pip_environment)
        run(
            pip_python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--only-binary=:all:",
            wheel,
            cwd=scratch,
        )
        run(pip_python, "-I", smoke, cwd=scratch)

        uv_environment = scratch / "uv-environment"
        run(
            uv,
            "venv",
            "--python",
            sys.executable,
            "--no-python-downloads",
            str(uv_environment),
            cwd=scratch,
        )
        uv_python = interpreter(uv_environment)
        run(
            uv,
            "pip",
            "install",
            "--python",
            uv_python,
            "--offline",
            "--no-build",
            "--cache-dir",
            cache,
            wheel,
            cwd=scratch,
        )
        run(uv_python, "-I", smoke, cwd=scratch)

        project = scratch / "consumer"
        project.mkdir()
        (project / "pyproject.toml").write_text(
            '[project]\nname = "reed-qr-consumer"\nversion = "0.1.0"\n'
            f'requires-python = "{requires_python}"\ndependencies = []\n',
            encoding="utf-8",
        )
        run(
            uv,
            "add",
            "--python",
            sys.executable,
            "--offline",
            "--no-build",
            "--cache-dir",
            cache,
            wheel,
            cwd=project,
        )
        run(
            uv,
            "run",
            "--python",
            sys.executable,
            "--offline",
            "--cache-dir",
            cache,
            "python",
            "-I",
            smoke,
            cwd=project,
        )
        print("All three wheel installation workflows passed.")


if __name__ == "__main__":
    main()
