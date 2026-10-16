import contextlib
import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mercurial import error, util

import win32lfn as lfn

ROOT = Path(
    os.environ.get(
        "WIN32LFN_TEST_ROOT", str(Path(__file__).resolve().parents[1] / ".tmp")
    )
)


class UI:
    def __init__(self, answer=0):
        self.output = []
        self.warnings = []
        self.answer = answer
        self.prompts = []

    def write(self, message):
        self.output.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def promptchoice(self, message, default):
        self.prompts.append((message, default))
        return self.answer


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.installed = lfn.install()
        self.addCleanup(lambda: lfn.uninstall() if self.installed else None)
        ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = lfn._encode(self.temp.name)
        self.deep = os.path.join(self.root, *([b"segment123456789"] * 18))
        os.makedirs(self.deep)
        self.longfile = os.path.join(self.deep, b"untracked.txt")
        with open(self.longfile, "wb") as stream:
            stream.write(b"keep until requested")
        self.ui = UI()
        self.repo = mock.Mock(root=self.root, dirstate={})
        self.repo.wlock.side_effect = contextlib.nullcontext

    def test_report_and_default_no_do_not_delete(self):
        self.assertEqual(lfn.lfn(self.ui, self.repo), 0)
        self.assertTrue(any(self.longfile in s for s in self.ui.output))
        self.assertEqual(lfn.lfn(self.ui, self.repo, clean=True), 1)
        self.assertTrue(os.path.isfile(self.longfile))
        self.assertTrue(self.ui.prompts)
        self.assertTrue(all(default == 0 for message, default in self.ui.prompts))

    def test_force_requires_clean(self):
        with self.assertRaises(error.Abort):
            lfn.lfn(self.ui, self.repo, force=True)
        self.assertTrue(os.path.isfile(self.longfile))

    def test_force_deletes_children_before_empty_parents(self):
        self.assertEqual(lfn.lfn(self.ui, self.repo, clean=True, force=True), 0)
        self.assertFalse(os.path.exists(self.longfile))
        self.assertFalse(os.path.exists(self.deep))
        self.assertFalse(self.ui.prompts)
        self.repo.wlock.assert_called_once()

    def test_prompt_yes_uses_correct_directory_name(self):
        self.ui.answer = 1
        self.assertEqual(lfn.lfn(self.ui, self.repo, clean=True), 0)
        self.assertTrue(
            any(self.deep in message for message, default in self.ui.prompts)
        )

    def test_tracked_paths_and_their_ancestors_are_protected(self):
        tracked = os.path.join(self.deep, b"tracked.txt")
        with open(tracked, "wb") as stream:
            stream.write(b"tracked contents")
        relative = os.path.relpath(tracked, self.root)
        self.repo.dirstate = {util.pconvert(relative): object()}
        self.assertEqual(lfn.lfn(self.ui, self.repo, clean=True, force=True), 1)
        self.assertTrue(os.path.isfile(tracked))
        self.assertFalse(os.path.exists(self.longfile))
        self.assertTrue(self.ui.warnings)

    def test_metadata_and_nested_repositories_are_not_scanned(self):
        for parent in (
            os.path.join(self.root, b".hg"),
            os.path.join(self.deep, b"nested", b".hg"),
        ):
            os.makedirs(parent)
            child = os.path.join(parent, b"data")
            with open(child, "wb") as stream:
                stream.write(b"metadata")
        candidates, directories = lfn._scan(self.root)
        self.assertFalse(
            any(".hg" in path or "nested" in path for path, info in candidates)
        )
        lfn.lfn(self.ui, self.repo, clean=True, force=True)
        self.assertTrue(
            os.path.isfile(os.path.join(self.deep, b"nested", b".hg", b"data"))
        )

    def test_symlink_is_neither_followed_nor_deleted(self):
        target = os.path.join(self.root, b"target")
        os.mkdir(target)
        with open(os.path.join(target, b"sentinel"), "wb") as stream:
            stream.write(b"outside")
        link = os.path.join(self.deep, b"linked")
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as exc:
            self.skipTest("symlink creation unavailable: %s" % exc)
        candidates, directories = lfn._scan(self.root)
        self.assertFalse(any(path.endswith("sentinel") for path, info in candidates))
        self.assertEqual(lfn.lfn(self.ui, self.repo, clean=True, force=True), 1)
        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.isfile(os.path.join(target, b"sentinel")))

    def test_scan_error_aborts_before_any_deletion(self):
        with mock.patch.object(lfn, "_scan", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                lfn.lfn(self.ui, self.repo, clean=True, force=True)
        self.assertTrue(os.path.isfile(self.longfile))

    def test_delete_failure_does_not_continue(self):
        with mock.patch.object(
            os, "unlink", side_effect=PermissionError("denied")
        ) as unlink:
            with self.assertRaises(PermissionError):
                lfn.lfn(self.ui, self.repo, clean=True, force=True)
        unlink.assert_called_once()
        self.assertTrue(os.path.isfile(self.longfile))

    def test_directory_replacement_aborts(self):
        moved = self.deep + b"-moved"

        def replace_after_prompt(message, default):
            os.rename(self.deep, moved)
            os.mkdir(self.deep)
            return 1

        self.ui.promptchoice = replace_after_prompt
        with self.assertRaises(error.Abort):
            lfn.lfn(self.ui, self.repo, clean=True)
        self.assertTrue(os.path.isfile(os.path.join(moved, b"untracked.txt")))

    def test_nonempty_directory_never_recurses(self):
        os.unlink(self.longfile)
        with mock.patch.object(
            os, "rmdir", side_effect=OSError(errno.ENOTEMPTY, "not empty")
        ):
            self.assertEqual(lfn.lfn(self.ui, self.repo, clean=True, force=True), 1)
        self.assertTrue(os.path.isdir(self.deep))


if __name__ == "__main__":
    unittest.main()
