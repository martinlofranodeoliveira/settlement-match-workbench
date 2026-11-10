"""Network preparation only: fetch the exact published build wheels by hash."""
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "wheelhouse"
MAX_WHEEL_BYTES = 16 * 1024 * 1024


def main():
    rows = json.loads((ROOT / "qualified-build-wheels.json").read_text())
    if DEST.is_symlink() or (DEST.exists() and not DEST.is_dir()):
        raise ValueError("wheelhouse must be a regular directory")
    DEST.mkdir(exist_ok=True)
    for row in rows:
        name = row["file"]
        if Path(name).name != name or not name.endswith(".whl"):
            raise ValueError("invalid qualified filename")
        parsed = urllib.parse.urlsplit(row["url"])
        if parsed.scheme != "https" or parsed.hostname != "files.pythonhosted.org":
            raise ValueError("unqualified download origin")
        path = DEST / name
        if path.is_symlink():
            raise ValueError("wheel cache cannot be a symlink")
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]:
            continue
        request = urllib.request.Request(row["url"], headers={"User-Agent": "settlement-match-build-preparation/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            final = urllib.parse.urlsplit(response.url)
            if final.scheme != "https" or final.hostname != "files.pythonhosted.org":
                raise ValueError("download redirected outside qualified origin")
            data = response.read(MAX_WHEEL_BYTES + 1)
        if len(data) > MAX_WHEEL_BYTES or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("qualified wheel hash/size mismatch")
        path.write_bytes(data)
    print("QUALIFIED_BUILD_WHEEL_BYTES_READY")


if __name__ == "__main__":
    main()
