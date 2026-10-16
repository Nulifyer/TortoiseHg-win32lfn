import os
import types
import unittest
from unittest import mock

import mercurial

import win32lfn as lfn


class InstallTests(unittest.TestCase):
    def test_platform_and_configuration_gating(self):
        with mock.patch.object(os, "name", "posix"):
            self.assertFalse(lfn.install())
        ui = mock.Mock()
        ui.configbool.return_value = False
        with mock.patch.object(lfn, "install") as install:
            lfn.uisetup(ui)
            install.assert_not_called()
        ui.configbool.return_value = True
        with mock.patch.object(lfn, "install") as install:
            lfn.uisetup(ui)
            install.assert_called_once_with()

    def test_idempotency_uninstall_and_reinstall(self):
        osutil = types.SimpleNamespace(
            posixfile=lambda *a: None, listdir=lambda *a, **k: []
        )
        windows = types.SimpleNamespace(osutil=osutil, listdir=osutil.listdir)
        win32 = types.SimpleNamespace(_kernel32=object())
        old_stat = os.stat
        with (
            mock.patch.object(mercurial, "windows", windows, create=True),
            mock.patch.object(mercurial, "win32", win32, create=True),
            mock.patch.object(
                lfn, "_WideKernel32", side_effect=lambda original, state: original
            ),
            mock.patch.object(os, "name", "nt"),
        ):
            try:
                self.assertTrue(lfn.install())
                installed = os.stat
                self.assertFalse(lfn.install())
                self.assertIs(os.stat, installed)
                lfn.uninstall()
                self.assertIs(os.stat, old_stat)
                self.assertTrue(lfn.install())
            finally:
                lfn.uninstall()
        self.assertIs(os.stat, old_stat)

    def test_failed_install_rolls_back(self):
        old_stat = os.stat
        with (
            mock.patch.object(
                mercurial,
                "windows",
                types.SimpleNamespace(osutil=object()),
                create=True,
            ),
            mock.patch.object(
                mercurial,
                "win32",
                types.SimpleNamespace(_kernel32=object()),
                create=True,
            ),
            mock.patch.object(
                lfn, "_WideKernel32", side_effect=RuntimeError("adapter failed")
            ),
            mock.patch.object(os, "name", "nt"),
        ):
            with self.assertRaisesRegex(RuntimeError, "adapter failed"):
                lfn.install()
        self.assertIs(os.stat, old_stat)
        self.assertIsNone(getattr(os, lfn._STATE, None))

    def test_partial_install_rolls_back_every_replacement(self):
        original = lambda *a: None
        osutil = types.SimpleNamespace(posixfile=original)
        windows = types.SimpleNamespace(osutil=osutil)
        kernel = object()
        win32 = types.SimpleNamespace(_kernel32=kernel)
        with (
            mock.patch.object(mercurial, "windows", windows, create=True),
            mock.patch.object(mercurial, "win32", win32, create=True),
            mock.patch.object(lfn, "_WideKernel32", return_value=object()),
            mock.patch.object(os, "name", "nt"),
        ):
            with self.assertRaises(AttributeError):
                lfn.install()
        self.assertIs(win32._kernel32, kernel)
        self.assertIs(osutil.posixfile, original)
        self.assertIsNone(getattr(os, lfn._STATE, None))
