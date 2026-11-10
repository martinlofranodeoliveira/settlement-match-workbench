"""Offline genuine sdist/wheel/rebuild checks. Run only on owner-admitted source."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


EXCLUDES = {"node_modules", "target", "dist", "build", ".build", "vendor", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".dart_tool", ".pub-cache", ".gradle", "_build", "deps", "obj"}

def sha(data):
    return hashlib.sha256(data).hexdigest()


def inventory(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source must be a regular directory")
    excludes = EXCLUDES
    entries = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in excludes)
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError("source symlink")
        for name in sorted(files):
            if name in excludes:
                continue
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("source non-regular file")
            data = path.read_bytes()
            entries.append({"path": path.relative_to(root).as_posix(), "size": len(data), "sha256": sha(data)})
    entries.sort(key=lambda row: row["path"])
    data = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {"sha256": sha(data), "files": entries}


def run(argv, **kwargs):
    subprocess.run(argv, check=True, **kwargs)


def check_wheel(path, rows):
    modules = {r["path"].removeprefix("src/"): r for r in rows if r["path"].startswith("src/")}
    licenses = {r["path"]: r for r in rows if r["path"] == "LICENSE" or r["path"].startswith("THIRD_PARTY/")}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise AssertionError("duplicate wheel members")
        for name in names:
            if name.startswith("/") or ".." in Path(name).parts or "\\" in name:
                raise AssertionError("unsafe wheel member")
            if name.endswith("/"):
                continue
            if name not in modules and ".dist-info/" not in name:
                raise AssertionError("unexpected wheel member")
        for name, row in modules.items():
            if sha(archive.read(name)) != row["sha256"]:
                raise AssertionError("module bytes differ")
        metadata = [n for n in names if n.count("/") == 1 and n.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise AssertionError("one package metadata root required")
        license_root = metadata[0].rsplit("/", 1)[0] + "/licenses/"
        for name, row in licenses.items():
            member = license_root + name
            if member not in names or sha(archive.read(member)) != row["sha256"]:
                raise AssertionError("notice bytes differ")
    return {name: row["sha256"] for name, row in modules.items()}


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/work/source")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/work/distributions")
    evidence = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/work/evidence")
    before = inventory(source)
    if out.is_symlink() or not out.is_dir() or any(out.iterdir()):
        raise ValueError("distribution output must be an empty regular directory")
    if evidence.is_symlink() or not evidence.is_dir() or any(evidence.iterdir()):
        raise ValueError("evidence output must be an empty regular directory")
    with tempfile.TemporaryDirectory(prefix="settlement-package-") as scratch:
        scratch = Path(scratch)
        build = scratch / "build-source"
        shutil.copytree(source, build, ignore=shutil.ignore_patterns(*EXCLUDES))
        run([sys.executable, "-I", "-B", "-c", "import setuptools.build_meta as b; b.build_sdist(" + repr(str(out)) + "); b.build_wheel(" + repr(str(out)) + ")"], cwd=build)
        wheel, = out.glob("*.whl")
        sdist, = out.glob("*.tar.gz")
        module_hashes = check_wheel(wheel, before["files"])
        unpack = scratch / "sdist"
        unpack.mkdir()
        with tarfile.open(sdist) as archive:
            members = archive.getmembers()
            tops = {m.name.split("/")[0] for m in members}
            if len(tops) != 1:
                raise AssertionError("sdist must have one root")
            top = next(iter(tops))
            for member in members:
                if member.name.startswith("/") or ".." in Path(member.name).parts or "\\" in member.name:
                    raise AssertionError("unsafe sdist member")
                if not member.isfile() and not member.isdir():
                    raise AssertionError("sdist links/special files are forbidden")
            for row in before["files"]:
                if sha(archive.extractfile(top + "/" + row["path"]).read()) != row["sha256"]:
                    raise AssertionError("source/sdist bytes differ")
            archive.extractall(unpack, filter="data")
        rebuilt = out / "rebuilt"
        rebuilt.mkdir()
        run([sys.executable, "-I", "-B", "-c", "import setuptools.build_meta as b; b.build_wheel(" + repr(str(rebuilt)) + ")"], cwd=unpack / top)
        rebuilt_wheel, = rebuilt.glob("*.whl")
        if check_wheel(rebuilt_wheel, before["files"]) != module_hashes:
            raise AssertionError("rebuilt module bytes differ")
        venv = scratch / "installed-sdk"
        run(["/usr/local/bin/python", "-I", "-B", "-m", "venv", str(venv)])
        python = str(venv / "bin/python")
        run([python, "-I", "-B", "-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--no-deps", str(rebuilt_wheel)])
        run([python, "-I", "-B", "-m", "pip", "check"])
        run([python, "-I", "-B", str(source / "scripts/run_tests.py"), str(source / "tests"), str(evidence / "unit-tests.json")], cwd=scratch)
    if inventory(source) != before:
        raise AssertionError("source changed during gate")
    proof = {
        "status": "PASS",
        "scope": "Installed SDK tests, source/sdist bytes, original/rebuilt wheel modules and every shipped license byte. Outside artifact consumer and hosted CI are separate gates.",
        "control_inventory": before,
        "module_hashes": module_hashes,
        "artifacts": {p.relative_to(out).as_posix(): sha(p.read_bytes()) for p in sorted(out.rglob("*")) if p.is_file()},
    }
    (evidence / "package-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "gate": "SDIST_WHEEL_REBUILD_AND_INSTALLED_SDK_TESTS", "source_sha256": before["sha256"]}))


if __name__ == "__main__":
    main()
