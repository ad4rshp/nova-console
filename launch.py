#!/usr/bin/env python3
"""
Nova Console Universal Launcher
Cross-platform entrypoint for Windows, macOS, and Linux.
"""
import os
import sys
import time
import webbrowser
from pathlib import Path

# Verify Python version
if sys.version_info < (3, 10):
    print("Error: Nova Console requires Python 3.10 or higher.")
    print(f"Current version: {sys.version}")
    sys.exit(1)

# Ensure app directory is on path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    from app.config import PORT, HOST, LLM_BACKEND_URL, NOVA_ALLOW_LAN
except ValueError as e:
    print("\n" + "=" * 60)
    print(f"  [SECURITY CONFIGURATION ERROR] {e}")
    print("  To permit binding to a non-loopback or LAN interface, run:")
    print("    set NOVA_ALLOW_LAN=1    (Windows Command Prompt)")
    print("    $env:NOVA_ALLOW_LAN=1  (Windows PowerShell)")
    print("    export NOVA_ALLOW_LAN=1 (Linux/macOS)")
    print("=" * 60 + "\n")
    sys.exit(1)

import uvicorn

def main():
    print("=" * 60)
    print("  🚀 Starting Nova Console (Local AI Workstation)")
    print(f"  • Network Binding:    {HOST}:{PORT}")
    print(f"  • Local Dashboard:    http://127.0.0.1:{PORT}")
    print(f"  • API Proxy Gateway:  http://127.0.0.1:{PORT}/v1")
    print(f"  • Interactive Docs:   http://127.0.0.1:{PORT}/docs")
    print(f"  • Inference Backend:  {LLM_BACKEND_URL}")
    if NOVA_ALLOW_LAN or HOST in ("0.0.0.0", "::"):
        print("  ⚠️  WARNING: LAN access is ENABLED (0.0.0.0).")
        print("      Anyone on your local network can reach your dashboard.")
    else:
        print("  🛡️  Loopback Isolation: 127.0.0.1 (Localhost Only)")
    print("=" * 60)

    # Optional: open browser after brief delay
    if os.environ.get("NOVA_NO_BROWSER", "0") != "1":
        def open_browser():
            time.sleep(1.2)
            webbrowser.open(f"http://127.0.0.1:{PORT}")
        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    # Run Uvicorn ASGI server
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False
    )

if __name__ == "__main__":
    main()

