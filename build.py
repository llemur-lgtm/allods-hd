"""Build allods-hd-patch.exe with PyInstaller and pack the release archive.

    pip install -r requirements-build.txt
    python build.py
"""
import os
import shutil
import subprocess
import sys
import zipfile

from patch import __version__

ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(ROOT, "build")
RELEASE = os.path.join(ROOT, "release")
EXE_NAME = "allods-hd-patch"

RELEASE_FILES = {
    # path in the archive: path in the repository
    "allods-hd-patch.exe": os.path.join(BUILD, "dist", EXE_NAME + ".exe"),
    "ddraw.dll": os.path.join(ROOT, "third_party", "cnc-ddraw", "ddraw.dll"),
    "ddraw.ini": os.path.join(ROOT, "game", "ddraw.ini"),
    "patch.py": os.path.join(ROOT, "patch.py"),
    "README.md": os.path.join(ROOT, "README.md"),
    "README.en.md": os.path.join(ROOT, "README.en.md"),
    "LICENSE.txt": os.path.join(ROOT, "LICENSE"),
    "LICENSE-cnc-ddraw.txt": os.path.join(ROOT, "third_party", "cnc-ddraw", "LICENSE"),
}


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--clean",
        "--name", EXE_NAME,
        "--distpath", os.path.join(BUILD, "dist"),
        "--workpath", os.path.join(BUILD, "work"),
        "--specpath", BUILD,
        os.path.join(ROOT, "patch.py"),
    ], check=True)

    os.makedirs(RELEASE, exist_ok=True)
    archive = os.path.join(RELEASE, f"allods-hd-{__version__}.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, path in RELEASE_FILES.items():
            zf.write(path, name)
    print(archive)


if __name__ == "__main__":
    main()
