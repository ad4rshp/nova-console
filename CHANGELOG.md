# Changelog

All notable changes to Nova Console are documented in this file.

## [2.1.0] - 2026-11-13

### Security Hardening
- **Network Binding Enforcement**: Binding to non-loopback addresses (`0.0.0.0`, LAN IPs) now strictly requires `NOVA_ALLOW_LAN=1`.
- **SSRF Mitigation**: Backend URL validation rejects non-HTTP/HTTPS schemes, link-local addresses, and cloud metadata endpoints (`169.254.169.254`).
- **Deep CSRF Protection**: Origin validation verifies scheme, hostname, and port on all state-changing endpoints, rejecting mismatched origins and missing origins on unauthenticated calls.
- **Terminal Sandbox Isolation**: Added restricted PATH execution, `-NonInteractive` PowerShell execution, `--noprofile --norc [--restricted]` bash execution, subshell chaining prevention (`NOVA_TERMINAL_SANDBOX=strict`), and execution concurrency caps.
- **Admin Credential Protection**: Removed credential extraction from URL query parameters (`?token=`), and filtered internal administrative tokens from `/api/settings` and `/api/dashboard` responses.
- **Output & Error Sanitization**: Added automatic scrubbing of bearer tokens, API keys, and internal exception traces in 500/502 responses.

### Architecture & Engine Support
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
- **Expanded Test Suite**: Grew automated test coverage to 46 unit, integration, and security regression tests across all core systems.
- **Static Analysis**: Configured Ruff linter and Bandit security scanner in `pyproject.toml` and GitHub Actions workflow.
- **Multi-OS & Python Matrix**: Extended CI testing to Ubuntu, Windows, macOS across Python 3.10, 3.11, and 3.12.
