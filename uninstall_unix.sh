#!/usr/bin/env bash
# Nova Console Complete System Uninstaller (macOS & Linux)
set -e

echo "========================================================"
echo "       Nova Console - Complete System Uninstaller"
echo "========================================================"
echo ""

FORCE=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes|-f|--force)
            FORCE=1
            ;;
    esac
done

if [ "$FORCE" -eq 0 ]; then
    echo "This utility will completely remove Nova Console from your system:"
    echo "  - Stop active Nova Console processes"
    echo "  - Delete installation directory: \$HOME/.local/share/nova-console"
    echo "  - Remove launcher script: \$HOME/.local/bin/nova-console"
    echo "  - Remove application desktop entry (Linux)"
    echo "  - Remove configuration directory: \$HOME/.config/nova-console"
    echo "  - Clean temporary setup cache in /tmp"
    echo ""
    read -rp "Are you sure you want to completely uninstall Nova Console? (y/N): " CONFIRM
    case "$CONFIRM" in
        [yY]|[yY][eE][sS])
            ;;
        *)
            echo "[!] Uninstallation cancelled by user."
            exit 0
            ;;
    esac
fi

echo ""
echo "[*] Step 1/5: Stopping active Nova Console processes..."
pkill -f "launch.py" 2>/dev/null || true
pkill -f "nova-console" 2>/dev/null || true
echo "[OK] Processes stopped."

echo "[*] Step 2/5: Removing installation directory..."
INSTALL_DIR="$HOME/.local/share/nova-console"
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo "  [-] Removed: $INSTALL_DIR"
else
    echo "  [-] $INSTALL_DIR not found (already clean)."
fi
echo "[OK] Installation directory removed."

echo "[*] Step 3/5: Removing launcher binary and desktop shortcuts..."
BIN_FILE="$HOME/.local/bin/nova-console"
if [ -f "$BIN_FILE" ]; then
    rm -f "$BIN_FILE"
    echo "  [-] Removed launcher: $BIN_FILE"
fi

DESKTOP_FILE="$HOME/.local/share/applications/nova-console.desktop"
if [ -f "$DESKTOP_FILE" ]; then
    rm -f "$DESKTOP_FILE"
    echo "  [-] Removed desktop entry: $DESKTOP_FILE"
fi
echo "[OK] Shortcuts and launchers removed."

echo "[*] Step 4/5: Removing configuration directory..."
CONFIG_DIR="$HOME/.config/nova-console"
if [ -d "$CONFIG_DIR" ]; then
    rm -rf "$CONFIG_DIR"
    echo "  [-] Removed: $CONFIG_DIR"
fi
echo "[OK] Configuration cleaned."

echo "[*] Step 5/5: Cleaning temporary installation files..."
rm -rf /tmp/nova-console* 2>/dev/null || true
rm -rf /tmp/nova-src* 2>/dev/null || true

# Check if run from a local repository clone and clean repo artifacts if present
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
if [ -f "$SCRIPT_DIR/nova-dashboard.db" ]; then
    rm -f "$SCRIPT_DIR/nova-dashboard.db*" 2>/dev/null || true
    echo "  [-] Removed local repository database files."
fi

echo ""
echo "========================================================"
echo "  🎉 Nova Console has been completely uninstalled!"
echo "  All application files, shortcuts, and data were removed."
echo "========================================================"
echo ""
exit 0
