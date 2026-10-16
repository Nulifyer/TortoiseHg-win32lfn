# Mercurial 7.0.1 compatibility

This implementation was designed against the actual 7.0.1 source distribution from
[PyPI](https://pypi.org/project/mercurial/7.0.1/).
Its SHA-256 is `0f4cde42ec6c15f7ff93d421e7a842fdb30ee7951b1dbc4aacaac06eac764b48`.
No Mercurial 7.1 or 7.2 interface is assumed.

## Startup and registration

`extensions.loadall()` imports configured modules, registers `configtable`, runs `uisetup`, then runs `extsetup`.
Command registration uses `registrar.command(cmdtable)` with byte-string names, options, help, and synopsis.
The only setting is `[win32lfn] enabled`, registered with `registrar.configitem`, defaulting to true.
It controls process installation at startup. Changing it does not unload wrappers from an existing command server.

`dispatch._getlocal()` discovers repositories and reads local configuration before `extensions.loadall()`.
Extension setup cannot repair every failure that occurs before this stage.
Use user/system configuration and run from a short current directory with `-R` for deeply nested repositories.
The automated tests cover initialization and working-copy operations through `-R` with a repository root exceeding 320 characters.

TortoiseHg 7.0.1's `tortoisehg.util.hglib.loadextensions()` calls Mercurial's `extensions.loadall()`.
`tortoisehg.hgqt.run` invokes it before opening the command's repository UI.
Some GUI startup path handling and `chdir` attempts precede this call.
External extensions therefore need configuration that is accessible during startup.
The reviewed TortoiseHg source archive is available from the project's
[release directory](https://www.mercurial-scm.org/release/tortoisehg/targz/).

`testedwith` is Mercurial metadata for diagnostics, not a Windows certification mechanism.
The extension declares `testedwith = b"7.0.1"` after target-release CLI and Windows API tests.
See [the test record](testing.md) for the actual scope.

## Why VFS alone is insufficient

`vfs.vfs` delegates file opening to `util.posixfile` and uses standard Python filesystem calls elsewhere.
`dirstate.walk()` caches `util.listdir` and calls `os.lstat` on paths produced by `_join`.
Directory creation, rename, copy, archive timestamps, and other operations also call Python filesystem functions directly.
A VFS-only path rewrite would miss these calls and leak namespace prefixes into repository-relative path handling.

The implementation instead adapts final filesystem calls in the process.
It does not change dirstate contents, manifests, repository-relative paths, VFS joins, locks, or transaction algorithms.
This is still process-wide interception. It is necessary for the inspected call paths and has explicit limits for other extensions.

| 7.0.1 owner | Adaptation and reason |
| --- | --- |
| `os.stat`, `os.lstat` | Dirstate walking, path audits, filesystem identity and working-copy checks bypass VFS. |
| `os.open`, `builtins.open`, `io.open` | Direct file access, temporary files and standard-library copies. Integer descriptors pass through. |
| `os.mkdir`, `rmdir`, `remove`, `unlink` | Directory creation and deletion beneath long working-copy and repository roots. Higher-level recursion keeps its existing implementation. |
| `os.rename`, `replace`, `link` | Preserve the actual operation and flags while adapting both path arguments. |
| `os.chmod`, `utime` | Existing mode handling, read-only handling and archive timestamps. |
| `os.listdir`, `scandir`, `readlink` | Standard-library enumeration and path inspection. Long `scandir` entries preserve their caller-facing path spelling through an adapter. |
| `os.symlink` | Adapt only the destination. A relative symlink target is stored data and must remain relative. |
| Selected `osutil.posixfile` | The Windows C helper calls ANSI `CreateFile`; the pure fallback uses `CreateFileA`. Prefixing alone does not supply the required Unicode API. |
| `osutil.listdir`, `windows.listdir`, `util.listdir` | 7.0.1 caches these aliases independently. The C helper uses `FindFirstFileA`; Unicode `scandir` supplies long-directory results. |
| `win32._kernel32` | A private proxy adapts `CreateFileA`, `CreateHardLinkA`, `SetFileAttributesA`, and `GetVolumePathNameA` for long paths only. Other calls delegate to the original DLL object. |

The kernel proxy keeps `win32._getfileinfo`, `nlinks`, `samefile`, `samedevice`, `oslink`, `makedir`, and `unlink` algorithms intact.
`util` and `windows` aliases reach those functions' module globals, so those aliases need no additional wrappers.
`getfstype` uses the adapted volume lookup and retains its existing filesystem classification.

## File opening and transactions

Long `posixfile` opens use `CreateFileW` with `FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE`.
The handle transfers to the CRT through `msvcrt.open_osfhandle`.
An `io.open` opener transfers descriptor ownership once, including failures during stream construction.
The default `windows.fdproxy`, append positioning, and mixed read/write wrapper still run.
Replacing this path with ordinary `open()` would lose the sharing required by Mercurial's atomic replacement behavior.

The extension does not replace Mercurial's transaction, locking, atomic-file, or delayed-unlink code.
Tests hold an old reader open while renaming, unlinking, and recreating a long file.
They also exercise hardlink identity and read-only unlink through the native adapters.
Mercurial's own best-effort attribute updates and unlink retry policy remain its responsibility.
`hg lfn --clean` uses direct unlink and propagates failures instead of adopting that best-effort deletion policy.

## Encoding and namespace rules

`mercurial.pycompat` calls `sys._enablelegacywindowsfsencoding()` on Windows.
Consequently, a filename byte sequence is interpreted using the effective legacy filesystem codec.
The extension obtains that codec with `sys.getfilesystemencoding()` and uses strict conversion.
It preserves bytes versus text after normalization and never unconditionally decodes a byte path as UTF-8.
Encoding also requires a lossless round trip, preventing best-fit substitutions from aliasing different filenames.

The embedded Python 3.9 test driver demonstrated a relevant detail.
Its early `os.fsencode` closure retained UTF-8 even after Mercurial changed `sys.getfilesystemencoding()` to `mbcs`.
Tests therefore encode Mercurial fixture paths using the effective codec explicitly.
The extension itself does not depend on that stale closure.

`ntpath.abspath` uses Windows full-path resolution for relative, rooted, and drive-relative paths.
The extension normalizes DOS paths before adding a namespace prefix.
Existing `\\?\`, `\\.\`, and `\??\` inputs remain opaque, preserving their caller-selected semantics.
Long DOS paths with reserved devices, trailing dots/spaces, alternate streams, or invalid DOS syntax are refused.
Prefixing such paths could otherwise reinterpret them as different filesystem objects.
Thresholds count UTF-16 code units, including surrogate pairs, rather than Python code points or encoded bytes.

Directory-handle-relative arguments bypass conversion and retain the platform's support errors.
File descriptors pass through unchanged. Path-like inputs to `scandir` resolve once; short paths retain native directory-entry and iterator types.
All unrelated keyword arguments reach the original callable.
Installation records each replacement and rolls back on errors.
Uninstall removes a wrapper only when it still owns that callable; buried wrappers deactivate and forward without conversion.

## Cleanup ownership

Cleanup scans before mutating and holds `repo.wlock()` throughout.
Its path structure operations use Unicode, so a multibyte character containing a backslash-valued byte is never split as a separator.
Every dirstate key and its directory ancestors are protected, including removed or missing tracked entries still in dirstate.
Case-normalized names and filesystem identities also protect aliases of tracked files and their directories.
The scan excludes metadata and nested repositories and never follows a reparse point.
Only unlink and empty-directory removal perform deletion.

Python 3.9 on Windows returns zero file IDs from `DirEntry.stat()`.
Cleanup therefore snapshots with `os.lstat()` and uses the same operation when checking identities before deletion.
It also checks file size and modification time and rechecks every captured ancestor after a confirmation prompt.
These checks detect ordinary replacement races. They do not provide a security boundary against an attacker replacing paths between validation and the kernel operation.

## Maintenance risks

The selected osutil module and `win32._kernel32` are private interfaces.
Future Mercurial versions require source review and a new Windows test run before support is claimed.
Replacing these adapters with copies of transaction, unlink, or VFS implementations would duplicate ownership and increase maintenance risk.

Other extensions can retain old function references or change encoding contracts.
Long-path helper replacements can bypass wrappers installed earlier on the same helper.
Wrapper coexistence is unit-tested, but arbitrary combinations of filesystem extensions are not certified.
Use one copy of win32lfn and restart persistent processes after configuration changes.
