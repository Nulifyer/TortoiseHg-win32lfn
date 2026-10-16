"""Create a source/install ZIP with one extension implementation."""

import hashlib
import zipfile
from pathlib import Path

project = Path(__file__).resolve().parents[1]
files = [project / name for name in ("win32lfn.py", "README.md", "LICENSE")]
files += sorted((project / "docs").rglob("*.md"))
files += sorted((project / "docs" / "evidence").glob("*.json"))
files += sorted((project / "docs" / "evidence").glob("*.png"))
files += sorted((project / "tests").glob("test_*.py"))
files += [project / "tests" / "run_windows.py", Path(__file__).resolve()]
output = project / "dist"
output.mkdir(exist_ok=True)
archive = output / "win32lfn-0.1.0.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
    for path in files:
        stream.write(path, path.relative_to(project).as_posix())
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / "SHA256SUMS").write_text(
    "%s  %s\n" % (checksum, archive.name), encoding="ascii"
)
print("%s  %s" % (checksum, archive))
