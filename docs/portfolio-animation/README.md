# Nova Console — Portfolio Showcase Animation

A standalone, high-performance, looping showcase animation built specifically for developer portfolios, product showcase cards, and demo videos.

## Features

- **13-Second Seamless Loop**: Automatically cycles through 4 realistic workstation stages:
  1. **Telemetry & VRAM Calibration**: Live GPU & RAM gauge sweep, status pill animation.
  2. **Model Selection & Prompting**: Interactive context preset switch (`4K`), model selection (`qwen3.5:4b`), and natural cursor typing.
  3. **Deep Reasoning & Token Stream**: Animated thinking accordion and 64+ tok/s real-time generation.
  4. **Sandboxed Terminal Execution**: Cryptographic token authorization badge, cursor approval click, and audited command output.
- **Crystal-Clear Vector Quality**: Uses pure Tailwind CSS + JS DOM animations (zero video compression artifacts on Retina/4K displays).
- **1-Click 1080p Video Exporter**: Built-in `Export 1080p Video (.webm)` button using the browser's native `MediaRecorder` API.
- **Embedded or Video Options**: You can either embed it directly on your website (as an interactive iframe / React component) or export it as a video/GIF.

---

## How to Export as a Looping Video / GIF

1. Open `docs/portfolio-animation/index.html` in your browser (Chrome or Edge recommended).
2. Click **"Export 1080p Video (.webm)"** in the top-right toolbar.
3. Select this browser tab to record — it will capture exactly 1 seamless 13-second loop and automatically download `nova-console-portfolio-demo.webm`.
4. (Optional) Convert to MP4 or GIF using any free tool or online converter, or use standard Windows Snipping Tool (`Win + Shift + R`) to capture an MP4.

---

## How to Embed Directly on Your Portfolio Website

### 1. Direct iframe (Easiest — Next.js, HTML, Webflow, Framer)
```html
<iframe
  src="/docs/portfolio-animation/index.html"
  width="100%"
  height="720"
  style="border: none; border-radius: 16px; overflow: hidden;"
  title="Nova Console Demo">
</iframe>
```

### 2. Video Tag (If using the exported .webm / .mp4 file)
```html
<video
  autoplay
  loop
  muted
  playsinline
  class="rounded-2xl border border-slate-800 shadow-2xl w-full max-w-4xl">
  <source src="/assets/nova-console-demo.mp4" type="video/mp4" />
  <source src="/assets/nova-console-demo.webm" type="video/webm" />
</video>
```
