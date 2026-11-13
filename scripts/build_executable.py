#!/usr/bin/env python3
"""
Nova Console Standalone Executable Builder
Uses PyInstaller to package Nova Console into a standalone executable for Windows, macOS, or Linux.
Usage:
    python scripts/build_executable.py
"""
import sys
import os
import platform
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def build():
    print("=" * 60)
    print("  📦 Nova Console Standalone Executable Builder")
    print(f"  • Platform: {platform.system()} ({platform.machine()})")
    print(f"  • Base Directory: {BASE_DIR}")
    print("=" * 60)

    # 1. Verify PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("Installing pyinstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Determine OS separator for data files (; on Windows, : on Unix)
    sep = ";" if platform.system() == "Windows" else ":"

    # 3. Assemble PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "NovaConsole",
        "--clean",
        "--onefile",
        # Include data files
        "--add-data", f"{BASE_DIR / 'static'}{sep}static",
        "--add-data", f"{BASE_DIR / 'app'}{sep}app",
        # Hidden imports for FastAPI / Uvicorn
        "--hidden-import", "uvicorn",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespans",
        "--hidden-import", "uvicorn.lifespans.on",
        "--hidden-import", "pydantic",
        "--hidden-import", "httpx",
        "--hidden-import", "psutil",
        str(BASE_DIR / "launch.py")
    ]

    print("\nRunning PyInstaller command:")
    print(" ".join(cmd))
    print("\nCompiling... please wait.\n")

    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode == 0:
        exe_name = "NovaConsole.exe" if platform.system() == "Windows" else "NovaConsole"
        dist_path = BASE_DIR / "dist" / exe_name
        print("\n" + "=" * 60)
        print(f"  🎉 SUCCESS! Standalone binary built:")
        print(f"  {dist_path}")
        print("=" * 60)
    else:
        print("\nBuild failed with exit code:", result.returncode)

if __name__ == "__main__":
    build()

