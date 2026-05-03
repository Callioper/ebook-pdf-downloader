import os
import subprocess
import sys
from pathlib import Path


def build():
    project_root = Path(__file__).resolve().parent

    frontend_dir = project_root / "frontend"
    if frontend_dir.exists() and (frontend_dir / "package.json").exists():
        print("[1/3] Building frontend...")
        subprocess.run(["npm", "run", "build"], cwd=str(frontend_dir), check=True)
    else:
        print("[1/3] Skipping frontend build (no frontend/package.json)")

    backend_dir = project_root / "backend"
    spec_file = backend_dir / "book-downloader.spec"

    print("[2/3] Installing backend requirements...")
    req_file = backend_dir / "requirements.txt"
    if req_file.exists():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
            check=True,
        )

    print("[3/3] Building executable with PyInstaller...")
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--distpath", str(backend_dir / "dist"),
            "--workpath", str(backend_dir / "build"),
            "--specpath", str(backend_dir),
            str(spec_file),
        ],
        check=True,
        cwd=str(backend_dir),
    )

    print(f"Build complete! Output: {backend_dir / 'dist' / 'BookDownloader.exe'}")


if __name__ == "__main__":
    build()
