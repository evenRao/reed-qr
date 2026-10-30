"""Maintain dependency license inventories and Rust notice bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "crates/reed-qr-core"
LICENSE_NAME = re.compile(r"license|licence|copying|copyright|notice|unlicense", re.I)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def closure(package_id: str, nodes: dict, *, tests: bool = False) -> set[str]:
    found: set[str] = set()
    pending = [package_id]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        for dependency in nodes[current]["deps"]:
            if any(kind["kind"] != "dev" or tests for kind in dependency["dep_kinds"]):
                pending.append(dependency["pkg"])
    return found


def notice_files(directory: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in directory.rglob("*")
            if path.is_file()
            and len(path.relative_to(directory).parts) <= 4
            and LICENSE_NAME.search(path.name)
        ),
        key=lambda path: path.relative_to(directory).as_posix(),
    )


def copyrights(directory: Path) -> list[str]:
    found = set()
    for source in (directory / "src").rglob("*.rs"):
        header = source.read_text(encoding="utf-8", errors="replace")[:8192]
        for line in header.splitlines():
            text = line.strip().lstrip("/* ").strip()
            if re.match(r"copyright\b", text, re.I):
                found.add(text.rstrip("*/ "))
    return sorted(found)


def collect() -> tuple[dict, dict[str, str]]:
    output = subprocess.check_output(
        ["cargo", "metadata", "--locked", "--offline", "--format-version", "1"],
        cwd=ROOT,
    )
    metadata = json.loads(output)
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    core_id = next(p["id"] for p in metadata["packages"] if p["name"] == "reed-qr-core")
    binding_id = next(p["id"] for p in metadata["packages"] if p["name"] == "reed-qr-python")
    core = closure(core_id, nodes)
    binding = closure(binding_id, nodes)
    core_tests = closure(core_id, nodes, tests=True)
    checksums = {
        (package["name"], package["version"]): package.get("checksum")
        for package in tomllib.loads((ROOT / "Cargo.lock").read_text())["package"]
    }
    packages = []
    sections = {}
    for package in sorted(metadata["packages"], key=lambda item: (item["name"], item["version"])):
        if package["source"] is None:
            continue
        name, version = package["name"], package["version"]
        identity = f"{name}-{version}"
        directory = Path(package["manifest_path"]).parent
        evidence = []
        texts = []
        files = notice_files(directory)
        for path in files:
            data = path.read_bytes()
            relative = path.relative_to(directory).as_posix()
            evidence.append({"path": relative, "sha256": digest(data), "source": "released crate"})
            texts.append(f"--- {relative} ---\n{data.decode('utf-8-sig').rstrip()}\n")
        if not files:
            upstream = ROOT / "licenses/upstream" / identity
            provenance = json.loads((upstream / "provenance.json").read_text())
            for item in provenance["files"]:
                path = upstream / item["path"]
                data = path.read_bytes()
                if digest(data) != item["sha256"]:
                    raise ValueError(f"Upstream license hash mismatch: {path}")
                evidence.append(item)
                texts.append(f"--- {item['url']} ---\n{data.decode('utf-8-sig').rstrip()}\n")
        if not evidence:
            raise ValueError(f"No license evidence for {identity}")
        roles = []
        if package["id"] in core:
            roles.append("core")
        if package["id"] in binding:
            roles.append("binding")
        if package["id"] in core_tests - core:
            roles.append("core tests")
        entry = {
            "name": name,
            "version": version,
            "license": package["license"],
            "repository": package.get("repository"),
            "crate_checksum": checksums[(name, version)],
            "scope": roles,
            "notices": evidence,
        }
        packages.append(entry)
        copyright_lines = copyrights(directory)
        heading = f"{'=' * 72}\n{name} {version}\nLicense: {package['license']}\n"
        heading += "Source: https://crates.io/crates/" + name + "/" + version + "\n"
        if copyright_lines:
            heading += "\nSource copyright notices:\n" + "\n".join(copyright_lines) + "\n"
        sections[identity] = heading + "\n" + "\n".join(texts)
    inventory = {
        "scope": (
            "All resolved Cargo.lock targets, including build and test dependencies; "
            "not an exact linked-code inventory."
        ),
        "packages": packages,
    }
    return inventory, sections


def outputs() -> dict[Path, str]:
    inventory, sections = collect()
    sysroot = Path(subprocess.check_output(["rustc", "--print", "sysroot"], text=True).strip())
    stdlib_path = sysroot / "share/doc/rust/COPYRIGHT-library.html"
    stdlib = stdlib_path.read_text(encoding="utf-8")
    inventory["standard_library"] = {
        "toolchain": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "source": "share/doc/rust/COPYRIGHT-library.html in the pinned Rust distribution",
        "sha256": digest(stdlib.encode("utf-8")),
    }
    packages = inventory["packages"]
    introduction = (
        "REED QR: Rust dependency licenses and attribution\n\n"
        "License expressions retain upstream declarations. Full available license\n"
        "and notice texts follow. Entries include build, test and target-specific\n"
        "dependencies; listing a package does not imply it is linked on every target.\n\n"
    )
    bundle = introduction + "\n".join(sections.values())
    core_bundle = introduction + "\n".join(
        sections[f"{package['name']}-{package['version']}"]
        for package in packages
        if "core" in package["scope"] or "core tests" in package["scope"]
    )
    rows = [
        "# Rust dependencies\n",
        "Versions come from `Cargo.lock`. Scope includes all resolved targets; build",
        "dependencies are included in their consuming core/binding closure.\n",
        "Full texts: [Rust notices](../../licenses/RUST-THIRD-PARTY.txt).",
        "Checksums and source evidence: [manifest](../../licenses/manifest.json).\n",
        "| Package | Version | License declaration | Scope |",
        "| --- | --- | --- | --- |",
    ]
    for package in packages:
        rows.append(
            f"| {package['name']} | {package['version']} | {package['license']} | "
            + ", ".join(package["scope"])
            + " |"
        )
    return {
        ROOT / "licenses/RUST-THIRD-PARTY.txt": bundle,
        ROOT / "licenses/RUST-STDLIB.html": stdlib,
        ROOT / "licenses/manifest.json": json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
        CORE / "THIRD_PARTY_NOTICES.txt": core_bundle,
        ROOT / "docs/licenses/rust-dependencies.md": "\n".join(rows) + "\n",
        CORE / "LICENSE": (ROOT / "LICENSE").read_text(),
        ROOT / "crates/reed-qr-python/LICENSE": (ROOT / "LICENSE").read_text(),
    }


def python_scopes(packages: list[dict]) -> dict[tuple[str, str], set[str]]:
    project_name = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["name"]
    project = next(package for package in packages if package["name"] == project_name)
    by_name: dict[str, list[dict]] = {}
    for package in packages:
        by_name.setdefault(package["name"], []).append(package)
    scopes: dict[tuple[str, str], set[str]] = {}

    def walk(dependencies: list[dict], scope: str) -> None:
        pending = list(dependencies)
        seen = set()
        while pending:
            dependency = pending.pop()
            for package in by_name[dependency["name"]]:
                if dependency.get("version") and package["version"] != dependency["version"]:
                    continue
                key = package["name"], package["version"]
                if key in seen:
                    continue
                seen.add(key)
                scopes.setdefault(key, set()).add(scope)
                pending.extend(package.get("dependencies", []))

    for extra, dependencies in project.get("optional-dependencies", {}).items():
        walk(dependencies, "extra:" + extra)
    for group, dependencies in project.get("dev-dependencies", {}).items():
        walk(dependencies, "group:" + group)
    walk([{"name": "maturin"}], "build backend")
    scopes[(project["name"], project["version"])] = {"project"}
    return scopes


def python_outputs() -> dict[Path, str]:
    locked = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    scopes = python_scopes(locked)
    previous_path = ROOT / "licenses/python-dependencies.json"
    previous = {
        (package["name"], package["version"]): package
        for package in json.loads(previous_path.read_text())["packages"]
    }

    def canonical(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).lower()

    installed = {
        (canonical(distribution.metadata["Name"]), distribution.version): distribution
        for distribution in distributions()
    }
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    packages = []
    for package in locked:
        key = package["name"], package["version"]
        prior = previous.get(key)
        if package["name"] == project["name"]:
            record = {
                "name": key[0],
                "version": key[1],
                "license": project["license"],
                "evidence": "project manifest",
                "source": "pyproject.toml",
            }
        elif distribution := installed.get(key):
            expression = distribution.metadata.get("License-Expression")
            expression = expression or (prior["license"] if prior else None)
            if not expression:
                raise ValueError(f"Review the license text before adding Python dependency {key}")
            files = []
            for path in distribution.files or []:
                if LICENSE_NAME.search(str(path)):
                    location = Path(distribution.locate_file(path))
                    if location.is_file():
                        files.append(
                            {"path": path.as_posix(), "sha256": digest(location.read_bytes())}
                        )
            record = {
                "name": key[0],
                "version": key[1],
                "license": expression,
                "evidence": "installed Windows wheel metadata and supplied license files",
                "source": f"https://pypi.org/project/{key[0]}/{key[1]}/",
                "license_files": sorted(files, key=lambda item: item["path"]),
            }
        elif prior:
            record = dict(prior)
        else:
            raise ValueError(
                f"Install or review exact-version metadata for Python dependency {key}"
            )
        record["scope"] = sorted(scopes[key])
        packages.append(record)
    rows = [
        "# Python dependencies\n",
        "Every package/version entry in `uv.lock` is listed below. The base package has",
        "no Python runtime dependencies. Optional and development distributions retain",
        "their own licenses and native component notices.\n",
        "Evidence covers installed Windows wheels and previously reviewed exact-version",
        "metadata for alternatives not selected by the development interpreter.",
        "Version alternatives preserve compatibility with supported Python versions.",
        "Other platform binaries require their own review. See [scope](../../LICENSE_AUDIT.md).\n",
        "Source hashes: [Python inventory](../../licenses/python-dependencies.json).\n",
        "| Package | Version | Declared/reviewed license | Scope |",
        "| --- | --- | --- | --- |",
    ]
    for package in packages:
        rows.append(
            f"| {package['name']} | {package['version']} | {package['license']} | "
            + ", ".join(package["scope"])
            + " |"
        )
    return {
        previous_path: json.dumps({"packages": packages}, indent=2) + "\n",
        ROOT / "docs/licenses/python-dependencies.md": "\n".join(rows) + "\n",
    }


def check_python_inventory() -> None:
    locked = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    scopes = python_scopes(locked)
    packages = json.loads((ROOT / "licenses/python-dependencies.json").read_text())["packages"]
    if set(scopes) != {(package["name"], package["version"]) for package in packages}:
        raise ValueError("Python license inventory is stale; review and regenerate it")
    for package in packages:
        if set(package["scope"]) != scopes[(package["name"], package["version"])]:
            raise ValueError("Python dependency scopes are stale")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated notices are stale")
    parser.add_argument(
        "--python-inventory",
        action="store_true",
        help="Refresh reviewed Python metadata from the installed development environment",
    )
    arguments = parser.parse_args()
    stale = []
    generated = outputs()
    if arguments.python_inventory:
        generated.update(python_outputs())
    for path, text in generated.items():
        if arguments.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(path.relative_to(ROOT))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    if stale:
        raise SystemExit("Outdated license files: " + ", ".join(map(str, stale)))
    check_python_inventory()
    print(
        "Dependency license files are current."
        if arguments.check
        else "Dependency license files updated."
    )


if __name__ == "__main__":
    main()
