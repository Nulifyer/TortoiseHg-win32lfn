# Source comparison

The supplied checkout is the original default-branch snapshot at revision
`a8052478845e23c379e2de04053ddbc8b9c98b4e`, dated August 31, 2018.
Its `.hg_archival.txt`, source, README, and Python 2 tests were inspected before implementation.
The handoff's prototype and ZIP bundle were absent from this workspace.
No compatibility claim depends on that unverified prototype.

The actual [Clonkex fork](https://github.com/Clonkex/win32lfn-python3) was downloaded at
commit `cfabb7b750210a23ff6dc0e1913cb52afec39ed3`.
It contains `win32lfn.py` at the repository root.
This comparison uses that code, rather than the reconstructed functional diff described in the handoff.

| Historical behavior | Replacement |
| --- | --- |
| Global prefixing of almost every pathname | Resolve and prefix paths whose absolute length reaches 248 UTF-16 code units. Pass ordinary short paths through. |
| Drive and UNC extended namespaces | Retained. Preserve the input's bytes/text representation. |
| ANSI `FindFirstFileA` directory implementation | Removed. Use Python Unicode `scandir` for Mercurial's long-directory enumeration. |
| Custom ANSI `CreateDirectoryA` implementation | Removed. Python's existing Unicode `mkdir` receives the extended spelling. |
| Global `abspath`, `split`, `chdir`, and `getcwd` replacements | Removed. Use Python 3.9 Windows resolution, including per-drive relative paths. Never emulate the process directory. |
| Broad wrappers around Mercurial copy and directory utilities | Removed. Keep their existing algorithms and intercept the filesystem calls they use. |
| Mercurial `posixfile` | Adapt the selected C/pure helper for long paths using `CreateFileW` and the original delete-sharing flags. Keep `windows.posixfile`'s proxy and mixed-mode behavior. |
| Mercurial directory enumeration | Adapt all three cached aliases in 7.0.1: selected `osutil`, `windows`, and `util`. Preserve `stat` and `skip` behavior. |
| Mercurial native file identity, hardlinks, attributes, volume lookup | A private forwarding object adapts only long filesystem calls to the W APIs. No shared ctypes DLL function is overwritten. |
| `registrar.command` | Retained from upstream. Command and option names now use Mercurial's bytes convention. |
| `hg lfn` | Retained, with metadata and nested-repository exclusions, explicit scan errors, and reparse-point protection. |
| `--clean` | Retained with default-No prompts. Files precede parent directories. Never recursively delete a directory. |
| `--clean --force` | Retained as prompt suppression. Tracked entries and their ancestors remain protected. `--force` alone is an error. |
| Incorrect directory prompt using variable `f` | Removed. Each prompt uses that candidate's path. A directory-prompt regression test covers this. |
| Unconditional runtime patches | Windows-only, configuration-gated, idempotent installation. Roll back partial installation. Reversible wrappers deactivate without removing another extension's later patches. |
| Fork's unconditional UTF-8 decode/encode | Removed. Use the effective filesystem codec with strict conversion. Include cp1252, cp1255, and cp932 unit cases. |
| Python 2 tests | Replaced with current unit tests, real Mercurial subprocess tests, Windows API tests, and an executable Windows runner. |

The Python 3 fork already retained `registrar.command` and the `mercurial.windows` fallback from upstream.
Those are not new features of the fork.
Its [reported update failure](https://github.com/Clonkex/win32lfn-python3/issues/1) is consistent with its unconditional UTF-8 decoding.
That report does not establish the cause of every Unicode error in Mercurial.

Only one extension implementation is shipped, at `win32lfn.py`.
The superseded `src/win32lfn.py`, old README, and Python 2 test entrypoint were removed.
Git history preserves the original snapshot for inspection.
GPLv2-or-later licensing and Aaron Cohen's attribution remain in the extension, README, and license file.
