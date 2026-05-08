# release_mac.py — macOS build & package script
import os, shutil, subprocess, sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(PROJECT_DIR, "backend")

def main():
    # 1. Kill any running instance
    subprocess.run(["pkill", "-f", "ebook-pdf-downloader"], capture_output=True)

    # 2. Build with PyInstaller
    spec = os.path.join(BACKEND_DIR, "book-downloader-mac.spec")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", spec], cwd=BACKEND_DIR, check=True)

    # 3. Copy .app to dist/
    app_src = os.path.join(BACKEND_DIR, "dist", "ebook-pdf-downloader.app")
    dist_dir = os.path.join(PROJECT_DIR, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    if os.path.exists(app_src):
        app_dst = os.path.join(dist_dir, "ebook-pdf-downloader.app")
        if os.path.exists(app_dst):
            shutil.rmtree(app_dst)
        shutil.move(app_src, app_dst)
        print(f"App built: {app_dst}")

    # 4. Create .dmg
    dmg_path = os.path.join(dist_dir, "ebook-pdf-downloader.dmg")
    subprocess.run(["hdiutil", "create", "-volname", "Ebook PDF Downloader",
                    "-srcfolder", app_dst, "-ov", "-format", "UDZO", dmg_path], check=True)
    print(f"DMG: {dmg_path}")

if __name__ == "__main__":
    main()
