"""Select and stage the complete Python release from a verified CI run."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {
    "ubuntu-24.04": r"manylinux_2_28_x86_64",
    "windows-2025": r"win_amd64",
    "macos-15-intel": r"macosx_[0-9]+_[0-9]+_x86_64",
    "macos-15": r"macosx_[0-9]+_[0-9]+_arm64",
}
PYTHON_MINORS = range(11, 16)
EXPECTED_ARTIFACTS = {
    f"packages-{platform}-py3.{minor}": (platform, minor)
    for platform in PLATFORMS
    for minor in PYTHON_MINORS
}
SOURCE_ARTIFACT = "packages-ubuntu-24.04-py3.15"


def validate_version(version: str) -> None:
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("Use a stable release version such as 0.1.0.")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    workspace = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    if not (
        project["project"]["name"] == "reed-qr"
        and project["project"]["version"] == workspace["workspace"]["package"]["version"] == version
    ):
        raise ValueError("Release version must match the Python project and Rust workspace.")


def select_artifacts(run: dict, artifacts: list[dict], repository: str, sha: str) -> list[int]:
    if not (
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("path") == ".github/workflows/checks.yml"
        and run.get("event") in {"push", "workflow_dispatch"}
        and run.get("head_branch") == "main"
        and run.get("head_sha") == sha
        and run.get("head_repository", {}).get("full_name", "").casefold() == repository.casefold()
    ):
        raise ValueError("CI must be successful on main in this repository at the release commit.")
    selected = []
    for name in EXPECTED_ARTIFACTS:
        matches = [artifact for artifact in artifacts if artifact.get("name") == name]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one CI artifact named {name}.")
        artifact = matches[0]
        provenance = artifact.get("workflow_run", {})
        if (
            artifact.get("expired") is not False
            or type(artifact.get("id")) is not int
            or artifact["id"] <= 0
            or provenance.get("id") != run.get("id")
            or provenance.get("head_sha") != sha
            or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest", "")) is None
        ):
            raise ValueError(f"Expired artifact or invalid commit/digest metadata: {name}")
        selected.append(artifact["id"])
    return selected


def github_api(endpoint: str) -> dict:
    return json.loads(subprocess.check_output(["gh", "api", endpoint], text=True))


def check_run(run_id: str, version: str) -> None:
    validate_version(version)
    if re.fullmatch(r"[1-9][0-9]*", run_id) is None:
        raise ValueError("CI run ID must be a positive integer.")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Run this workflow from main.")
    repository = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["GITHUB_SHA"]
    endpoint = f"repos/{repository}/actions/runs/{run_id}"
    run = github_api(endpoint)
    if run.get("id") != int(run_id):
        raise ValueError("CI run response does not match the requested run ID.")
    artifacts = []
    page = 1
    while True:
        response = github_api(f"{endpoint}/artifacts?per_page=100&page={page}")
        artifacts.extend(response["artifacts"])
        if len(artifacts) >= response["total_count"]:
            break
        if not response["artifacts"]:
            raise ValueError("Incomplete CI artifact listing.")
        page += 1
    identifiers = select_artifacts(run, artifacts, repository, sha)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"artifact_ids={','.join(map(str, identifiers))}\n")
    print(f"Selected {len(identifiers)} CI artifacts from run {run_id}, commit {sha}.")


def check_metadata(data: bytes, version: str) -> None:
    metadata = BytesParser().parsebytes(data)
    if metadata.get_all("Name") != ["reed-qr"] or metadata.get_all("Version") != [version]:
        raise ValueError("Distribution metadata must identify reed-qr at the release version.")


def stage(version: str, artifacts: Path, output: Path) -> None:
    validate_version(version)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Release output directory must be empty.")
    selected = []
    for name, (platform, minor) in EXPECTED_ARTIFACTS.items():
        wheels = list((artifacts / name).rglob("*.whl"))
        if len(wheels) != 1:
            raise ValueError(f"Expected one wheel in {name}.")
        wheel = wheels[0]
        pattern = rf"reed_qr-{re.escape(version)}-cp3{minor}-cp3{minor}-{PLATFORMS[platform]}\.whl"
        if re.fullmatch(pattern, wheel.name) is None:
            raise ValueError(f"Wheel version, Python ABI, or platform mismatch: {wheel.name}")
        with zipfile.ZipFile(wheel) as archive:
            metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError(f"Expected one wheel metadata file: {wheel.name}")
            check_metadata(archive.read(metadata[0]), version)
        selected.append(wheel)
    sources = list((artifacts / SOURCE_ARTIFACT).rglob("*.tar.gz"))
    if len(sources) != 1 or sources[0].name != f"reed_qr-{version}.tar.gz":
        raise ValueError("Expected one source distribution from the canonical Linux artifact.")
    with tarfile.open(sources[0], "r:gz") as archive:
        metadata = archive.extractfile(f"reed_qr-{version}/PKG-INFO")
        if metadata is None:
            raise ValueError("Source distribution metadata is missing.")
        check_metadata(metadata.read(), version)
    selected.append(sources[0])
    if len({path.name for path in selected}) != len(selected):
        raise ValueError("Duplicate release filenames.")
    output.mkdir(parents=True, exist_ok=True)
    summary = [
        f"## PyPI release {version}\n",
        f"Commit: `{os.environ.get('GITHUB_SHA', 'local')}`\n",
    ]
    summary.extend(
        ["20 wheels and one source distribution.\n", "| File | SHA-256 |", "| --- | --- |"]
    )
    for path in selected:
        destination = output / path.name
        shutil.copyfile(path, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        summary.append(f"| `{path.name}` | `{digest}` |")
    if report := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(report).open("a", encoding="utf-8") as stream:
            stream.write("\n".join(summary) + "\n")
    print(f"Staged {len(selected)} distributions in {output}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-run", help="Verify CI provenance and select artifact IDs")
    check.add_argument("--run-id", required=True)
    check.add_argument("--version", required=True)
    assemble = commands.add_parser("stage", help="Validate and stage the complete release")
    assemble.add_argument("--version", required=True)
    assemble.add_argument("--artifacts", type=Path, required=True)
    assemble.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check-run":
        check_run(args.run_id, args.version)
    else:
        stage(args.version, args.artifacts, args.out)


if __name__ == "__main__":
    main()
