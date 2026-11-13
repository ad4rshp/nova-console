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
- **Mandatory LAN Authentication**: When LAN mode is active, all mutating endpoints and administrative APIs require an `Authorization: Bearer <token>` or `X-Nova-Auth` header.

### 2. Browser Security & CSRF
- **Deep CSRF Origin Verification**: All state-changing requests (`POST`, `PUT`, `DELETE`, `PATCH`) to `/api/` endpoints must present valid `Origin` or `Referer` headers matching the server's configured scheme, hostname, and port.
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

### 4. Terminal Command Execution Sandbox
Terminal execution is never governed solely by regex pattern matching. It uses multiple layered defense controls:
- **Two-Phase Cryptographic Approval**: Commands must first be proposed via `/api/terminal/propose`, issuing a time-limited (60-second), single-use HMAC token bound to the exact command and working directory.
- **Server-Side User Authorization**: Execution requests require valid server administrative credentials (`NOVA_ADMIN_KEY`).
- **Path Traversal Confinement**: Working directories are strictly validated and confined to the approved workspace boundary (`NOVA_WORKSPACE`). Symlink escapes and directory traversal (`../`) are rejected.
- **Subprocess Environment Isolation**: Subprocesses execute with sanitized environments. Sensitive variables (API keys, admin tokens, passwords) are scrubbed.
- **Restricted PATH Execution**: Subprocesses execute with restricted system search paths, preventing unintended binary hijacking.
- **Execution Concurrency Limit**: Terminal executions are gated by an internal semaphore allowing a maximum of 3 concurrent processes.
- **Automatic LAN Disabling**: Terminal execution is automatically disabled when `NOVA_ALLOW_LAN=1` is active unless explicitly overridden by `NOVA_ENABLE_TERMINAL_LAN=1`.
- **Output Sanitization**: Command outputs are scrubbed for authorization tokens and credentials before being stored in the database audit log or returned to the browser.

### 5. Denial of Service & Resource Caps
- **Request Body Limits**: Maximum payload size is capped at 10MB globally and 1MB for administrative APIs.
- **Rate Limiting**: Built-in sliding-window rate limiter per client IP.

## Reporting a Vulnerability

If you discover a security vulnerability in Nova Console:
1. Do not open a public issue.
2. Email the maintainer or report via private GitHub security advisory.
3. Include details of the vulnerability, reproduction steps, and impact.
