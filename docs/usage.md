# Usage and operational limits

## Check the installed runtime

Use the executables from the intended TortoiseHg installation:

```powershell
$win32lfnHg = 'C:\Program Files\TortoiseHg\hg.exe'
& $win32lfnHg version --verbose
& $win32lfnHg debuginstall
& $win32lfnHg config --source extensions.win32lfn
& $win32lfnHg debugextensions
```

`version` must report Mercurial 7.0.1. `debuginstall` identifies the bundled Python runtime.
`config --source` identifies the configuration file that supplies the extension path.
`debugextensions` lists loaded extensions. These checks establish loading, not long-path operation.

## Choose the configuration location

Use the user configuration for both TortoiseHg and `hg`.
Mercurial 7.0.1 also reads `%USERPROFILE%\.hgrc`, installation configuration, and system configuration under `%PROGRAMDATA%\Mercurial`.
System choices include `Mercurial.ini`, `hgrc`, and `hgrc.d\*.rc` in that directory.
The installation directory can contain `Mercurial.ini` and `hgrc.d\*.rc`.
`HGRCPATH`, when set, changes configuration discovery.
These locations come from Mercurial 7.0.1's own `help config` and `rcutil.py`.

Configure the extension outside the repository. Mercurial reads repository configuration during discovery, before extension setup.
A repository-local `.hg\hgrc` can therefore be too late.
Keep the command's current directory short and address a deeply nested repository explicitly:

```powershell
& $win32lfnHg -R 'C:\path\to\deep\repository' status
```

The extension does not emulate the current directory. Windows 10 testing with native opt-in disabled rejected a long `chdir` with WinError 206.
Launching the shell itself inside a long path can fail before the extension loads. Use a short current directory and `-R`.

## Try a disposable repository

After configuring the extension, run this from a short directory. It creates a new repository and leaves it for inspection.
It does not change Windows registry settings.

```powershell
$win32lfnDemo = Join-Path $env:TEMP ('win32lfn-demo-' + [guid]::NewGuid().ToString('N'))
& $win32lfnHg init $win32lfnDemo
$win32lfnNested = $win32lfnDemo
1..18 | ForEach-Object { $win32lfnNested = Join-Path $win32lfnNested 'directory123456789' }
# Extended spelling is used only to prepare the fixture with .NET.
$win32lfnExtended = '\\?\' + $win32lfnNested
[IO.Directory]::CreateDirectory($win32lfnExtended) | Out-Null
[IO.File]::WriteAllText($win32lfnExtended + '\example.txt', 'long path test')
& $win32lfnHg -R $win32lfnDemo add
& $win32lfnHg -R $win32lfnDemo --config 'ui.username=Long path test' commit -m 'long path test'
& $win32lfnHg -R $win32lfnDemo status
& $win32lfnHg -R $win32lfnDemo update -r null
& $win32lfnHg -R $win32lfnDemo update -r 0
& $win32lfnHg -R $win32lfnDemo lfn
```

Check command exit codes. After checkout, confirm that `example.txt` contains `long path test`.
Open the repository in TortoiseHg and refresh its status.
For full automated testing, use [the Windows test instructions](testing.md).

## Report or clean long paths

```text
hg lfn
hg lfn --clean
hg lfn --clean --force
```

`hg lfn` reports absolute paths with at least 260 UTF-16 code units for files, or 248 for directories.
These are legacy compatibility thresholds, not a measurement of each application's actual limit.
The scan excludes `.hg` metadata and nested repositories. It does not follow symlinks, junctions, or other reparse points.
An unreadable directory fails the scan instead of silently hiding entries.

Back up the working copy before using `--clean`. Cleanup includes **ignored and untracked files**.
It protects every dirstate path, tracked-path ancestors, metadata, nested repositories, and reparse points.
`--force` suppresses prompts. It does not override these protections and requires `--clean`.
There is no option to delete tracked files through this command. Use normal Mercurial commands for those files.

Cleanup first scans the entire tree, then deletes individual files and empty directories, children before parents.
The default answer to each prompt is No. A nonempty directory remains in place.
Exit code 1 means protected, declined, or nonempty candidates remain. Operational errors abort the command.
The command takes Mercurial's working-copy lock and rechecks identities immediately before deletion.
Stop other programs that change this working copy during cleanup. These checks cannot prevent every concurrent filesystem race.

## Native Windows support and the extension

Windows long-path opt-in requires both `LongPathsEnabled` and an executable manifest with `longPathAware`.
It applies to the process and supported Windows APIs. It does not remove component-length or filesystem limits.
Inspect the setting without changing it:

```powershell
Get-ItemPropertyValue 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' LongPathsEnabled
```

If the Windows SDK is installed, `mt.exe` can extract an executable's manifest:

```powershell
mt.exe '-inputresource:C:\Program Files\TortoiseHg\hg.exe;#1' '-out:hg.manifest.xml'
mt.exe '-inputresource:C:\Program Files\TortoiseHg\thg.exe;#1' '-out:thg.manifest.xml'
```

Inspect both executables separately. An absent manifest does not declare `longPathAware`.
A bundled Python DLL's capabilities alone do not establish the executable's opt-in state.
See Microsoft's [long-path documentation](https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation).

Mercurial 7.0.1 still has ANSI filesystem helpers and direct filesystem calls outside its VFS.
The extension resolves long DOS paths, adds the extended namespace, and uses Unicode operations for the remaining native helpers.
It preserves Mercurial's ability to rename and unlink files while readers keep the old revision open.
No registry or executable modification is required by this extension.
Compare native behavior with the extension disabled before deciding whether to enable it on your installation.

## Encoding and path limits

Mercurial 7.0.1 uses the Windows legacy filesystem code page for byte paths.
This extension uses that effective filesystem codec and strict conversion. It does not decode arbitrary bytes as UTF-8.
Unicode working-copy names must still be representable in Mercurial's active filesystem code page.
This extension does not change repository filename encoding or replace `win32mbcs`.
Japanese and other multibyte locales still need Mercurial's normal encoding precautions.

Ordinary short paths retain their normal spelling. Long relative and drive-relative paths are resolved before prefixing.
UNC paths become `\\?\UNC\server\share\...`. Existing extended and device namespace inputs remain opaque.
Ambiguous long DOS names, including reserved devices and trailing dots or spaces, are refused rather than reinterpreted.
Embedded nulls and unsupported argument types retain errors.
Individual components remain limited by the filesystem, usually 255 characters on NTFS.
A single oversized component is not fixed by this extension.

## Disable or remove

To keep `hg lfn` registered but disable filesystem interception:

```ini
[win32lfn]
enabled = false
```

To unload the extension completely:

```ini
[extensions]
win32lfn = !
```

Restart TortoiseHg and command servers afterward.
Remove the configuration before deleting or moving `win32lfn.py`.
Disabling does not rename existing long paths. Other applications may still be unable to open or remove them.

## Remaining limits

- Explorer, editors, merge tools, hooks, and subprocesses have their own path limits. The extension cannot change those processes.
- Filesystem interception affects the current process. Other extensions that cache filesystem callables before setup can bypass it.
  A long-path helper replacement can also bypass another extension's earlier wrapper. Test extension combinations separately.
- Long `scandir` results use a small adapter to preserve `DirEntry.path` spelling. Code requiring the exact built-in entry type can distinguish it.
- `open().name` and filesystem exceptions can expose the extended spelling of a long path.
- SMB servers, share permissions, and network filesystems can impose additional limits. See the test report for UNC coverage.
- Symlink privilege and reparse-point behavior depend on Windows configuration. Cleanup deliberately preserves these entries.
- Windows ARM64, x86, other Mercurial releases, and arbitrary combinations of filesystem extensions have not been certified.

See [the API compatibility report](compatibility.md) and [the source comparison](source-comparison.md) for implementation details.
