# Nova Console — Interactive Showcase & Animated Tutorial

A standalone, high-performance looping tutorial and feature showcase designed to demonstrate Nova Console directly on GitHub and documentation pages.

Styled with Nova Console's exact **Dark Neumorphic Design System**:
- Canvas: Deep Slate & Gunmetal (`#14171f`)
- Soft Neumorphic Shadows: `6px 6px 14px #0a0c10, -6px -6px 14px #1c212c`
- Accents: Electric Blue (`#2563eb` / `#3b82f6`) and Emerald Green (`#10b981`)
- Real Radial Gauges & Sparklines

---

## 4-Scene Tutorial Flow (13-Second Cycle)

1. **Scene 1: Telemetry & VRAM Calibration (0.0s – 3.0s)**
   - Live hardware status initialization (`100% Localhost · 0 Telemetry`).
   - Radial gauges animate GPU VRAM (3.8 / 8.0 GB, 42°C) and RAM Load (14.2 / 32.0 GB).
2. **Scene 2: Natural Prompt Input & Context Tuning (3.0s – 5.6s)**
   - Context preset selector toggles to `4K Context`.
   - Simulated user input types into the chat box and sends.
3. **Scene 3: Deep Reasoning & 64+ tok/s Token Stream (5.6s – 9.2s)**
   - Real `thinking-box` accordion expands with step-by-step reasoning.
   - High-velocity token streaming with live TPS indicator (spiking above 64 tok/s).
4. **Scene 4: Cryptographic Command Execution & Approval (9.2s – 12.6s)**
   - Sandboxed terminal command proposal card surfaces (`$ git status`).
   - Virtual cursor moves to and clicks **Approve & Run**.
   - Verified output displays with secret redaction before resetting cleanly for the next loop.

---

## How to View and Export as a Video for GitHub

### Option 1: Direct Browser View
Open `docs/showcase/tutorial.html` in your web browser.

### Option 2: 1-Click Video Recording
Click **"Export Video (.webm)"** in the top-right toolbar:
- Captures exactly 1 seamless 13-second loop at 60fps.
- Automatically saves `nova-console-showcase.webm` for embedding into GitHub Releases or documentation.

### Option 3: Screen Capture to MP4 / GIF
Use Windows Snipping Tool (**Win + Shift + R**) to record the screen into an `.mp4` video.
