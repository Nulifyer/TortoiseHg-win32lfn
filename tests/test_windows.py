"""Real Windows API tests, including Mercurial's delete-sharing contract."""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import win32lfn as lfn

ROOT = Path(
    os.environ.get(
        "WIN32LFN_TEST_ROOT", str(Path(__file__).resolve().parents[1] / ".tmp")
    )
)


@unittest.skipUnless(os.name == "nt", "requires real Windows")
class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(lfn.install())
        self.addCleanup(lfn.uninstall)
        ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.directory = os.path.join(self.root, *(["directory123456789"] * 18))
        os.makedirs(self.directory)
        self.file = os.path.join(self.directory, "caf\u00e9.txt")

    def test_python_filesystem_keyword_pathlike_and_descriptors(self):
        with open(file=Path(self.file), mode="wb") as stream:
            stream.write(b"contents")
            self.assertEqual(os.stat(stream.fileno()).st_size, 0)
        self.assertEqual(os.stat(path=Path(self.file)).st_size, 8)
        fd = os.open(path=self.file, flags=os.O_RDONLY | os.O_BINARY)
        try:
            self.assertEqual(os.read(fd, 100), b"contents")
            self.assertEqual(os.stat(fd).st_size, 8)
        finally:
            os.close(fd)
        destination = self.file + ".renamed"
        os.rename(src=self.file, dst=destination)
        os.utime(destination, ns=(1000000000000000000, 1000000000000000000))
        os.chmod(destination, stat.S_IREAD | stat.S_IWRITE)
        os.link(destination, self.file)
        self.assertTrue(os.path.samefile(destination, self.file))
        os.unlink(self.file)
        os.remove(destination)
        with self.assertRaises(FileNotFoundError):
            os.stat(self.file)

    def test_bytes_and_scandir_preserve_names_and_path_spelling(self):
        with os.scandir(Path(self.root)) as entries:
            self.assertIsInstance(next(entries), os.DirEntry)
        value = lfn._encode(self.file)
        self.assertIn(b"\xe9", value)
        with open(value, "wb") as stream:
            stream.write(b"non UTF-8 bytes")
        directory = lfn._encode(self.directory)
        self.assertIn(b"caf\xe9.txt", os.listdir(directory))
        with os.scandir(directory) as entries:
            entry = next(entries)
            self.assertEqual(entry.name, b"caf\xe9.txt")
            self.assertEqual(entry.path, value)
            self.assertEqual(os.fspath(entry), value)
            self.assertTrue(entry.is_file())
            self.assertEqual(entry.stat().st_size, 15)

    def test_mercurial_listdir_contract_and_error_propagation(self):
        from mercurial import util

        with open(self.file, "wb") as stream:
            stream.write(b"x")
        os.mkdir(os.path.join(self.directory, "skip"))
        entries = util.listdir(lfn._encode(self.directory), stat=True)
        self.assertEqual([e[0] for e in entries], [b"caf\xe9.txt", b"skip"])
        self.assertTrue(stat.S_ISREG(entries[0][1]))
        self.assertEqual(entries[0][2].st_size, 1)
        self.assertEqual(util.listdir(lfn._encode(self.directory), skip=b"skip"), [])
        with self.assertRaises(FileNotFoundError):
            util.listdir(lfn._encode(self.directory + "-missing"))

    def test_open_reader_allows_rename_unlink_and_recreate(self):
        from mercurial import util

        name = lfn._encode(self.file)
        with util.posixfile(name, b"wb") as stream:
            stream.write(b"old revision")
        with util.posixfile(name, b"rb") as reader:
            util.rename(name, name + b".moved")
            util.unlink(name + b".moved")
            with util.posixfile(name, b"wb") as writer:
                writer.write(b"new revision")
            self.assertEqual(reader.read(), b"old revision")
        with util.posixfile(name, b"rb") as stream:
            self.assertEqual(stream.read(), b"new revision")
        self.assertEqual(os.stat(self.file).st_size, 12)

    def test_readonly_unlink_and_hardlinks_use_wide_apis(self):
        from mercurial import util

        name = lfn._encode(self.file)
        with util.posixfile(name, b"wb") as stream:
            stream.write(b"content")
        second = name + b".linked"
        util.oslink(name, second)
        self.assertEqual(util.nlinks(name), 2)
        self.assertTrue(util.samefile(name, second))
        self.assertTrue(util.samedevice(name, second))
        self.assertIsNotNone(util.getfstype(name))
        os.chmod(name, stat.S_IREAD)
        try:
            util.unlink(name)
        finally:
            os.chmod(second, stat.S_IWRITE | stat.S_IREAD)
        self.assertFalse(os.path.exists(name))
        self.assertTrue(os.path.isfile(second))

    def test_posixfile_append_mixed_modes_and_invalid_mode(self):
        from mercurial import util

        name = lfn._encode(self.file)
        with util.posixfile(name, b"wb") as stream:
            stream.write(b"abc")
        with util.posixfile(name, b"ab") as stream:
            self.assertEqual(stream.tell(), 3)
            stream.write(b"d")
        with util.posixfile(name, b"r+b") as stream:
            self.assertEqual(stream.read(1), b"a")
            stream.write(b"B")
            stream.seek(0)
            self.assertEqual(stream.read(), b"aBcd")
        with self.assertRaises(ValueError):
            util.posixfile(name, b"wwb")
        with self.assertRaises(TypeError):
            util.posixfile(name, b"wb", buffering="invalid")
        with open(name, "rb") as stream:
            self.assertEqual(stream.read(), b"aBcd")
        with self.assertRaises(ValueError):
            util.posixfile(name, b"r", buffering=0)

    def test_relative_paths_use_actual_current_directory(self):
        old = os.getcwd()
        os.chdir(self.root)
        try:
            relative = os.path.relpath(self.file, self.root)
            with open(relative, "wb") as stream:
                stream.write(b"relative")
            self.assertEqual(os.stat(relative).st_size, 8)
            self.assertEqual(os.getcwd(), self.root)
            drive_relative = os.path.splitdrive(self.root)[0] + relative
            self.assertEqual(os.stat(drive_relative).st_size, 8)
        finally:
            os.chdir(old)

    def test_long_current_directory_and_null_device(self):
        previous = os.getcwd()
        try:
            try:
                os.chdir(lfn.extended_path(self.directory))
            except OSError as exc:
                if getattr(exc, "winerror", None) != 206:
                    raise
                self.assertEqual(os.getcwd(), previous)
                self.skipTest(
                    "native long current directory requires process/Windows opt-in; no chdir emulation"
                )
            with open("relative.txt", "wb") as stream:
                stream.write(b"actual current directory")
            with open("relative.txt", "rb") as stream:
                self.assertEqual(stream.read(), b"actual current directory")
            fd = os.open(os.devnull, os.O_RDWR)
            os.close(fd)
        finally:
            os.chdir(previous)

    def test_unrepresentable_unicode_is_not_aliased(self):
        filename = os.path.join(self.directory, "unicode-\u8cc7\u6599-\U0001f600.txt")
        with open(filename, "wb") as stream:
            stream.write(b"unicode")
        with open(filename, "rb") as stream:
            self.assertEqual(stream.read(), b"unicode")
        from mercurial import util

        with self.assertRaises((UnicodeEncodeError, lfn.error.Abort)):
            util.listdir(lfn._encode(self.directory))
        with self.assertRaises(lfn.error.Abort):
            lfn._scan(lfn._encode(self.root))

    def test_directory_handle_operations_remain_unsupported(self):
        with self.assertRaises((NotImplementedError, TypeError)):
            os.stat(self.file, dir_fd=123)

    def test_cleanup_protects_case_aliases_and_readonly_failures(self):
        import contextlib
        from unittest import mock

        from test_cleanup import UI

        with open(self.file, "wb") as stream:
            stream.write(b"tracked")
        repo = mock.Mock(root=lfn._encode(self.root))
        repo.wlock.side_effect = contextlib.nullcontext
        repo.dirstate = {
            lfn._encode(os.path.relpath(self.file, self.root).upper()).replace(
                b"\\", b"/"
            ): object()
        }
        self.assertEqual(lfn.lfn(UI(), repo, clean=True, force=True), 1)
        self.assertTrue(os.path.isfile(self.file))
        repo.dirstate = {}
        first = os.path.join(self.directory, "0-readonly.txt")
        second = os.path.join(self.directory, "1-preserve.txt")
        for path in (first, second):
            with open(path, "wb") as stream:
                stream.write(b"preserve")
        os.chmod(first, stat.S_IREAD)
        try:
            with self.assertRaises(PermissionError):
                lfn.lfn(UI(), repo, clean=True, force=True)
            self.assertTrue(os.path.isfile(first))
            self.assertTrue(os.path.isfile(second))
            self.assertTrue(os.path.isfile(self.file))
        finally:
            os.chmod(first, stat.S_IREAD | stat.S_IWRITE)

    def test_junction_cleanup_does_not_touch_target(self):
        import contextlib
        from unittest import mock

        from test_cleanup import UI

        target = os.path.join(self.root, "target")
        os.mkdir(target)
        with open(os.path.join(target, "sentinel"), "wb") as stream:
            stream.write(b"preserved")
        # mklink itself needs an extended destination at the command boundary.
        link = os.path.join(self.directory, "junction")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", lfn.extended_path(link), target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        repo = mock.Mock(root=lfn._encode(self.root), dirstate={})
        repo.wlock.side_effect = contextlib.nullcontext
        ui = UI()
        self.assertEqual(lfn.lfn(ui, repo, clean=True, force=True), 1)
        self.assertTrue(os.path.isfile(os.path.join(target, "sentinel")))
        self.assertTrue(os.path.isdir(link))
        os.rmdir(link)


if __name__ == "__main__":
    unittest.main()
