# Nova Console

Local hardware monitor, web UI, and OpenAI-compatible proxy for local LLM backends (Ollama, LM Studio, vLLM, LocalAI, llama.cpp).

![Nova Console Dashboard](docs/screenshots/dashboard_overview.png)

An interactive animated tutorial demonstrating telemetry monitoring, context presets, streaming generation, and command sandboxing is available at [docs/showcase/tutorial.html](docs/showcase/tutorial.html).

## Installation

### Windows
```powershell
Invoke-WebRequest -Uri https://raw.githubusercontent.com/ad4rshp/nova-console/main/setup_windows.bat -OutFile setup.bat; .\setup.bat
```

### macOS & Linux
```bash
curl -fsSL https://raw.githubusercontent.com/ad4rshp/nova-console/main/setup_unix.sh | bash
```

### Manual
```bash
git clone https://github.com/ad4rshp/nova-console.git
cd nova-console
pip install -r requirements.txt
python launch.py
```

## Features

- **Hardware Monitoring**: Real-time GPU VRAM, temperature, RAM, and disk metrics.
- **Context Presets**: Context profiles (2K, 4K, 8K) to manage VRAM allocation.
- **Proxy & Metrics**: OpenAI-compatible endpoint (`/v1`) logging latency, tokens/sec, and token counts to SQLite.
- **Web Chat**: Chat interface with model switching, system prompts, parameter tuning, and terminal execution with approval confirmation.

## OpenAI-Compatible Proxy (`/v1`)

Point OpenAI-compatible tools to `http://127.0.0.1:8080/v1` (API key: `nova-local` or your `NOVA_ADMIN_KEY`).

### Cursor
Set **Override OpenAI Base URL** to `http://127.0.0.1:8080/v1`.

### Continue (`config.json`)
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
response = client.chat.completions.create(
    model="llama3.2:latest",
    messages=[{"role": "user", "content": "Hello"}]
)
print(response.choices[0].message.content)
```

## Configuration

Set environment variables or use a `.env` file:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `NOVA_HOST` | `127.0.0.1` | Bind address. Non-loopback addresses require `NOVA_ALLOW_LAN=1`. |
| `NOVA_PORT` | `8080` | Port for web UI and proxy. |
| `NOVA_ALLOW_LAN` | `0` | Set to `1` to allow non-loopback binding. Enforces authentication on sensitive routes. |
| `NOVA_ADMIN_KEY` | *(auto-generated)* | Admin key for authenticated routes and terminal execution. |
| `NOVA_REQUIRE_AUTH` | `0` | Set to `1` to enforce authentication on loopback as well. |
| `NOVA_DISABLE_TERMINAL` | `0` | Set to `1` to disable terminal command execution. |
| `NOVA_BACKEND_URL` | `http://127.0.0.1:11434` | Backend LLM server URL (Ollama, LM Studio, vLLM, LocalAI, llama.cpp). |
| `NOVA_NO_BROWSER` | `0` | Set to `1` to prevent opening the browser on launch. |
| `NOVA_CHECK_UPDATES` | `1` | Set to `0` to disable GitHub release check. |

## Security

- **Loopback Default**: Binds to `127.0.0.1`. Non-loopback addresses fail startup unless `NOVA_ALLOW_LAN=1` is set.
- **Terminal Execution**: Restricted execution environment with resource limits (POSIX setrlimit / Windows process group), directory confinement, sanitized environment variables, single-use cryptographic approval tokens, and server user authorization. Catastrophic commands are blocked.
- **LAN Protection**: When `NOVA_ALLOW_LAN=1` is enabled, sensitive endpoints (`/api/terminal/*`, `/api/modelfile`, `/api/settings`, `/api/chat-history`, `/v1/*`) require `Authorization: Bearer <token>` or `X-Nova-Auth`. Arbitrary non-loopback origins are strictly rejected.
- **Credential Stripping**: Nova's administrative credentials are never forwarded upstream to the backend inference server.
- **Browser Protection**: Strict CSRF origin checking on mutating endpoints and security headers (`nosniff`, `SAMEORIGIN`).

## License

MIT
