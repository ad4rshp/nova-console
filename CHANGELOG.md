# Changelog

All notable changes to Nova Console are documented in this file.

## [2.1.0] - 2026-11-13

### Security Hardening
- **Strict LAN Origin Verification**: Eliminated permissive origin fallback in LAN mode; exact scheme, hostname, and port matching is required against the trusted origins list. Arbitrary non-loopback origins are strictly rejected.
- **Private Route Authentication**: Enforced authentication for conversation history retrieval and clearing (`/api/chat-history`) whenever LAN mode or authentication is required.
- **Upstream Credential Stripping**: Nova's administrative tokens (`Authorization: Bearer`, `X-Nova-Auth`) are stripped before forwarding requests to the upstream LLM backend proxy.
- **Streaming Request Body Size Enforcement**: Byte limits are continuously monitored during stream consumption, preventing bypasses via chunked transfer without `Content-Length`.
- **Network Binding Enforcement**: Binding to non-loopback addresses (`0.0.0.0`, LAN IPs) strictly requires `NOVA_ALLOW_LAN=1`.
- **SSRF Mitigation**: Backend URL validation rejects non-HTTP/HTTPS schemes, link-local addresses, and cloud metadata endpoints (`169.254.169.254`).
- **Terminal Isolation & Resource Limits**: Restricted execution environment with POSIX `setrlimit` limits (CPU, memory, file size, process count), Windows process group isolation, sanitized environment variables (all host secrets stripped), single-use cryptographic approval tokens (`secrets.token_urlsafe(32)`), and opt-in execution flags (`NOVA_DISABLE_TERMINAL=1`, `NOVA_ENABLE_TERMINAL_LAN=1`).
- **Admin Credential Protection**: Removed credential extraction from URL query parameters (`?token=`), and filtered internal administrative tokens from `/api/settings` and `/api/dashboard` responses.
- **Output & Error Sanitization**: Added automatic scrubbing of bearer tokens, API keys, and internal exception traces in 500/502 responses.

### Architecture & Engine Support
- **Asynchronous Provider Detection**: Connected `detect_provider()` directly to chat routes and startup lifespan, probing endpoints and response headers instead of relying on port heuristics.
- **Structured Chat Payload Validation**: Enforced Pydantic V2 validation with bounds on message count, text length, images, and model name identifiers.
- **Bounded Multi-Category Rate Limiter**: Added bounded storage with stale key pruning and endpoint-specific thresholds (`chat`, `proxy`, `admin`).
- **Universal Provider Adapters**: Added pluggable adapters for Ollama, LM Studio, vLLM, LocalAI, and llama.cpp (`llama-server`).
- **Capability Introspection**: Each provider declares its supported capabilities (`vram_eviction`, `slots_monitoring`, `thinking_extraction`) to distinguish zero metrics from unsupported features.
- **Incremental SSE Parsing**: Fixed streaming proxy chunk-boundary splitting with an incremental event buffer.
- **Hardware Telemetry**: Added multi-GPU enumeration and aggregation for NVIDIA GPUs, typed numeric metrics, and explicit distinction between dedicated VRAM and Apple Silicon / host shared memory.

### Data Integrity & Reliability
- **Chat History Ordering**: Fixed chat message retrieval to return the latest messages in chronological order.
- **Database Retention Policies**: Added automatic pruning for records older than 30 days and table row caps to prevent unbounded database growth.
- **WAL Checkpointing**: Added automated SQLite WAL checkpoints on startup and shutdown.
- **Side-Effect Free Imports**: Removed module-level database initialization on import.

### CI/CD & Testing
- **Expanded Test Suite**: Grew automated test coverage to 52 unit, integration, and security regression tests across all core systems.
- **Static Analysis**: Configured Ruff linter and Bandit security scanner in `pyproject.toml` and GitHub Actions workflow.
- **Multi-OS & Python Matrix**: Extended CI testing to Ubuntu, Windows, macOS across Python 3.10, 3.11, and 3.12.
