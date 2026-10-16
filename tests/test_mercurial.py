"""Real subprocess tests. Select the exact target with WIN32LFN_HG_COMMAND.

The Windows runner records a native-disabled baseline separately. These tests
also run on POSIX to verify registration, cleanup and ordinary hg behavior.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXTENSION = Path(__file__).resolve().parents[1] / "win32lfn.py"
SCRATCH = Path(os.environ.get("WIN32LFN_TEST_ROOT", str(EXTENSION.parent / ".tmp")))
DEFAULT_HG = str(Path(sys.executable).parent / ("hg.exe" if os.name == "nt" else "hg"))
HG = json.loads(os.environ.get("WIN32LFN_HG_COMMAND", json.dumps([DEFAULT_HG])))


def native(path):
    value = str(path)
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = (
            "\\\\?\\UNC\\" + value[2:]
            if value.startswith("\\\\")
            else "\\\\?\\" + os.path.abspath(value)
        )
    return value


def write(path, contents):
    os.makedirs(native(path.parent), exist_ok=True)
    with open(native(path), "wb") as stream:
        stream.write(contents)


def read(path):
    with open(native(path), "rb") as stream:
        return stream.read()


@unittest.skipUnless(
    Path(HG[0]).is_file() or shutil.which(HG[0]),
    "select Mercurial 7.0.1 with WIN32LFN_HG_COMMAND",
)
class MercurialTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.log = []
        self.env = os.environ.copy()
        self.env.update(
            HGRCPATH="",
            HGPLAIN="1",
            HGUSER="win32lfn tests <test@example.invalid>",
            HGENCODING="utf-8" if os.name != "nt" else "cp1252",
            HGDEMANDIMPORT="disable",
        )
        self.hg("init")

    def cleanup(self):
        shutil.rmtree(native(self.base))
        self.temp.cleanup()

    def hg(self, *args, cwd=None, enabled=True, expected=0, data=None):
        command = (
            HG
            + [
                "--config",
                "extensions.win32lfn=" + str(EXTENSION),
                "--config",
                "win32lfn.enabled=" + ("true" if enabled else "false"),
            ]
            + list(args)
        )
        result = subprocess.run(
            command,
            cwd=str(cwd or self.repo),
            env=self.env,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        self.log.append((command, result.returncode, result.stdout, result.stderr))
        self.assertEqual(
            result.returncode,
            expected,
            "\n%s\nstdout=%r\nstderr=%r" % (command, result.stdout, result.stderr),
        )
        self.assertNotIn(b"failed to import extension", result.stderr)
        self.assertNotIn(b"*** failed to", result.stderr)
        return result.stdout

    def test_exact_version_and_load(self):
        self.assertIn(b"7.0.1", self.hg("version", "-q"))
        self.assertIn(b"lfn", self.hg("help", "lfn"))
        self.hg("lfn", "--force", expected=255)

    def test_short_paths_disabled_and_enabled(self):
        path = self.repo / "ordinary.txt"
        write(path, b"base\n")
        self.hg("add", enabled=False)
        self.hg("commit", "-m", "base", enabled=False)
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.assertEqual(self.hg("status", enabled=enabled), b"")
                write(path, b"changed\n")
                self.assertIn(b"ordinary.txt", self.hg("status", "-m", enabled=enabled))
                self.hg("revert", "--all", "--no-backup", enabled=enabled)
                self.assertEqual(read(path), b"base\n")
                self.hg("update", "-r", "null", enabled=enabled)
                self.hg("update", "-r", "0", enabled=enabled)
                self.assertEqual(read(path), b"base\n")

    def test_long_workflow(self):
        relative = Path(*(["directory123456789"] * 18)) / "caf\u00e9.txt"
        longfile = self.repo / relative
        shortfile = self.repo / "short.txt"
        self.assertGreater(len(str(longfile)), 320)
        write(longfile, b"long base\n")
        write(shortfile, b"short base\n")
        self.hg("add")
        self.hg("commit", "-m", "base")
        self.assertEqual(self.hg("status"), b"")
        write(longfile, b"changed\n")
        self.assertIn(b"caf", self.hg("status", "-m"))
        self.hg("revert", "--all", "--no-backup")
        self.assertEqual(read(longfile), b"long base\n")
        self.hg("update", "-r", "null")
        self.assertFalse(os.path.exists(native(longfile)))
        self.hg("update", "-r", "0")
        self.assertEqual(read(longfile), b"long base\n")
        clone = self.base / "clone"
        self.hg("clone", str(self.repo), str(clone))
        self.assertEqual(read(clone / relative), b"long base\n")
        self.assertEqual(self.hg("status", cwd=clone), b"")
        archive = self.base / "archive"
        self.hg("archive", str(archive))
        self.assertEqual(read(archive / relative), b"long base\n")
        # Two heads modify separate files, requiring a real working-copy merge.
        write(longfile, b"left branch\n")
        self.hg("commit", "-m", "left")
        self.hg("update", "-r", "0")
        write(shortfile, b"right branch\n")
        self.hg("commit", "-m", "right")
        self.hg("merge", "-r", "1", "--tool", "internal:merge")
        self.assertEqual(read(longfile), b"left branch\n")
        self.assertEqual(read(shortfile), b"right branch\n")
        self.hg("commit", "-m", "merge")
        renamed = relative.with_name("renamed-\u00e9.txt")
        self.hg("rename", str(relative), str(renamed))
        self.assertEqual(read(self.repo / renamed), b"left branch\n")
        self.hg("commit", "-m", "rename")
        self.hg("remove", str(renamed))
        self.hg("commit", "-m", "remove")
        self.assertFalse(os.path.exists(native(self.repo / renamed)))
        self.assertEqual(self.hg("status"), b"")

    def test_cleanup_with_real_dirstate(self):
        directory = self.repo.joinpath(*(["directory123456789"] * 18))
        tracked = directory / "tracked.txt"
        untracked = directory / "untracked.txt"
        write(tracked, b"tracked\n")
        self.hg("add")
        self.hg("commit", "-m", "tracked")
        write(untracked, b"untracked\n")
        self.assertIn(b"tracked.txt", self.hg("lfn"))
        self.hg("--config", "ui.interactive=false", "lfn", "--clean", expected=1)
        self.assertEqual(read(untracked), b"untracked\n")
        self.hg(
            "--config",
            "ui.interactive=true",
            "lfn",
            "--clean",
            expected=1,
            data=b"y\n" * 100,
        )
        self.assertFalse(os.path.exists(native(untracked)))
        self.assertEqual(read(tracked), b"tracked\n")
        write(untracked, b"untracked again\n")
        self.hg("lfn", "--clean", "--force", expected=1)
        self.assertFalse(os.path.exists(native(untracked)))
        self.assertEqual(read(tracked), b"tracked\n")
        self.assertEqual(self.hg("status"), b"")

    def test_deep_repository_root_from_short_cwd(self):
        deep = self.base.joinpath(*(["deeprepo123456789"] * 19))
        self.assertGreater(len(str(deep)), 320)
        self.hg("init", str(deep))
        write(deep / "file.txt", b"deep root\n")
        self.hg("-R", str(deep), "add")
        self.hg("-R", str(deep), "commit", "-m", "deep")
        self.assertEqual(self.hg("-R", str(deep), "status"), b"")
        self.hg("-R", str(deep), "update", "-r", "null")
        self.hg("-R", str(deep), "update", "-r", "0")
        self.assertEqual(read(deep / "file.txt"), b"deep root\n")


if __name__ == "__main__":
    unittest.main()
