# 🌌 Nova Console

[![100% Offline Localhost](https://img.shields.io/badge/Network-100%25%20Offline-success?style=flat-square)](https://github.com/ad4rshp/nova-console)
[![Zero Telemetry](https://img.shields.io/badge/Telemetry-Zero-blue?style=flat-square)](https://github.com/ad4rshp/nova-console)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![No Login](https://img.shields.io/badge/Account-No%20Login-orange?style=flat-square)](https://github.com/ad4rshp/nova-console)

**Nova Console** is an open-source local AI workstation, hardware telemetry monitor, and usage-tracking proxy. Monitor GPU/VRAM load in real time, tune context with 1-click hardware presets, chat with local models, and track token usage from Cursor and Continue.

Works on **Windows, macOS, and Linux** with **Ollama, LM Studio, vLLM, and LocalAI**.

![Nova Console Dashboard](docs/screenshots/dashboard_overview.png)

---

## Quickstart

### Windows
Run in PowerShell (no Git or manual setup required):
```powershell
irm https://raw.githubusercontent.com/ad4rshp/nova-console/main/setup_windows.bat -OutFile setup.bat; .\setup.bat
```
*Or download the **[Source Zip](https://github.com/ad4rshp/nova-console/archive/refs/heads/main.zip)**, extract, and double-click `setup_windows.bat`.*

### macOS & Linux
Run in Terminal:
```bash
curl -fsSL https://raw.githubusercontent.com/ad4rshp/nova-console/main/setup_unix.sh | bash
```

### From Source (All Platforms)
```bash
git clone https://github.com/ad4rshp/nova-console.git
cd nova-console
pip install -r requirements.txt
python launch.py
```

*Pre-compiled standalone `.exe` binaries are also available on [GitHub Releases](https://github.com/ad4rshp/nova-console/releases).*

---

## 🛡️ Trust & Privacy Guarantee

* **100% Offline (`127.0.0.1`)**: Binds strictly to local loopback. No open LAN ports, no cloud dependencies.
* **Zero Telemetry**: No analytics, no tracking pixels, no user fingerprinting, and no account required.
* **100% Auditable Code**: Pure unminified Python (FastAPI) and modern JavaScript.
* **Zero Background RAM**: When closed, it exits completely. No background daemons or hidden tray miners.
* **Terminal Sandbox**: Nova Chat can propose commands, but **never** runs them without your explicit approval modal.

![Trust & Privacy Transparency](docs/screenshots/trust_privacy_modal.png)

---

## ✨ Features

* **Real-Time VRAM & Hardware Telemetry**: Live GPU VRAM, temperature, RAM usage, and disk headroom with sparklines.
* **CPU/GPU Split Offload Alerts**: Detects when large models spill from VRAM into slower system RAM and suggests optimal context size.
* **1-Click Hardware Presets**:
  * **Low (2K)**: For integrated graphics / <6 GB VRAM (prevents paging).
  * **Medium (4K)**: Balanced everyday coding profile (6–8 GB VRAM).
  * **High (8K)**: Deep reasoning profile for 12+ GB VRAM.
* **Interactive Chat Drawer**: Multimodal chat (images & voice), code execution sandbox with 1-click **Run Python**, and thinking reasoning viewer.
* **Zero-RAM Update Checker**: Header lights up when a new version is released on GitHub with 0 MB idle RAM footprint.

![Nova Chat Interface](docs/screenshots/chat_interface.png)

---

## 🔌 Connect Cursor, Continue, or Python

Route any OpenAI-compatible client through Nova Console (`http://127.0.0.1:8080/v1`) to track tokens/sec, latency, and request logs in SQLite:

### Cursor
Set **Override OpenAI Base URL** to `http://127.0.0.1:8080/v1`, enter dummy key `nova-local`, and pick your installed model (e.g. `llama3.2:latest`).

### Continue.dev (`config.json`)
```json
{
  "models": [{
    "title": "Nova Console",
    "provider": "openai",
    "model": "llama3.2:latest",
    "apiBase": "http://127.0.0.1:8080/v1",
    "apiKey": "nova-local"
  }]
}
```

### Python
```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="nova-local")
response = client.chat.completions.create(model="llama3.2:latest", messages=[{"role": "user", "content": "Hello!"}])
print(response.choices[0].message.content)
```

---

## ⚙️ Configuration (`.env`)

*Works out of the box with zero configuration.* To change defaults, create a `.env` file:

```ini
NOVA_BACKEND_URL=http://127.0.0.1:11434   # Ollama: 11434 | LM Studio: 1234 | vLLM: 8000
NOVA_PORT=8080                          # Dashboard port
NOVA_NO_BROWSER=0                       # Set to 1 to disable auto-opening browser
```

---

## 📄 License
MIT License. Free and open source forever.
