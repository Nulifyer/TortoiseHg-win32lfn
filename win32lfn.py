"""Long working-copy paths for Mercurial 7.0.1 on Windows.

Configure in the user Mercurial.ini before opening a repository::

    [extensions]
    win32lfn = C:\\tools\\win32lfn.py

``hg lfn`` reports paths at legacy limits. ``--clean`` prompts before deleting
untracked entries; ``--force`` suppresses those prompts. Tracked paths, metadata,
nested repositories and reparse points are protected. See README.md for limits.

Original win32lfn: Aaron Cohen <aaron@assonance.org>, 2018 and earlier.
Modern implementation: 2026 contributors. SPDX-License-Identifier: GPL-2.0-or-later
"""

import builtins
import ctypes
import errno
import functools
import io
import ntpath
import operator
import os
import stat as statmod
import sys

from mercurial import error, registrar, util

cmdtable = {}
command = registrar.command(cmdtable)
configtable = {}
configitem = registrar.configitem(configtable)
configitem(b"win32lfn", b"enabled", default=True)

# Exact target-release CLI and Windows API tests are recorded in docs/testing.md.
testedwith = b"7.0.1"
__version__ = b"0.1.0"
_LIMIT = 248  # Directory creation can fail before the 260-character file limit.
_STATE = "_win32lfn_patch_state"
_state = None


def _decode(path):
    # Mercurial pycompat enables legacy MBCS filesystem encoding on Windows.
    # Strict conversion prevents best-fit/replacement characters aliasing names.
    return (
        path.decode(sys.getfilesystemencoding(), "strict")
        if isinstance(path, bytes)
        else path
    )


def _encode(path):
    codec = sys.getfilesystemencoding()
    encoded = path.encode(codec, "strict")
    if encoded.decode(codec, "strict") != path:
        raise UnicodeEncodeError(
            codec, path, 0, len(path), "filesystem encoding is not lossless"
        )
    return encoded


def _filename_bytes(name):
    try:
        return _encode(name)
    except UnicodeEncodeError:
        raise error.Abort(
            b"win32lfn cannot represent a filename in the Windows filesystem code page: "
            + repr(name).encode("ascii", "backslashreplace"),
            hint=b"use filenames representable in Mercurial's active filesystem code page",
        )


def _units(path):
    return len(path.encode("utf-16-le", "surrogatepass")) // 2


def _special(path):
    return path.startswith(("\\\\?\\", "\\\\.\\", "\\??\\"))


def _reserved(part):
    stem = part.split(".", 1)[0].split(":", 1)[0].rstrip(" ").upper()
    return stem in ("CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$") or (
        len(stem) == 4
        and stem[:3] in ("COM", "LPT")
        and stem[3] in "123456789\u00b9\u00b2\u00b3"
    )


def _check_components(path):
    # Prefixing must not turn a DOS device or an invalid DOS name into a file.
    _drive, tail = ntpath.splitdrive(path)
    for part in tail.replace("/", "\\").split("\\"):
        if not part or part in (".", ".."):
            continue
        if (
            _reserved(part)
            or part.endswith((".", " "))
            or any(c in part for c in '<>"|?*:')
            or any(ord(c) < 32 for c in part)
        ):
            raise OSError(
                errno.EINVAL,
                "win32lfn refuses extended syntax for a non-portable DOS path",
                path,
            )


def extended_path(path):
    """Keep short paths unchanged; resolve and prefix long DOS/UNC paths.

    Preserve bytes versus str and pass descriptors/invalid types to the caller.
    Existing device and extended namespaces belong to the caller and are opaque.
    ntpath.abspath uses Windows GetFullPathName, including drive-relative paths.
    """
    if isinstance(path, int) or path is None:
        return path
    try:
        path = os.fspath(path)
    except TypeError:
        return path
    text = _decode(path)
    if not text or "\0" in text or _special(text):
        return path
    if not any(c in text for c in ("\\", "/")) and _reserved(text):
        return path
    absolute = ntpath.abspath(text)
    if _units(absolute) < _LIMIT:
        return path
    _check_components(text)
    # A genuine extended current directory can make Windows resolution return
    # an already-extended absolute spelling. Never prefix that spelling twice.
    if _special(absolute):
        return _encode(absolute) if isinstance(path, bytes) else absolute
    _check_components(absolute)
    drive, tail = ntpath.splitdrive(absolute)
    if not drive or (tail and not tail.startswith("\\")):
        raise OSError(
            errno.EINVAL, "win32lfn requires a fully resolved Windows path", path
        )
    if drive.startswith("\\\\"):
        # A UNC root must contain both server and share names.
        if len(drive[2:].split("\\")) != 2 or not all(drive[2:].split("\\")):
            raise OSError(
                errno.EINVAL, "win32lfn requires a UNC server and share", path
            )
        if any(part.endswith((".", " ")) for part in drive[2:].split("\\")):
            raise OSError(
                errno.EINVAL, "win32lfn refuses ambiguous UNC root spelling", path
            )
        absolute = "\\\\?\\UNC\\" + absolute[2:]
    elif len(drive) == 2 and drive[1] == ":":
        absolute = "\\\\?\\" + absolute
    else:
        raise OSError(errno.EINVAL, "win32lfn requires a DOS drive or UNC share", path)
    return _encode(absolute) if isinstance(path, bytes) else absolute


def _is_extended(path):
    return isinstance(path, (str, bytes)) and _decode(path).startswith("\\\\?\\")


class _Patches:
    def __init__(self):
        self.active = True
        self.changes = []

    def replace(self, target, name, replacement):
        original = getattr(target, name)
        setattr(target, name, replacement)
        self.changes.append((target, name, original, replacement))

    def undo(self):
        # Deactivate buried wrappers without removing another extension's patch.
        self.active = False
        for target, name, original, replacement in reversed(self.changes):
            if getattr(target, name) is replacement:
                setattr(target, name, original)


def _wrap_paths(original, parameters, state):
    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        # Windows rejects directory-handle-relative operations. Do not turn an
        # unsupported call into an operation on the process working directory.
        if not state.active or any(
            kwargs.get(k) is not None for k in ("dir_fd", "src_dir_fd", "dst_dir_fd")
        ):
            return original(*args, **kwargs)
        args = list(args)
        for index, name in parameters:
            if index < len(args):
                args[index] = extended_path(args[index])
            elif name in kwargs:
                kwargs[name] = extended_path(kwargs[name])
        return original(*args, **kwargs)

    return wrapped


class _DirEntry:
    def __init__(self, entry, parent):
        self._entry = entry
        self.path = os.path.join(parent, entry.name)

    def __fspath__(self):
        return self.path

    def __getattr__(self, name):
        return getattr(self._entry, name)


class _Scandir:
    def __init__(self, stream, parent):
        self._stream = stream
        self._parent = parent

    def __iter__(self):
        return self

    def __next__(self):
        return _DirEntry(next(self._stream), self._parent)

    def close(self):
        self._stream.close()

    def __enter__(self):
        self._stream.__enter__()
        return self

    def __exit__(self, *args):
        return self._stream.__exit__(*args)


def _wrap_scandir(original, state):
    @functools.wraps(original)
    def scandir(path="."):
        if not state.active:
            return original(path)
        try:
            source = os.fspath(path)
        except TypeError:
            # Descriptors and unsupported types retain the native contract.
            return original(path)
        converted = extended_path(source)
        stream = original(converted)
        if converted != source:
            return _Scandir(stream, source)
        return stream

    return scandir


def _hg_listdir(original, state):
    @functools.wraps(original)
    def listdir(path, stat=False, skip=None):
        if not isinstance(path, bytes):
            return original(path, stat=stat, skip=skip)
        converted = extended_path(path) if state.active else path
        if not state.active or not _is_extended(converted):
            return original(path, stat=stat, skip=skip)
        if skip is not None and not isinstance(skip, bytes):
            raise TypeError("skip must be bytes or None")
        stat = bool(stat)
        result = []
        # Unicode enumeration avoids the ANSI C helper and detects names that
        # cannot be represented in Mercurial's filesystem encoding.
        with os.scandir(_decode(converted)) as entries:
            for entry in entries:
                name = _filename_bytes(entry.name)
                info = entry.stat(follow_symlinks=False)
                kind = statmod.S_IFMT(info.st_mode)
                if name == skip and kind == statmod.S_IFDIR:
                    return []
                result.append((name, kind, info) if stat else (name, kind))
        return sorted(result)

    return listdir


class _WideKernel32:
    """Keep Mercurial's algorithms; adapt its private ANSI filesystem calls."""

    def __init__(self, original, state):
        import ctypes
        from ctypes import wintypes

        self.original = original
        self.state = state
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dll.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.dll.CreateFileW.restype = wintypes.HANDLE
        self.dll.CreateHardLinkW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
        ]
        self.dll.CreateHardLinkW.restype = wintypes.BOOL
        self.dll.SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        self.dll.SetFileAttributesW.restype = wintypes.BOOL
        self.dll.GetVolumePathNameW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        self.dll.GetVolumePathNameW.restype = wintypes.BOOL

    def __getattr__(self, name):
        return getattr(self.original, name)

    def _paths(self, *paths):
        converted = [extended_path(p) for p in paths] if self.state.active else paths
        if self.state.active and any(_is_extended(p) for p in converted):
            return [_decode(p) for p in converted]
        return None

    def CreateFileA(self, path, *args):
        paths = self._paths(path)
        if paths is None:
            return self.original.CreateFileA(path, *args)
        result = self.dll.CreateFileW(paths[0], *args)
        if result == ctypes.c_void_p(-1).value:
            self._raise(path)
        return result

    def CreateHardLinkA(self, dst, src, attrs):
        paths = self._paths(dst, src)
        if paths is None:
            return self.original.CreateHardLinkA(dst, src, attrs)
        result = self.dll.CreateHardLinkW(paths[0], paths[1], attrs)
        if not result:
            self._raise(src)
        return result

    def SetFileAttributesA(self, path, attrs):
        paths = self._paths(path)
        if paths is None:
            return self.original.SetFileAttributesA(path, attrs)
        # Mercurial intentionally treats this attribute update as best-effort.
        return self.dll.SetFileAttributesW(paths[0], attrs)

    def GetVolumePathNameA(self, path, buffer, size):
        paths = self._paths(path)
        if paths is None:
            return self.original.GetVolumePathNameA(path, buffer, size)
        import ctypes

        wide = ctypes.create_unicode_buffer(32768)
        if not self.dll.GetVolumePathNameW(paths[0], wide, len(wide)):
            self._raise(path)
        data = _encode(wide.value) + b"\0"
        if len(data) > size:
            raise OSError(errno.ENAMETOOLONG, "volume path buffer too small", path)
        ctypes.memmove(buffer, data, len(data))
        return 1

    @staticmethod
    def _raise(path):
        import ctypes

        code = ctypes.get_last_error()
        exc = ctypes.WinError(code)
        exc.filename = path
        raise exc


def _hg_posixfile(original, kernel, state):
    @functools.wraps(original)
    def posixfile(name, mode=b"rb", buffering=-1):
        converted = extended_path(name) if state.active else name
        if not state.active or not _is_extended(converted):
            return original(name, mode, buffering)
        import msvcrt

        # Match osutil.posixfile: share deletion and allow atomic rename while
        # readers hold the old revision open. Python open() alone does not.
        if not isinstance(mode, bytes):
            raise TypeError("posixfile mode must be bytes")
        buffering = operator.index(buffering)
        if not -(2**31) <= buffering < 2**31:
            raise OverflowError("buffering does not fit a C int")
        textmode = mode.decode("ascii")
        if textmode not in (
            "r",
            "rb",
            "r+",
            "rb+",
            "r+b",
            "w",
            "wb",
            "w+",
            "wb+",
            "w+b",
            "a",
            "ab",
            "a+",
            "ab+",
            "a+b",
        ):
            raise ValueError("invalid posixfile mode")
        read_only = textmode[0] == "r" and "+" not in textmode
        flags = os.O_RDONLY if read_only else os.O_RDWR
        flags |= os.O_BINARY if "b" in textmode else os.O_TEXT
        if textmode[0] == "a":
            flags |= os.O_APPEND
        creation = {"r": 3, "w": 2, "a": 4}[textmode[0]]
        access = 0x80000000 if read_only else 0xC0000000

        def opener(path, ignored_flags):
            handle = kernel.CreateFileA(
                converted, access, 7, None, creation, 0x80, None
            )
            try:
                return msvcrt.open_osfhandle(handle, flags)
            except BaseException:
                kernel.CloseHandle(handle)
                raise

        # io.open owns the descriptor once opener returns it, including failures
        # while constructing a buffered/text stream. Do not close it twice.
        return io.open(_decode(converted), textmode, buffering, opener=opener)

    return posixfile


def install():
    """Install once on Windows. Return whether this call installed the patches."""
    global _state
    if os.name != "nt" or getattr(os, _STATE, None) is not None:
        return False
    from mercurial import win32, windows

    state = _Patches()
    try:
        kernel = _WideKernel32(win32._kernel32, state)
        state.replace(win32, "_kernel32", kernel)
        # These are cached aliases to the same C/pure module in 7.0.1.
        osutil = windows.osutil
        state.replace(
            osutil, "posixfile", _hg_posixfile(osutil.posixfile, kernel, state)
        )
        for target in (osutil, windows, util):
            state.replace(target, "listdir", _hg_listdir(target.listdir, state))
        one = (
            "stat",
            "lstat",
            "open",
            "mkdir",
            "rmdir",
            "remove",
            "unlink",
            "chmod",
            "utime",
            "listdir",
            "readlink",
        )
        for name in one:
            state.replace(
                os, name, _wrap_paths(getattr(os, name), ((0, "path"),), state)
            )
        state.replace(os, "scandir", _wrap_scandir(os.scandir, state))
        for name in ("rename", "replace", "link"):
            state.replace(
                os,
                name,
                _wrap_paths(getattr(os, name), ((0, "src"), (1, "dst")), state),
            )
        # Only the link location is a filesystem operation; its target is data.
        state.replace(os, "symlink", _wrap_paths(os.symlink, ((1, "dst"),), state))
        for target in (builtins, io):
            state.replace(
                target, "open", _wrap_paths(target.open, ((0, "file"),), state)
            )
    except BaseException:
        state.undo()
        raise
    _state = state
    setattr(os, _STATE, state)
    return True


def uninstall():
    """Undo this module's installation without removing later wrappers."""
    global _state
    if _state is None:
        return
    _state.undo()
    if getattr(os, _STATE, None) is _state:
        delattr(os, _STATE)
    _state = None


def uisetup(ui):
    if ui.configbool(b"win32lfn", b"enabled"):
        install()


def _reparse(info):
    return statmod.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def _identity(info):
    return info.st_dev, info.st_ino, statmod.S_IFMT(info.st_mode)


def _scan(root):
    """Snapshot before deletion, using Unicode for all path structure operations."""
    root = _decode(root)
    info = os.lstat(root)
    if _reparse(info):
        raise error.Abort(b"win32lfn refuses to scan a reparse-point repository root")
    directories = {"": info}
    candidates = []
    pending = [""]
    while pending:
        relative = pending.pop()
        absolute = os.path.join(root, relative)
        with os.scandir(absolute) as stream:
            names = sorted(entry.name for entry in stream)
        # A nested working copy has a different owner. Protect its whole tree.
        if relative and any(name.lower() == ".hg" for name in names):
            candidates = [(p, st) for p, st in candidates if p != relative]
            continue
        for name in names:
            if name.lower() == ".hg":
                continue
            _filename_bytes(name)  # Fail before any deletion if UI cannot name it.
            rel = os.path.join(relative, name)
            full = os.path.join(root, rel)
            # DirEntry.stat has zero st_ino/st_dev on Windows Python 3.9.
            # Use lstat for identities that can be checked again before delete.
            st = os.lstat(full)
            isdir = statmod.S_ISDIR(st.st_mode)
            link = _reparse(st)
            if _units(full) >= (248 if isdir else 260):
                candidates.append((rel, st))
            if isdir and not link:
                directories[rel] = st
                pending.append(rel)
    candidates.sort(key=lambda item: (-item[0].count(os.sep), item[0]))
    return candidates, directories


def _check_ancestors(root, relative, directories):
    parent = os.path.dirname(relative)
    while True:
        current = os.lstat(os.path.join(root, parent))
        if _reparse(current) or _identity(current) != _identity(directories[parent]):
            raise error.Abort(
                b"win32lfn directory changed during cleanup; rerun the command"
            )
        if not parent:
            break
        parent = os.path.dirname(parent)


def _clean(ui, repo, force):
    with repo.wlock():
        root = _decode(repo.root)
        candidates, directories = _scan(root)
        protected = set()
        for path in repo.dirstate:
            local = os.path.normcase(_decode(path).replace("/", os.sep))
            protected.add(local)
            parent = os.path.dirname(local)
            while parent:
                protected.add(parent)
                parent = os.path.dirname(parent)
        # Protect filesystem aliases too, including case variants and hardlinks.
        # Missing tracked entries remain protected by name. Other errors abort.
        identities = set()
        for relative in protected:
            try:
                identities.add(_identity(os.lstat(os.path.join(root, relative))))
            except (FileNotFoundError, NotADirectoryError):
                pass
        remaining = False
        for relative, before in candidates:
            path = os.path.join(root, relative)
            display = _encode(path)
            if (
                os.path.normcase(relative) in protected
                or _identity(before) in identities
                or _reparse(before)
            ):
                ui.warn(b"protected: " + display + b"\n")
                remaining = True
                continue
            if (
                not force
                and ui.promptchoice(b"Delete %s? $$ &No $$ &Yes" % display, default=0)
                != 1
            ):
                remaining = True
                continue
            _check_ancestors(root, relative, directories)
            current = os.lstat(path)
            changed = _identity(current) != _identity(before)
            if not statmod.S_ISDIR(before.st_mode):
                changed |= (current.st_size, current.st_mtime_ns) != (
                    before.st_size,
                    before.st_mtime_ns,
                )
            if _reparse(current) or changed:
                raise error.Abort(
                    b"win32lfn entry changed during cleanup; rerun the command"
                )
            if statmod.S_ISDIR(current.st_mode):
                try:
                    os.rmdir(path)
                except OSError as exc:
                    if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                        raise
                    ui.warn(b"not empty: " + display + b"\n")
                    remaining = True
                    continue
            else:
                os.unlink(path)
            ui.write(b"deleted: " + display + b"\n")
        return int(remaining)


@command(
    b"lfn",
    [
        (b"c", b"clean", False, b"prompt to delete long untracked paths"),
        (b"f", b"force", False, b"delete without prompts, requires --clean"),
    ],
    b"hg lfn [--clean [--force]]",
)
def lfn(ui, repo, **opts):
    """report long working-copy paths or delete untracked entries

    Cleanup includes ignored files. It protects tracked paths, .hg metadata,
    nested repositories and reparse points. It removes only individual files
    and empty directories. Back up the working copy before using --clean.
    """
    if opts.get("force") and not opts.get("clean"):
        raise error.Abort(b"--force requires --clean")
    if opts.get("clean"):
        return _clean(ui, repo, opts.get("force", False))
    candidates, unused = _scan(repo.root)
    for relative, info in candidates:
        ui.write(_encode(os.path.join(_decode(repo.root), relative)) + b"\n")
    return 0
