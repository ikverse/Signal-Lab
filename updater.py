"""Updates from GitHub releases, the same idea as EGX Analyzer's updater.

It reads one public URL, releases/latest on ikverse/Signal-Lab, so no token lives on the phone.
Nothing installs on its own: Settings offers Download, then Install and restart.

Phone layout (SIGNAL_LAB_HOME, normally ~/signal-lab):

    current.txt            the version that runs, e.g. 0.2.1
    previous.txt           the version before it, for Roll back
    versions/0.2.1/        the code of each installed version
    data/                  the database and downloads; never touched by an update

An install unpacks the new version beside the old one and runs the whole test suite there
first. Only if every test passes does current.txt move to it. A download is accepted only when
its size and SHA-256 match what the release published.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import requests

import config

API = "https://api.github.com/repos/{repo}/releases/latest"


class UpdateError(Exception):
    pass


def parse_version(v):
    v = v.strip().lstrip("v")
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def home():
    return config.HOME


def installed_layout():
    h = home()
    return h is not None and (h / "current.txt").exists()


def current_version():
    h = home()
    if installed_layout():
        return (h / "current.txt").read_text().strip()
    return config.VERSION


def _state_path():
    return config.DATA_DIR / "update.json"


def load_state():
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(s):
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(_state_path(), json.dumps(s, indent=1))


def _write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


# --- Check ------------------------------------------------------------------------

def latest_release(session=requests):
    r = session.get(API.format(repo=config.GITHUB_REPO), timeout=30,
                    headers={"Accept": "application/vnd.github+json"})
    if r.status_code == 404:
        raise UpdateError("No release published yet")
    r.raise_for_status()
    rel = r.json()
    tag = rel["tag_name"]
    assets = {a["name"]: a for a in rel.get("assets", [])}
    zip_name = f"signal-lab-{tag}.zip"
    if zip_name not in assets or zip_name + ".sha256" not in assets:
        raise UpdateError(f"Release {tag} is missing its zip or checksum")
    return {
        "latest": tag.lstrip("v"), "notes": rel.get("body") or "",
        "zip_url": assets[zip_name]["browser_download_url"], "size": assets[zip_name]["size"],
        "sha_url": assets[zip_name + ".sha256"]["browser_download_url"],
        "published": rel.get("published_at"),
    }


def check(session=requests):
    s = load_state()
    s.update(current=current_version(), checked_at=int(time.time() * 1000), error=None)
    try:
        s.update(latest_release(session))
        s["available"] = parse_version(s["latest"]) > parse_version(s["current"])
    except (requests.RequestException, UpdateError, KeyError, ValueError) as e:
        s.update(available=False, error=str(e))
    _save_state(s)
    return s


# --- Download ---------------------------------------------------------------------

def download_path(version):
    return config.DATA_DIR / "updates" / f"signal-lab-v{version}.zip"


def download(session=requests, attempts=3):
    s = load_state()
    if not s.get("available"):
        raise UpdateError("No update to download")
    final = download_path(s["latest"])
    if final.exists():
        return final
    final.parent.mkdir(parents=True, exist_ok=True)
    part = final.with_suffix(".part")
    for _ in range(attempts):
        have = part.stat().st_size if part.exists() else 0
        try:
            with session.get(s["zip_url"], stream=True, timeout=60,
                             headers={"Range": f"bytes={have}-"} if have else {}) as r:
                if r.status_code == 200 and have:
                    have = 0          # the server ignored the range: start the file over
                elif r.status_code not in (200, 206):
                    raise UpdateError(f"Download refused: HTTP {r.status_code}")
                with open(part, "ab" if have else "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
        except requests.RequestException:
            continue
        if part.stat().st_size == s["size"]:
            break
    if not part.exists() or part.stat().st_size != s["size"]:
        raise UpdateError("Download incomplete; try again")
    expected = session.get(s["sha_url"], timeout=30).text.split()[0].lower()
    if sha256(part) != expected:
        part.unlink()
        raise UpdateError("Checksum mismatch: the download was damaged and has been deleted")
    os.replace(part, final)
    return final


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Install and roll back -----------------------------------------------------------

def safe_extract(zip_path, dest):
    """Unpack, refusing any entry that would land outside dest."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            target = (dest / name).resolve()
            if dest not in target.parents and target != dest:
                raise UpdateError(f"Unsafe path in update: {name}")
        z.extractall(dest)


def self_test(code_dir, python=sys.executable):
    """Run the new version's own tests against a scratch database inside its folder."""
    env = {k: v for k, v in os.environ.items() if k != "SIGNAL_LAB_HOME"}
    r = subprocess.run([python, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                       cwd=code_dir, env=env, capture_output=True, text=True,
                       timeout=config.SELF_TEST_TIMEOUT_S)
    return r.returncode == 0, (r.stdout + r.stderr)[-4000:]


def install(zip_path=None, version=None, python=sys.executable, run_tests=True):
    """Unpack beside the running version, self-test, then switch. Returns the new version."""
    if not installed_layout():
        raise UpdateError("Updates install only on the phone layout (see phone/setup.md)")
    h = home()
    s = load_state()
    version = version or s.get("latest")
    zip_path = Path(zip_path or download_path(version))
    if not zip_path.exists():
        raise UpdateError("Download the update first")
    versions = h / "versions"
    tmp = versions / f"{version}.installing"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        safe_extract(zip_path, tmp)
        packaged = (tmp / "VERSION").read_text().strip() if (tmp / "VERSION").exists() else ""
        if packaged != version:
            raise UpdateError(f"The zip says it is version {packaged or '?'}, expected {version}")
        cur_req = versions / current_version() / "requirements.txt"
        new_req = tmp / "requirements.txt"
        if new_req.exists() and (not cur_req.exists() or cur_req.read_text() != new_req.read_text()):
            r = subprocess.run([python, "-m", "pip", "install", "-r", str(new_req)],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                raise UpdateError("Installing the new version's requirements failed; staying on "
                                  f"{current_version()}\n{r.stderr[-1500:]}")
        if run_tests:
            ok, out = self_test(tmp, python)
            if not ok:
                raise UpdateError(f"The new version failed its own tests; staying on {current_version()}\n{out}")
        final = versions / version
        shutil.rmtree(final, ignore_errors=True)
        os.replace(tmp, final)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    old = current_version()
    _write_atomic(h / "previous.txt", old)
    _write_atomic(h / "current.txt", version)
    s.update(current=version, available=False, installed_at=int(time.time() * 1000))
    _save_state(s)
    return version


def rollback():
    if not installed_layout():
        raise UpdateError("Roll back works only on the phone layout")
    h = home()
    prev = (h / "previous.txt").read_text().strip() if (h / "previous.txt").exists() else ""
    if not prev or not (h / "versions" / prev).exists():
        raise UpdateError("No previous version to go back to")
    cur = current_version()
    _write_atomic(h / "current.txt", prev)
    _write_atomic(h / "previous.txt", cur)
    return prev


def summary():
    s = load_state()
    h = home()
    prev = (h / "previous.txt").read_text().strip() if installed_layout() and (h / "previous.txt").exists() else None
    return {
        "current": current_version(), "previous": prev, "installed_layout": installed_layout(),
        "latest": s.get("latest"), "available": bool(s.get("available")), "notes": s.get("notes", ""),
        "checked_at": s.get("checked_at"), "error": s.get("error"),
        "downloaded": bool(s.get("latest")) and download_path(s["latest"]).exists(),
    }
