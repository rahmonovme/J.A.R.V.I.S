"""
Build J.A.R.V.I.S into a standalone JARVIS.exe

Usage:
    python build.py

Requirements:
    pip install pyinstaller

Output:
    dist/JARVIS.exe
"""

import subprocess
import sys
import shutil
import os
from pathlib import Path
BASE = Path(__file__).resolve().parent

def build():
    import platform
    exe_name = "JARVIS.exe" if platform.system() == "Windows" else "JARVIS"
    print("=" * 50)
    print(f"  Building {exe_name}")
    print("=" * 50)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "JARVIS",
        "--icon", f"static{os.sep}icon.ico",
        "--noconsole",                        # No terminal window
        "--add-data", f"static{os.sep}*{os.pathsep}static",   # Bundle web UI
        "--add-data", f"core{os.sep}*{os.pathsep}core",        # Bundle prompts
        "--add-data", f"config{os.sep}*{os.pathsep}config",    # Bundle config (if any)
        "--add-data", f"memory{os.sep}*{os.pathsep}memory",
        "--add-data", f"actions{os.sep}*{os.pathsep}actions",
        "--add-data", f"agent{os.sep}*{os.pathsep}agent",
        "--hidden-import", "aiohttp",
        "--hidden-import", "webview",
        "--hidden-import", "pyaudio",
        "--hidden-import", "google.genai",
        "--hidden-import", "PIL",
        str(BASE / "main.py"),
    ]

    print(f"\nRunning: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(BASE))

    if result.returncode == 0:
        exe_name = "JARVIS.exe" if "win" in sys.platform else "JARVIS"
        exe = BASE / "dist" / exe_name
        if exe.exists():
            print(f"\nBuild successful!")
            print(f"  Output: {exe}")
            print(f"  Size:   {exe.stat().st_size / 1024 / 1024:.1f} MB")
            print(f"\nProcess name in Task Manager: {exe_name}")
        else:
            print("\nBuild completed but exe not found in dist/")
    else:
        print(f"\nBuild failed with exit code {result.returncode}")

    return result.returncode


if __name__ == "__main__":
    import os
    sys.exit(build())
