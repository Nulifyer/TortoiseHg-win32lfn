# Testing

Use a disposable working directory. The tests create and delete repositories beneath the selected test parent.
They do not change registry settings or executable manifests.

## Run on your Windows machine

Use a separate Python 3.9 x64 interpreter for the test driver.
TortoiseHg's frozen executables do not provide a general `python -m unittest` entrypoint.
Install the matching Mercurial package into a project-local environment:

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\python.exe -m pip install mercurial==7.0.1
.\.venv\Scripts\python.exe tests\run_windows.py `
  --hg 'C:\Program Files\TortoiseHg\hg.exe' `
  --workdir .tmp\windows `
  --report .test-results\windows.json
```

Check the exit code and JSON report. A nonzero test exit means the environment or extension needs investigation.
The runner rejects another Mercurial release, records a native-disabled baseline, then runs the tests with the extension configured explicitly.
Your normal Mercurial configuration is excluded from CLI fixtures.
Native API tests use the matching PyPI package in the test driver.
Mercurial subprocess tests use the selected TortoiseHg `hg.exe` itself.

To test a share you can already write to, run the Mercurial integration group:

```powershell
.\.venv\Scripts\python.exe tests\run_windows.py `
  --hg 'C:\Program Files\TortoiseHg\hg.exe' `
  --pattern test_mercurial.py `
  --workdir '\\server\share\win32lfn-tests' `
  --report .test-results\unc.json
```

This does not create or reconfigure a share.
Network filesystems can reject hardlinks or junction operations independently of path length.
The integration group checks Mercurial behavior without requiring those native filesystem capabilities.

## What the automated tests check

| Test file | Evidence supplied |
| --- | --- |
| `test_paths.py` | Drive, UNC and UNC-root conversion; relative and drive-relative resolution; normalization; namespace preservation; path-like objects; descriptors; UTF-16 boundaries; malformed DOS syntax; cp1252, cp1255 and cp932 bytes. Windows resolution is mocked in this group. |
| `test_install.py` | Platform/configuration gating, duplicate installation, uninstall/reinstall, and rollback after partial installation. |
| `test_cleanup.py` | Real directory traversal and individual deletion; prompt defaults; correct directory prompts; tracked ancestors; metadata and nested-repository protection; symlink protection when privileges permit; failures; replacement during a confirmation prompt. |
| `test_mercurial.py` | Exact release loading; short paths with interception off/on; long init/add/commit/status/revert/update/clone/archive/merge/rename/remove; Unicode filenames; real dirstate cleanup; initialization and operations with a repository root longer than 320 characters. |
| `test_windows.py` | Real W API behavior, byte paths, keyword arguments, descriptors, relative paths, scan results, delete-sharing, append/mixed modes, hardlinks, readonly unlink, readonly cleanup failure, case aliases, unrepresentable Unicode rejection and junction protection. |

The long workflow uses 18 directory components plus `café.txt`.
The filename is representable in the test machines' active Windows code page.
The encoding unit tests cover additional code pages without claiming native testing of those locales.
The native Windows tests also create a filename outside the active code page and verify explicit rejection at the Mercurial enumeration/cleanup interface.

## GUI procedure

Use the configured TortoiseHg 7.0.1 installation and a short repository root.

1. Create and commit a file beneath enough directory components to exceed 320 characters.
2. Commit a second revision with different contents in that file.
3. Modify the file again without committing.
4. Open `thg status`, refresh, select the long file, and inspect its diff.
5. Revert the uncommitted change through Mercurial.
6. Open `thg update --rev 0` and press Update.
7. Confirm revision 0, the original file contents, and a clean status through `hg`.

The screenshots and GUI result JSON files below record this procedure in the Windows test VMs.
A CLI test alone does not establish GUI compatibility.

## POSIX checks

These check registration, command behavior, filesystem logic and ordinary Mercurial operations. They do not establish Windows compatibility.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install mercurial==7.0.1
HGDEMANDIMPORT=disable .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

`HGDEMANDIMPORT=disable` was needed for Mercurial 7.0.1's launcher under the available Python 3.14 host runtime.
That host runtime is not the supported Windows target.
Windows-specific tests skip on POSIX.

## Verified results, October 16, 2026

| Environment | Registry setting | Automated results | Native baseline |
| --- | --- | --- | --- |
| Windows 10 Pro x64, build 19045, local NTFS | `LongPathsEnabled=0` | 48 tests: 46 passed, 2 skipped | Long-path `hg add` failed with the extension unloaded. |
| Windows 11 Pro x64, build 26200, local NTFS | `LongPathsEnabled=1` | 48 tests: 47 passed, 1 skipped | Long-path `hg add` failed with the extension unloaded. |
| Windows 10, loopback SMB UNC path | 0 | All 5 Mercurial integration tests passed | Long-path `hg add` failed with the extension unloaded. |
| Windows 11, loopback SMB UNC path | 1 | All 5 Mercurial integration tests passed | Long-path `hg add` failed with the extension unloaded. |
| Linux, Python 3.14, Mercurial 7.0.1 | Not applicable | 48 tests: 36 passed, 12 Windows-only tests skipped | Does not establish Windows compatibility. |

TortoiseHg graphical status displayed the modified long file and its diff on both Windows versions.
The graphical Update command changed revision 1 to revision 0 for a 367-character path ending in `café.txt`.
Separate post-update checks confirmed revision 0, the expected file contents and clean status.
The actual bundled runtime reported CPython 3.9.13, Mercurial 7.0.1 and C module policy on NTFS.

GUI evidence: [Windows 10 status](evidence/windows10-status.png), [Windows 11 status](evidence/windows11-status.png),
[Windows 10 update dialog](evidence/windows10-update.png), [Windows 11 update dialog](evidence/windows11-update.png),
[Windows 10 update checks](evidence/gui-windows10.json), [Windows 11 update checks](evidence/gui-windows11.json).

Both Windows test drivers used Python 3.9.13 x64 and the matching Mercurial 7.0.1 wheel.
The subprocess group used `hg.exe` from the official TortoiseHg 7.0.1 x64 MSI.
The ordinary test user lacked symlink-creation privilege on both guests.
The second Windows 10 skip records native `chdir` rejecting an extended path with WinError 206.
The same native-current-directory test passed on Windows 11 with its existing opt-in setting.
The extension does not emulate `chdir`. Short current directories with `hg -R` passed on both systems.

The manifest probe found no embedded manifest resource in either bundled `hg.exe` or `thg.exe`, Win32 error 1813.
Mercurial's source-build launcher has a separate manifest-insertion step in `setup.py`.
That source-build configuration must not be assumed for TortoiseHg's packaged executables.
The Windows 11 baseline demonstrates that the registry setting alone did not make this package's long-path operation succeed.

Reports: [POSIX checks](evidence/linux.json), [Windows 10](evidence/windows10.json), [Windows 11](evidence/windows11.json),
[Windows 10 UNC](evidence/windows10-unc.json), [Windows 11 UNC](evidence/windows11-unc.json).

## Evidence and scope

The release evidence is stored in `docs/evidence`.
Each Windows JSON report records the operating-system caption, Python version, selected executable, registry value, executable manifest lookup, extension checksum, native baseline and test results.
`sources.json` records the downloaded package checksums and inspected source revisions.
The extension checksum in each report must match the delivered `win32lfn.py`.

The test VMs used separate writable disk overlays inside this project.
Existing VM images served only as read-only backing files.
TortoiseHg 7.0.1 was administratively extracted from its official x64 MSI into each disposable guest.
The tests exercised the package's actual CLI and GUI executables.
They did not validate MSI installation, Explorer shell registration or Explorer's own long-path behavior.

The status screenshots show the modified file and its diff. The update screenshots show the selected target before execution.
These are manual observations. The post-update JSON checks revision, file contents and clean status separately.
The share tests use the Windows guest's loopback SMB administrative share. They do not certify another SMB server or NAS.
Windows symlink tests require a privilege that the normal test user may lack. Such skips remain visible in the JSON.
Junction protection is tested separately and does not require that symlink privilege.
The native long-current-directory test also skips when Windows returns WinError 206. This is separate from `-R` repository access, which is required to pass.

## Build the distributable

```sh
python tools/package.py
```

This produces `dist/win32lfn-0.1.0.zip` and `dist/SHA256SUMS`.
The ZIP contains one extension implementation, documentation, license and runnable tests.
Downloaded upstream packages, virtual environments and VM disks are excluded.
