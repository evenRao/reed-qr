"""Check release provenance, matrix completeness, and distribution selection."""

import copy
import io
import tarfile
import tomllib
import zipfile

import pytest

from scripts import prepare_pypi_release as release

SHA = "a" * 40
REPOSITORY = "evenRao/reed-qr"
PROJECT = tomllib.loads((release.ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
VERSION = PROJECT["version"]
DIST = f"reed_qr-{VERSION}"


@pytest.fixture
def ci_metadata():
    run = {
        "id": 123,
        "status": "completed",
        "conclusion": "success",
        "path": ".github/workflows/checks.yml",
        "event": "push",
        "head_branch": "main",
        "head_sha": SHA,
        "head_repository": {"full_name": REPOSITORY},
    }
    artifacts = [
        {
            "id": index,
            "name": name,
            "expired": False,
            "digest": "sha256:" + "b" * 64,
            "workflow_run": {"id": 123, "head_sha": SHA},
        }
        for index, name in enumerate(release.EXPECTED_ARTIFACTS, 1)
    ]
    return run, artifacts


def test_selects_exact_release_matrix(ci_metadata):
    run, artifacts = ci_metadata
    artifacts.append({"name": "tests-windows-2025-py3.15", "id": 999})
    assert release.select_artifacts(run, artifacts, REPOSITORY, SHA) == list(range(1, 21))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("event", "pull_request"),
        ("head_branch", "feature"),
        ("head_sha", "c" * 40),
        ("path", ".github/workflows/publish.yml"),
        ("head_repository", {"full_name": "someone/reed-qr"}),
    ],
)
def test_rejects_untrusted_or_unverified_runs(ci_metadata, field, value):
    run, artifacts = ci_metadata
    run[field] = value
    with pytest.raises(ValueError, match="CI must be successful"):
        release.select_artifacts(run, artifacts, REPOSITORY, SHA)


@pytest.mark.parametrize(
    "defect", ["expired", "missing", "duplicate", "wrong_run", "wrong_commit", "bad_digest"]
)
def test_rejects_invalid_artifact_sets(ci_metadata, defect):
    run, artifacts = ci_metadata
    if defect == "expired":
        artifacts[0]["expired"] = True
    elif defect == "missing":
        artifacts.pop()
    elif defect == "duplicate":
        artifacts.append(copy.deepcopy(artifacts[0]))
    elif defect == "wrong_run":
        artifacts[0]["workflow_run"]["id"] = 456
    elif defect == "wrong_commit":
        artifacts[0]["workflow_run"]["head_sha"] = "c" * 40
    else:
        artifacts[0]["digest"] = "sha256:invalid"
    with pytest.raises(ValueError):
        release.select_artifacts(run, artifacts, REPOSITORY, SHA)


def test_check_run_paginates_and_writes_selected_ids(ci_metadata, monkeypatch, tmp_path):
    run, artifacts = ci_metadata
    calls = []
    responses = iter(
        [
            run,
            {"total_count": 20, "artifacts": artifacts[:10]},
            {"total_count": 20, "artifacts": artifacts[10:]},
        ]
    )

    def api(endpoint):
        calls.append(endpoint)
        return next(responses)

    monkeypatch.setattr(release, "github_api", api)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    release.check_run("123", VERSION)
    assert "page=2" in calls[-1]
    assert (tmp_path / "outputs").read_text() == (
        "artifact_ids=" + ",".join(map(str, range(1, 21))) + "\n"
    )


@pytest.mark.parametrize("run_id", ["0", "-1", "123; echo command", "$(command)"])
def test_run_id_requires_digits(run_id):
    with pytest.raises(ValueError, match="positive integer"):
        release.check_run(run_id, VERSION)


@pytest.fixture
def packages(tmp_path):
    artifacts = tmp_path / "input"
    tags = {
        "ubuntu-24.04": "manylinux_2_28_x86_64",
        "windows-2025": "win_amd64",
        "macos-15-intel": "macosx_10_12_x86_64",
        "macos-15": "macosx_11_0_arm64",
    }
    for name, (platform, minor) in release.EXPECTED_ARTIFACTS.items():
        directory = artifacts / name / "dist"
        directory.mkdir(parents=True)
        path = directory / f"{DIST}-cp3{minor}-cp3{minor}-{tags[platform]}.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{DIST}.dist-info/METADATA", f"Name: reed-qr\nVersion: {VERSION}\n\n")
        (directory / "unrelated.crate").write_bytes(b"not a Python distribution")
    source = artifacts / release.SOURCE_ARTIFACT / "dist" / f"{DIST}.tar.gz"
    data = f"Name: reed-qr\nVersion: {VERSION}\n\n".encode()
    with tarfile.open(source, "w:gz") as archive:
        info = tarfile.TarInfo(f"{DIST}/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return artifacts, tmp_path / "output"


def test_stages_only_twenty_wheels_and_one_source(packages):
    artifacts, output = packages
    release.stage(VERSION, artifacts, output)
    assert len(list(output.glob("*.whl"))) == 20
    assert len(list(output.glob("*.tar.gz"))) == 1
    assert len(list(output.iterdir())) == 21


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("missing_wheel", "Expected one wheel"),
        ("wrong_abi", "Wheel version, Python ABI, or platform mismatch"),
        ("wrong_metadata", "Distribution metadata must identify reed-qr"),
        ("missing_source", "Expected one source distribution"),
    ],
)
def test_stage_rejects_incomplete_or_mismatched_packages(packages, defect, message):
    artifacts, output = packages
    wheel = next(artifacts.rglob("*.whl"))
    if defect == "missing_wheel":
        wheel.unlink()
    elif defect == "wrong_abi":
        parts = wheel.name.split("-")
        parts[3] = "abi3"
        wheel.rename(wheel.with_name("-".join(parts)))
    elif defect == "wrong_metadata":
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                f"{DIST}.dist-info/METADATA", f"Name: different-package\nVersion: {VERSION}\n\n"
            )
    else:
        next(artifacts.rglob("*.tar.gz")).unlink()
    with pytest.raises(ValueError, match=message):
        release.stage(VERSION, artifacts, output)
    assert not output.exists()


def test_stage_refuses_to_mix_existing_packages(packages):
    artifacts, output = packages
    output.mkdir()
    (output / "old.whl").write_bytes(b"old")
    with pytest.raises(ValueError, match="must be empty"):
        release.stage(VERSION, artifacts, output)
    assert (output / "old.whl").read_bytes() == b"old"
