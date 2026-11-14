# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :--- |
| 2.1.x | Yes |
| < 2.0.0 | No |

## Threat Model & Security Boundaries

Nova Console is designed as a local-first workstation for developers running local LLMs. It features defense-in-depth protections designed to prevent unauthorized local or remote access.

### 1. Network Exposure & Binding Policy
- **Loopback Default**: By default, Nova Console binds strictly to `127.0.0.1`.
- **LAN Protection**: Binding to any non-loopback address (including `0.0.0.0`, LAN IPs, or public interfaces) is blocked by default and requires explicit opt-in via `NOVA_ALLOW_LAN=1`.
- **Mandatory LAN Authentication**: When LAN mode is active, sensitive endpoints (terminal execution, modelfile modifications, settings, chat history retrieval/clearing, model unloading, rebuilds, and the OpenAI proxy) require an `Authorization: Bearer <token>` or `X-Nova-Auth` header.
- **Credential Stripping**: Nova's administrative credentials are never forwarded upstream to the configured LLM backend.

### 2. Browser Security & CSRF
- **Strict CSRF Origin Verification**: All state-changing requests (`POST`, `PUT`, `DELETE`, `PATCH`) to `/api/` endpoints must present valid `Origin` or `Referer` headers matching the server's configured scheme, hostname, and port (`127.0.0.1:{PORT}`, `localhost:{PORT}`, or configured `NOVA_CORS_ORIGINS`). Arbitrary non-loopback origins are strictly rejected even in LAN mode.
- **Security Headers**: Standard defense-in-depth HTTP headers are sent on all responses:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: SAMEORIGIN`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(), microphone=(self), geolocation=()`

### 3. Backend SSRF Protection
- **Target URL Validation**: The configured inference backend URL (`NOVA_BACKEND_URL`) is validated against SSRF attacks:
  - Only `http://` and `https://` schemes are permitted.
  - Access to cloud metadata services (`169.254.169.254`, `metadata.google.internal`) is strictly blocked.
  - Link-local, multicast, and reserved IP ranges are rejected.

### 4. Terminal Security, Process Isolation & Container Boundary
Terminal execution is a privileged feature intended for local workstation control.

> [!IMPORTANT]
> **OS Privilege Disclosure**: When executing commands directly on the host (Windows / Linux / macOS), commands run with the operating system privileges of the Nova Console user. While host guardrails (workspace confinement, environment sanitization, process limits, and command allowlists) protect against accidental damage, **host subprocess execution is not a full OS container boundary**. For untrusted or shared environments, enable Docker container isolation (`NOVA_REQUIRE_CONTAINER=1`).

- **OS Container Isolation (`NOVA_REQUIRE_CONTAINER=1`)**:
  - When container isolation is enabled or `NOVA_TERMINAL_BACKEND=docker` is set, commands run inside an ephemeral Docker container.
  - Container security parameters: `--network none` (zero network access), `--memory 512m`, `--cpus 1.0`, `--read-only` root filesystem, `--tmpfs /tmp:rw,noexec,nosuid,size=64m`, and volume mounting limited strictly to the designated workspace directory (`/workspace`).
  - **Fail-Closed Policy**: If `NOVA_REQUIRE_CONTAINER=1` is configured and the Docker daemon is unreachable or unavailable, execution fails closed with HTTP 503 instead of falling back to host execution.
- **Windows Job Object Kernel Sandboxing**:
  - On Windows, host subprocesses are assigned to Windows Job Objects (`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`).
  - Kernel-enforced limits:
    - `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: Automatically terminates all child and grandchild processes if Nova Console terminates or the execution completes, eliminating orphaned background processes.
    - `JOB_OBJECT_LIMIT_JOB_MEMORY` / `JOB_OBJECT_LIMIT_PROCESS_MEMORY`: Caps maximum memory to prevent host RAM exhaustion.
    - `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`: Caps active child processes (maximum 16) to prevent fork bombs.
- **POSIX Resource Limits**:
  - On Linux and macOS, `setrlimit` restricts CPU execution time (15s soft, 20s hard), address space memory (1GB), maximum file write size (25MB), open file descriptors (128), and maximum processes (32).
- **Strict Command Allowlist & Chaining Prevention**:
  - Configurable via `NOVA_STRICT_ALLOWLIST=1` and `NOVA_COMMAND_ALLOWLIST=...`.
  - In strict allowlist mode, only approved binaries (`python`, `pip`, `pytest`, `git`, `dir`, `ls`, etc.) can be executed.
  - Shell chaining and redirection operators (`;`, `&&`, `||`, `|`, `&`, `` ` ``, `$()`, `>`, `<`, `\n`) are strictly forbidden, preventing command injection and unauthorized lateral execution.
- **Two-Phase Approval with Single-Use Cryptographic Tokens**:
  - Commands must first be proposed via `/api/terminal/propose`, issuing a time-limited (60-second), single-use cryptographically random token (`secrets.token_urlsafe(32)`) bound in server-side memory to the exact command and working directory. Tokens cannot be reused or replayed.
- **Server-Side User Authorization**:
  - Execution requests require valid server administrative credentials (`NOVA_ADMIN_KEY` or `X-Nova-Auth`).
- **Path Traversal Confinement**:
  - Working directories are strictly validated and confined to the approved workspace boundary (`NOVA_WORKSPACE`). Symlink escapes and directory traversal (`../`) are rejected.
- **Environment Variable Sanitization**:
  - Subprocesses execute with an aggressively stripped environment; secrets, tokens, credentials, and API keys are purged.
- **Restricted PATH Execution**:
  - Subprocesses execute with restricted system search paths, preventing unintended binary hijacking.
- **Execution Concurrency Limit**:
  - Terminal executions are gated by an internal semaphore allowing a maximum of 3 concurrent processes.
- **Automatic LAN Disabling**:
  - Terminal execution is automatically disabled when `NOVA_ALLOW_LAN=1` is active unless explicitly overridden by `NOVA_ENABLE_TERMINAL_LAN=1`. It can also be disabled globally with `NOVA_DISABLE_TERMINAL=1`.
- **Output Sanitization & Transparent Metadata**:
  - Command outputs are scrubbed for authorization tokens and credentials before being stored in the database audit log or returned to the browser.
  - Every execution response includes `isolation_mode` (`container_docker` or `host_subprocess_restricted`) and a transparent `security_notice` disclosing the execution context.

### 5. Denial of Service & Resource Caps
- **Request Body Limits**: Maximum payload size is capped at 10MB globally and 1MB for administrative APIs. Limits are enforced via declared `Content-Length` headers and continuously monitored during stream consumption to prevent chunked payload bypasses.
- **Rate Limiting**: Built-in sliding-window rate limiter per client IP with bounded memory tracking and endpoint-specific thresholds for generation (`chat`), proxy traffic (`proxy`), and administrative actions (`admin`).

## Reporting a Vulnerability

If you discover a security vulnerability in Nova Console:
1. Do not open a public issue.
2. Email the maintainer or report via private GitHub security advisory.
3. Include details of the vulnerability, reproduction steps, and impact.
