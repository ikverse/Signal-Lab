"""The updater: versions, checksums, the self-test gate, rollback and database upgrades."""

import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import config
import store
import updater


def make_zip(version, test_passes=True, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("VERSION", version + "\n")
        z.writestr("requirements.txt", "numpy>=2.0\nrequests>=2.31\n")
        z.writestr("tests/__init__.py", "")
        z.writestr("tests/test_ok.py", "import unittest\nclass T(unittest.TestCase):\n"
                                       f"    def test(self):\n        self.assertTrue({test_passes})\n")
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.text = body, status, body.decode(errors="ignore")

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    def __init__(self, files):
        self.files = files

    def get(self, url, **kw):
        return FakeResponse(self.files[url])


class Layout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.saved = (config.HOME, config.DATA_DIR)
        config.HOME, config.DATA_DIR = self.home, self.home / "data"
        (self.home / "versions" / "0.2.0").mkdir(parents=True)
        (self.home / "versions" / "0.2.0" / "requirements.txt").write_text("numpy>=2.0\nrequests>=2.31\n")
        (self.home / "current.txt").write_text("0.2.0")

    def tearDown(self):
        config.HOME, config.DATA_DIR = self.saved
        self.tmp.cleanup()

    def offer(self, version, body, sha=None):
        state = {"latest": version, "available": True, "zip_url": "zip", "sha_url": "sha", "size": len(body)}
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / "update.json").write_text(json.dumps(state))
        digest = sha or hashlib.sha256(body).hexdigest()
        return FakeSession({"zip": body, "sha": f"{digest}  signal-lab-v{version}.zip".encode()})

    def test_version_order(self):
        self.assertGreater(updater.parse_version("v0.10.0"), updater.parse_version("0.9.9"))
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))

    def test_good_download_is_kept(self):
        body = make_zip("0.2.1")
        path = updater.download(self.offer("0.2.1", body))
        self.assertEqual(path.read_bytes(), body)

    def test_bad_checksum_is_refused_and_deleted(self):
        body = make_zip("0.2.1")
        with self.assertRaises(updater.UpdateError):
            updater.download(self.offer("0.2.1", body, sha="0" * 64))
        self.assertFalse(updater.download_path("0.2.1").exists())
        self.assertFalse(updater.download_path("0.2.1").with_suffix(".part").exists())

    def test_install_switches_only_after_its_tests_pass(self):
        body = make_zip("0.2.1")
        updater.download(self.offer("0.2.1", body))
        self.assertEqual(updater.install(python=sys.executable), "0.2.1")
        self.assertEqual((self.home / "current.txt").read_text(), "0.2.1")
        self.assertEqual((self.home / "previous.txt").read_text(), "0.2.0")
        self.assertTrue((self.home / "versions" / "0.2.1" / "VERSION").exists())

    def test_failing_self_test_keeps_the_old_version(self):
        body = make_zip("0.2.1", test_passes=False)
        updater.download(self.offer("0.2.1", body))
        with self.assertRaises(updater.UpdateError):
            updater.install(python=sys.executable)
        self.assertEqual((self.home / "current.txt").read_text(), "0.2.0")
        self.assertFalse((self.home / "versions" / "0.2.1").exists())

    def test_rollback_swaps_back(self):
        body = make_zip("0.2.1")
        updater.download(self.offer("0.2.1", body))
        updater.install(python=sys.executable)
        self.assertEqual(updater.rollback(), "0.2.0")
        self.assertEqual((self.home / "current.txt").read_text(), "0.2.0")
        self.assertEqual((self.home / "previous.txt").read_text(), "0.2.1")

    def test_zip_cannot_write_outside_its_folder(self):
        body = make_zip("0.2.1", extra={"../evil.txt": "x"})
        updater.download(self.offer("0.2.1", body))
        with self.assertRaises(updater.UpdateError):
            updater.install(python=sys.executable)
        self.assertFalse((self.home / "versions" / "evil.txt").exists())
        self.assertEqual((self.home / "current.txt").read_text(), "0.2.0")


class DatabaseUpgrade(unittest.TestCase):
    def test_phase1_database_upgrades_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            old = sqlite3.connect(path)
            old.executescript(store.SCHEMA)            # the Phase 1 tables, user_version 0
            old.execute("INSERT INTO candles VALUES ('BTCUSDT','1d',1,1,1,1,1,1,1,2)")
            old.execute("INSERT INTO trades (run_id, variant) VALUES (1, 'donchian20_1d')")
            old.commit()
            old.close()
            conn = store.connect(path)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], store.SCHEMA_VERSION)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"live_trades", "live_exits", "alerts", "settings"} <= tables)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 1)
            conn.close()
            again = store.connect(path)                # running the upgrade twice changes nothing
            self.assertEqual(again.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 1)
            again.close()


if __name__ == "__main__":
    unittest.main()
