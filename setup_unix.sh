#!/usr/bin/env bash
# Nova Console Unix 1-Click Installer (macOS & Linux)
set -e

echo "========================================================"
echo "         Nova Console - Setup Wizard"
echo "========================================================"

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3.10 or higher is required."
    echo "Please install python3 using your package manager (brew, apt, dnf)."
    exit 1
fi

INSTALL_DIR="$HOME/.local/share/nova-console"
BIN_DIR="$HOME/.local/bin"

echo "[*] Target Directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

SRC_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

if [ ! -d "$SRC_DIR/app" ]; then
    echo "[*] Standalone web runner detected. Fetching latest Nova Console from GitHub..."
    TMP_DIR=$(mktemp -d)
    curl -fsSL https://github.com/ad4rshp/nova-console/archive/refs/heads/main.tar.gz | tar -xz -C "$TMP_DIR"
    cp -R "$TMP_DIR/nova-console-main/"* "$INSTALL_DIR/"
    rm -rf "$TMP_DIR"
else
    echo "[*] Copying application files..."
    cp -R "$SRC_DIR/app" "$INSTALL_DIR/"
    cp -R "$SRC_DIR/static" "$INSTALL_DIR/"
    cp "$SRC_DIR/dashboard.html" "$INSTALL_DIR/"
    cp "$SRC_DIR/launch.py" "$INSTALL_DIR/"
    cp "$SRC_DIR/requirements.txt" "$INSTALL_DIR/"
    cp "$SRC_DIR/.env.example" "$INSTALL_DIR/" 2>/dev/null || true
    [ -f "$SRC_DIR/Modelfile" ] && cp "$SRC_DIR/Modelfile" "$INSTALL_DIR/"
fi

cd "$INSTALL_DIR"

if [ ! -d ".venv" ]; then
    echo "[*] Creating virtual environment..."
    python3 -m venv .venv
fi

echo "[*] Installing dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet -r requirements.txt

# Create runner script in ~/.local/bin/nova-console
cat << 'EOF' > "$BIN_DIR/nova-console"
#!/usr/bin/env bash
DIR="$HOME/.local/share/nova-console"
cd "$DIR"
exec "$DIR/.venv/bin/python3" "$DIR/launch.py" "$@"
EOF

chmod +x "$BIN_DIR/nova-console"

# Linux Desktop Entry (.desktop)
if [ "$(uname)" = "Linux" ]; then
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    cat << EOF > "$DESKTOP_DIR/nova-console.desktop"
[Desktop Entry]
Name=Nova Console
Comment=Local AI Workstation & Hardware Monitor
Exec=$BIN_DIR/nova-console
Terminal=false
Type=Application
Categories=Development;Utility;
EOF
    echo "[*] Desktop entry created at $DESKTOP_DIR/nova-console.desktop"
fi

echo ""
echo "========================================================"
echo "  🎉 Installation Complete!"
echo "  Run anywhere via: nova-console"
echo "========================================================"
echo ""
"$BIN_DIR/nova-console"


