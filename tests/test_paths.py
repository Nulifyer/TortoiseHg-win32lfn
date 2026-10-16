import errno
import ntpath
import sys
import unittest
from pathlib import PureWindowsPath
from unittest import mock

import win32lfn as lfn


def resolve(path):
    drive, tail = ntpath.splitdrive(path.replace("/", "\\"))
    if drive.startswith("\\\\"):
        return ntpath.normpath(path)
    if drive:
        return ntpath.normpath(
            drive + (tail if tail.startswith("\\") else "\\perdrive\\" + tail)
        )
    return ntpath.normpath(("C:" if tail.startswith("\\") else "C:\\work\\") + tail)


class PathTests(unittest.TestCase):
    def setUp(self):
        self.abspath = mock.patch.object(lfn.ntpath, "abspath", side_effect=resolve)
        self.abspath.start()
        self.addCleanup(self.abspath.stop)

    def test_namespace_conversion(self):
        tail = "\\".join(["abcdefghij"] * 28)
        cases = [
            ("C:\\" + tail, "\\\\?\\C:\\" + tail),
            ("C:relative\\" + tail, "\\\\?\\C:\\perdrive\\relative\\" + tail),
            ("D:relative\\" + tail, "\\\\?\\D:\\perdrive\\relative\\" + tail),
            ("relative\\" + tail, "\\\\?\\C:\\work\\relative\\" + tail),
            ("\\rooted\\" + tail, "\\\\?\\C:\\rooted\\" + tail),
            ("\\\\server\\share\\" + tail, "\\\\?\\UNC\\server\\share\\" + tail),
            ("C:/a/./b/../" + tail.replace("\\", "/"), "\\\\?\\C:\\a\\" + tail),
        ]
        for value, expected in cases:
            for convert in (lambda s: s, lambda s: s.encode("ascii")):
                with self.subTest(value=value, type=convert):
                    self.assertEqual(
                        lfn.extended_path(convert(value)), convert(expected)
                    )

    def test_long_unc_root(self):
        root = "\\\\server\\" + "share" * 60
        self.assertEqual(lfn.extended_path(root), "\\\\?\\UNC\\" + root[2:])
        with self.assertRaises(OSError):
            lfn.extended_path(root + " ")

    def test_opaque_or_short_inputs(self):
        for value in (
            "",
            b"",
            ".",
            "..",
            "C:",
            "C:\\",
            "\\\\server\\share\\",
            "NUL",
            "nul.txt",
            "C:\\NUL",
            "\\\\?\\C:\\a/../b",
            "\\\\.\\pipe\\" + "x" * 300,
            "\\??\\C:\\" + "x" * 300,
            "x\0" + "y" * 300,
            3,
            None,
            object(),
        ):
            with self.subTest(value=value):
                self.assertIs(lfn.extended_path(value), value)

    def test_device_names_and_relative_paths_under_extended_cwd(self):
        cwd = "\\\\?\\C:\\" + "directory\\" * 30
        with mock.patch.object(ntpath, "abspath", side_effect=lambda path: cwd + path):
            for device in ("NUL", "NUL.txt", "con", "COM1", "LPT9"):
                self.assertEqual(lfn.extended_path(device), device)
            self.assertEqual(lfn.extended_path("file.txt"), cwd + "file.txt")

    def test_pathlike(self):
        path = PureWindowsPath("C:\\" + "\\".join(["abcdefghij"] * 28))
        self.assertEqual(lfn.extended_path(path), "\\\\?\\" + str(path))

        class BytesPath:
            def __fspath__(self):
                return b"C:\\" + b"a\\" * 150 + b"x"

        self.assertIsInstance(lfn.extended_path(BytesPath()), bytes)

    def test_boundary_counts_utf16_units(self):
        for length in (1, 247, 248, 249, 259, 260, 1000, 32000):
            path = "C:\\" + "a" * (length - 3) if length >= 3 else "x"
            with self.subTest(length=length):
                result = lfn.extended_path(path)
                self.assertEqual(result.startswith("\\\\?\\"), length >= 248)
        path = "C:\\" + "\U0001f600" * 123
        self.assertTrue(lfn.extended_path(path).startswith("\\\\?\\"))

    def test_reject_ambiguous_long_DOS_names(self):
        base = "C:\\" + "directory\\" * 28
        for leaf in (
            "NUL",
            "nul.txt",
            "CON",
            "com1",
            "LPT9.dat",
            "COM\u00b9",
            "tail.",
            "tail ",
            "bad:name",
            "bad?name",
            "bad*name",
        ):
            with self.subTest(leaf=leaf), self.assertRaises(OSError) as raised:
                lfn.extended_path(base + leaf)
            self.assertEqual(raised.exception.errno, errno.EINVAL)

    def test_filesystem_bytes_are_not_assumed_utf8(self):
        for codec, name in [
            ("cp1255", "\u05d0\u05d4\u05e8\u05d5\u05df"),
            ("cp1252", "caf\u00e9"),
            ("cp932", "\u8868"),
        ]:
            value = ("C:\\" + "directory\\" * 28 + name).encode(codec)
            with (
                self.subTest(codec=codec),
                mock.patch.object(sys, "getfilesystemencoding", return_value=codec),
            ):
                self.assertEqual(lfn.extended_path(value), b"\\\\?\\" + value)

    def test_invalid_bytes_fail_without_replacement(self):
        with mock.patch.object(sys, "getfilesystemencoding", return_value="cp932"):
            with self.assertRaises(UnicodeDecodeError):
                lfn.extended_path(b"C:\\" + b"dir\\" * 80 + b"\x81")

    def test_resolution_errors_propagate(self):
        with mock.patch.object(
            ntpath, "abspath", side_effect=PermissionError("denied")
        ):
            with self.assertRaises(PermissionError):
                lfn.extended_path("relative")


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.state = lfn._Patches()
        self.convert = mock.patch.object(
            lfn, "extended_path", side_effect=lambda x: ("converted", x)
        )
        self.convert.start()
        self.addCleanup(self.convert.stop)

    def test_positional_and_keyword_contracts(self):
        original = mock.Mock(return_value="result")
        wrapped = lfn._wrap_paths(original, ((0, "src"), (1, "dst")), self.state)
        self.assertEqual(wrapped("a", dst="b", follow_symlinks=False), "result")
        original.assert_called_once_with(
            ("converted", "a"), dst=("converted", "b"), follow_symlinks=False
        )

    def test_directory_handle_operations_pass_through(self):
        for option in ("dir_fd", "src_dir_fd", "dst_dir_fd"):
            original = mock.Mock()
            wrapped = lfn._wrap_paths(original, ((0, "path"),), self.state)
            wrapped("relative", **{option: 7})
            original.assert_called_once_with("relative", **{option: 7})

    def test_errors_and_duplicate_arguments_preserved(self):
        def original(path):
            raise PermissionError("original error")

        wrapped = lfn._wrap_paths(original, ((0, "path"),), self.state)
        with self.assertRaisesRegex(PermissionError, "original error"):
            wrapped("a")
        with self.assertRaises(TypeError):
            wrapped("a", path="b")

    def test_undo_preserves_later_wrapper_and_deactivates_ours(self):
        class Target:
            call = staticmethod(lambda path: path)

        target = Target()
        ours = lfn._wrap_paths(target.call, ((0, "path"),), self.state)
        self.state.replace(target, "call", ours)
        target.call = lambda path: ours(path)
        later = target.call
        self.state.undo()
        self.assertIs(target.call, later)
        self.assertEqual(target.call("original"), "original")

    def test_scandir_resolves_pathlike_once_and_keeps_short_native_iterator(self):
        class Once:
            calls = 0

            def __fspath__(self):
                self.calls += 1
                if self.calls != 1:
                    raise AssertionError("path-like object resolved twice")
                return "directory"

        for longpath in (False, True):
            path = Once()
            stream = mock.Mock()
            original = mock.Mock(return_value=stream)
            destination = "extended-directory" if longpath else "directory"
            with mock.patch.object(lfn, "extended_path", return_value=destination):
                result = lfn._wrap_scandir(original, self.state)(path)
            self.assertEqual(path.calls, 1)
            original.assert_called_once_with(destination)
            if longpath:
                self.assertEqual(result._parent, "directory")
            else:
                self.assertIs(result, stream)

    def test_symlink_target_is_data(self):
        original = mock.Mock()
        lfn._wrap_paths(original, ((1, "dst"),), self.state)(
            "../target", "link", target_is_directory=True
        )
        original.assert_called_once_with(
            "../target", ("converted", "link"), target_is_directory=True
        )


if __name__ == "__main__":
    unittest.main()
