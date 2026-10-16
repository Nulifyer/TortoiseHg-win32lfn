r"""Run against a chosen TortoiseHg hg.exe and a matching Python 3.9 interpreter.

Example: python tests\run_windows.py --hg "C:\\Program Files\\TortoiseHg\\hg.exe"
         --workdir .tmp\\windows --report .test-results\\windows.json
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import unittest
from pathlib import Path


def manifest(path):
    """Read executable resource #1 as data; do not execute the image."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel.LoadLibraryExW.restype = wintypes.HMODULE
    kernel.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    kernel.FindResourceW.restype = wintypes.HANDLE
    kernel.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    kernel.SizeofResource.restype = wintypes.DWORD
    kernel.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HANDLE]
    kernel.LoadResource.restype = wintypes.HANDLE
    kernel.LockResource.argtypes = [wintypes.HANDLE]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = [wintypes.HMODULE]
    kernel.FreeLibrary.restype = wintypes.BOOL
    module = kernel.LoadLibraryExW(str(path), None, 0x22)
    if not module:
        return {"error": ctypes.get_last_error()}
    try:
        resource = kernel.FindResourceW(module, 1, 24)
        if not resource:
            return {"xml": None, "error": ctypes.get_last_error()}
        size = kernel.SizeofResource(module, resource)
        address = kernel.LockResource(kernel.LoadResource(module, resource))
        return {"xml": ctypes.string_at(address, size).decode("utf-8-sig")}
    finally:
        kernel.FreeLibrary(module)


def main():
    if os.name != "nt":
        raise SystemExit(
            "This runner requires Windows. Use unittest discovery on other platforms."
        )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hg", required=True, help="TortoiseHg 7.0.1 hg.exe")
    parser.add_argument(
        "--workdir",
        default=".tmp/windows",
        help="disposable test parent; may be an existing UNC share",
    )
    parser.add_argument("--report", default=".test-results/windows.json")
    parser.add_argument(
        "--pattern", default="test_*.py", help="unittest discovery pattern"
    )
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    os.environ["WIN32LFN_TEST_ROOT"] = str(workdir)
    os.environ["WIN32LFN_HG_COMMAND"] = json.dumps([str(Path(args.hg).resolve())])
    sys.path.insert(0, str(project))
    sys.path.insert(0, str(project / "tests"))
    env = os.environ.copy()
    env.update(HGRCPATH="", HGPLAIN="1")
    version = subprocess.run(
        [args.hg, "version", "-q"], env=env, capture_output=True, check=True
    )
    if b"7.0.1" not in version.stdout:
        raise SystemExit("Expected Mercurial 7.0.1, got: " + repr(version.stdout))
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
    ) as key:
        longpaths = winreg.QueryValueEx(key, "LongPathsEnabled")[0]
    # Probe before extension activation. Do not assume every machine needs it.
    baseline = workdir / ("native-probe-" + str(os.getpid()))
    baseline.mkdir()
    env["HGUSER"] = "win32lfn native probe <test@example.invalid>"
    try:
        subprocess.run(
            [args.hg, "init", str(baseline)], env=env, check=True, capture_output=True
        )
        relative = Path(*(["directory123456789"] * 18)) / "caf\u00e9.txt"
        target = baseline / relative
        extended = (
            "\\\\?\\UNC\\" + str(target.parent)[2:]
            if str(target).startswith("\\\\")
            else "\\\\?\\" + str(target.parent)
        )
        os.makedirs(extended)
        with open(extended + "\\caf\u00e9.txt", "wb") as stream:
            stream.write(b"native probe")
        native = subprocess.run(
            [args.hg, "--cwd", str(baseline), "add"], env=env, capture_output=True
        )
    finally:
        import shutil

        extended = (
            "\\\\?\\UNC\\" + str(baseline)[2:]
            if str(baseline).startswith("\\\\")
            else "\\\\?\\" + str(baseline)
        )
        shutil.rmtree(extended)
    start = time.monotonic()
    suite = unittest.defaultTestLoader.discover(
        str(project / "tests"), pattern=args.pattern
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        "platform": platform.platform(),
        "python": sys.version,
        "os_caption": subprocess.check_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_OperatingSystem).Caption",
            ]
        )
        .decode("ascii", "backslashreplace")
        .strip(),
        "filesystem_encoding": sys.getfilesystemencoding(),
        "os_fsencode_sample": os.fsencode("caf\u00e9").hex(),
        "hg": str(Path(args.hg).resolve()),
        "hg_version": version.stdout.decode("ascii").strip(),
        "LongPathsEnabled": longpaths,
        "workdir": str(workdir),
        "hg_sha256": hashlib.sha256(Path(args.hg).read_bytes()).hexdigest(),
        "hg_manifest": manifest(Path(args.hg)),
        "thg_manifest": manifest(Path(args.hg).with_name("thg.exe")),
        "extension_sha256": hashlib.sha256(
            (project / "win32lfn.py").read_bytes()
        ).hexdigest(),
        "native_add": {
            "returncode": native.returncode,
            "stdout": native.stdout.decode("cp1252", "backslashreplace"),
            "stderr": native.stderr.decode("cp1252", "backslashreplace"),
        },
        "pattern": args.pattern,
        "tests": result.testsRun,
        "failures": [(str(t), detail) for t, detail in result.failures],
        "errors": [(str(t), detail) for t, detail in result.errors],
        "skipped": [(str(t), reason) for t, reason in result.skipped],
        "seconds": round(time.monotonic() - start, 2),
    }
    destination = Path(args.report)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
