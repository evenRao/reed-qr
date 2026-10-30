"""Check license files and source boundaries in built distribution archives."""

import argparse
import json
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORIES = {"crates", "docs", "examples", "licenses", "python", "scripts", "src", "tests"}
SOURCE_FILES = {
    ".cargo_vcs_info.json",
    ".gitattributes",
    ".gitignore",
    ".python-version",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "Cargo.lock",
    "Cargo.toml",
    "Cargo.toml.orig",
    "LICENSE",
    "LICENSE_AUDIT.md",
    "PKG-INFO",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "THIRD_PARTY_NOTICES.txt",
    "pyproject.toml",
    "rust-toolchain.toml",
    "uv.lock",
}


def read_archive(path: Path) -> dict[str, bytes]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return {
                name: archive.read(name) for name in archive.namelist() if not name.endswith("/")
            }
    with tarfile.open(path, "r:gz") as archive:
        return {
            member.name: stream.read()
            for member in archive.getmembers()
            if member.isfile() and (stream := archive.extractfile(member)) is not None
        }


def require(files: dict[str, bytes], suffix: str, content: bytes | None = None) -> None:
    matches = [
        value for name, value in files.items() if name == suffix or name.endswith("/" + suffix)
    ]
    if not matches or not all(matches):
        raise ValueError(f"Missing or empty artifact file: {suffix}")
    if content is not None and not all(value == content for value in matches):
        raise ValueError(f"Stale artifact file: {suffix}")


def check_boundaries(files: dict[str, bytes], *, source: bool = False) -> None:
    for name in files:
        parts = set(Path(name).parts)
        if parts.intersection({".env", ".venv", ".cache", ".git", ".vscode", "livekit_web"}):
            raise ValueError(f"Private or application file in artifact: {name}")
        if source:
            relative = Path(name).parts[1:]
            if len(relative) == 1 and relative[0] not in SOURCE_FILES:
                raise ValueError(f"Unexpected source archive file: {name}")
            if len(relative) > 1 and relative[0] not in SOURCE_DIRECTORIES:
                raise ValueError(f"Unexpected source archive directory: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--crate", dest="rust_crate", type=Path)
    args = parser.parse_args()
    project_license = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["license"]
    wheels = sorted(args.dist.glob("*.whl"))
    sources = sorted(args.dist.glob("*.tar.gz"))
    if not wheels or not sources:
        raise SystemExit("Build a wheel and source distribution before checking artifacts.")

    rust_lock = tomllib.loads((ROOT / "Cargo.lock").read_text())
    rust_manifest = json.loads((ROOT / "licenses/manifest.json").read_text())
    expected = {
        (item["name"], item["version"]) for item in rust_lock["package"] if "source" in item
    }
    actual = {(item["name"], item["version"]) for item in rust_manifest["packages"]}
    if actual != expected:
        raise ValueError("Rust notice manifest does not match Cargo.lock")
    python_lock = tomllib.loads((ROOT / "uv.lock").read_text())
    python_manifest = json.loads((ROOT / "licenses/python-dependencies.json").read_text())
    if {(p["name"], p["version"]) for p in python_lock["package"]} != {
        (p["name"], p["version"]) for p in python_manifest["packages"]
    }:
        raise ValueError("Python license inventory does not match uv.lock")
    for package in python_manifest["packages"]:
        if package["name"] == "reed-qr" and package["license"] != project_license:
            raise ValueError("Project license inventory does not match pyproject.toml")

    for path in wheels + sources:
        files = read_archive(path)
        check_boundaries(files, source=path.suffix != ".whl")
        metadata_name = "METADATA" if path.suffix == ".whl" else "PKG-INFO"
        metadata_files = [
            value for name, value in files.items() if name.endswith("/" + metadata_name)
        ]
        if not metadata_files or any(
            BytesParser().parsebytes(value).get("License-Expression") != project_license
            for value in metadata_files
        ):
            raise ValueError(f"Artifact license metadata does not match {project_license}")
        require(files, "LICENSE", (ROOT / "LICENSE").read_bytes())
        require(files, "THIRD_PARTY_NOTICES.md", (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes())
        require(
            files,
            "licenses/RUST-THIRD-PARTY.txt",
            (ROOT / "licenses/RUST-THIRD-PARTY.txt").read_bytes(),
        )
        require(
            files, "licenses/RUST-STDLIB.html", (ROOT / "licenses/RUST-STDLIB.html").read_bytes()
        )
        require(files, "reed_qr/integrations/livekit.py")
        if path.suffix != ".whl":
            require(files, "uv.lock", (ROOT / "uv.lock").read_bytes())
            require(files, ".python-version", (ROOT / ".python-version").read_bytes())
            require(files, "crates/reed-qr-core/LICENSE")
            require(files, "crates/reed-qr-core/THIRD_PARTY_NOTICES.txt")
            require(files, "crates/reed-qr-python/LICENSE")
        print(f"Artifact licenses and boundaries passed: {path.name}")

    if args.rust_crate:
        files = read_archive(args.rust_crate)
        check_boundaries(files, source=True)
        crate_manifests = [value for name, value in files.items() if name.endswith("/Cargo.toml")]
        if not crate_manifests or any(
            tomllib.loads(value.decode())["package"]["license"] != project_license
            for value in crate_manifests
        ):
            raise ValueError("Rust crate license metadata does not match the project license")
        require(files, "LICENSE", (ROOT / "crates/reed-qr-core/LICENSE").read_bytes())
        require(
            files,
            "THIRD_PARTY_NOTICES.txt",
            (ROOT / "crates/reed-qr-core/THIRD_PARTY_NOTICES.txt").read_bytes(),
        )
        print(f"Rust crate licenses passed: {args.rust_crate.name}")


if __name__ == "__main__":
    main()
