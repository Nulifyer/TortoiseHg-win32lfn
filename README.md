# win32lfn

## What it is

A Mercurial extension for Windows working-copy paths longer than 260 characters.
It targets **TortoiseHg 7.0.1 / Mercurial 7.0.1**, Python 3.9, and Windows 10/11 x64.

## Setup

1. Copy the root `win32lfn.py` to a permanent location, such as `C:\Tools\win32lfn`.
2. Add this to `%USERPROFILE%\Mercurial.ini`:

```ini
[extensions]
win32lfn = C:\Tools\win32lfn\win32lfn.py
```

Replace any old win32lfn setting. The former `src\win32lfn.py` has been removed.
No separate Python installation is needed to use the extension.

3. Restart TortoiseHg and any Mercurial command servers.
4. Check the bundled version and extension loading:

```powershell
& 'C:\Program Files\TortoiseHg\hg.exe' version
& 'C:\Program Files\TortoiseHg\hg.exe' help lfn
```

Confirm Mercurial **7.0.1**. Use `hg lfn` to list long paths.
For a deeply nested repository, launch from a short directory and use `hg -R <path>`.

See [usage and cleanup](docs/usage.md), [test results](docs/testing.md), and [compatibility](docs/compatibility.md) for details.
Back up files before using `hg lfn --clean`. Cleanup can delete ignored and untracked files.

## Remove

Remove the `win32lfn` line from `Mercurial.ini`, then restart TortoiseHg and command servers.
You can then delete `win32lfn.py`. Existing long paths remain on disk.

GPLv2 or later. Original author: Aaron Cohen. See [LICENSE](LICENSE) and [source comparison](docs/source-comparison.md).
