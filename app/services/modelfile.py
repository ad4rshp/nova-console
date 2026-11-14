import asyncio
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from app.config import MODELFILE_PATH, PARAM_LIMITS
from app.database import get_db

DEFAULT_MODELFILE_CONTENT = """FROM qwen3.5:4b

PARAMETER num_ctx 4096
PARAMETER num_predict 1024
PARAMETER temperature 0.4
PARAMETER top_k 20
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1

SYSTEM \"\"\"
You are Nova, an elite local coding, tool-use, and systems assistant powered by Ollama.

Operational Principles:
1. Precision & Verification:
   - Inspect relevant files, schema, and environment context before proposing modifications.
   - Break complex tasks into small, verifiable, atomic steps.
   - Never assert that an action, test, build, or execution succeeded without verifying actual output.
   - Always prioritize security, edge cases, error handling, and input validation.

2. Code Quality & Architecture:
   - Write clean, idiomatic, fully functional, and modular code with proper type annotations.
   - Avoid placeholders, omitted logic (like "// TODO: implement"), or half-finished snippets.
   - Maintain a full-stack perspective: consider API design, performance, UI/UX responsiveness, and state management.

3. Tool Use & Execution:
   - Prefer structured tools for file exploration, diagnostics, testing, and application control.
   - Provide minimal, surgical edits when modifying existing files to preserve existing code structure and style.

4. Communication & Tone:
   - Be concise, direct, and technically rigorous. Omit conversational fluff and preamble.
\"\"\"
"""

def ensure_modelfile() -> Path:
    if not MODELFILE_PATH.exists():
        MODELFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MODELFILE_PATH.write_text(DEFAULT_MODELFILE_CONTENT, encoding="utf-8")
    return MODELFILE_PATH

def read_modelfile() -> dict[str, Any]:
    ensure_modelfile()
    text = MODELFILE_PATH.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for key, value in re.findall(r"^PARAMETER\s+(\w+)\s+([^\s]+)", text, re.MULTILINE | re.IGNORECASE):
        values[key.lower()] = value

    system_match = re.search(r'SYSTEM\s+"""(.*?)"""', text, re.DOTALL) or re.search(r'SYSTEM\s+"(.*?)"', text, re.DOTALL)
    system_prompt = system_match.group(1).strip() if system_match else ""

    return {
        "text": text,
        "parameters": values,
        "system_prompt": system_prompt,
        "limits": PARAM_LIMITS,
    }

def update_modelfile(values: dict[str, Any]) -> dict[str, Any]:
    ensure_modelfile()
    text = MODELFILE_PATH.read_text(encoding="utf-8")

    # Update parameters with safety bounds
    for key, bounds in PARAM_LIMITS.items():
        if key not in values:
            continue
        try:
            value = float(values[key])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Parameter '{key}' must be a valid number, received: '{values[key]}'") from error
        if not bounds[0] <= value <= bounds[1]:
            raise ValueError(
                f"Parameter '{key}' value ({value}) is outside safe limits [{bounds[0]} – {bounds[1]}]."
            )
        printable = str(int(value)) if key in {"num_ctx", "num_predict", "top_k"} else str(value)
        pattern = rf"(?im)^PARAMETER\s+{re.escape(key)}\s+[^\s]+.*$"
        replacement = f"PARAMETER {key} {printable}"
        text, count = re.subn(pattern, replacement, text)
        if count == 0:
            text = text.replace("\nSYSTEM", f"\n{replacement}\n\nSYSTEM", 1)

    # Update system prompt if provided
    if "system_prompt" in values and isinstance(values["system_prompt"], str):
        new_prompt = values["system_prompt"].strip().replace('"""', "'''")
        replacement_block = f'SYSTEM """\n{new_prompt}\n"""'
        if 'SYSTEM """' in text:
            text = re.sub(r'SYSTEM\s+""".*?"""', lambda _: replacement_block, text, flags=re.DOTALL)
        elif re.search(r'SYSTEM\s+".*?"', text, flags=re.DOTALL):
            text = re.sub(r'SYSTEM\s+".*?"', lambda _: replacement_block, text, flags=re.DOTALL)
        else:
            text += f'\n\n{replacement_block}\n'

    # Atomic write to prevent partial/corrupted modelfile on unexpected crashes
    temp_path = MODELFILE_PATH.with_suffix(".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(MODELFILE_PATH)
    mf = read_modelfile()
    now = time.time()
    iso_time = time.strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute("""
            INSERT INTO modelfile_history (timestamp, iso_time, content, system_prompt, parameters_json, applied_to_ollama)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (now, iso_time, mf.get("text", ""), mf["system_prompt"], json.dumps(mf["parameters"])))
        conn.commit()
    return mf

async def evict_model_vram(model_name: str) -> bool:
    from app.services.providers.factory import get_async_provider
    provider = await get_async_provider()
    if not provider.capabilities.get("vram_eviction", False):
        return False
    return await provider.unload_model(model_name)

async def rebuild_nova_model(model_tag: str = "nova") -> dict[str, Any]:
    from app.services.providers.factory import get_async_provider
    provider = await get_async_provider()
    if not provider.capabilities.get("modelfile_compilation", False):
        return {
            "ok": False,
            "output": f"Modelfile compilation is only supported by Ollama. Current active provider is '{provider.name}'."
        }

    # 1. Evict running instances of model from VRAM so weights recompile cleanly
    for target in [model_tag, f"{model_tag}:latest"]:
        await evict_model_vram(target)

    # 2. Run ollama create offloaded to worker thread (prevents blocking event loop)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["ollama", "create", model_tag, "-f", str(MODELFILE_PATH)],
            capture_output=True,
            text=True,
            timeout=300
        )
        ok = (result.returncode == 0)
        if ok:
            with get_db() as conn:
                conn.execute("UPDATE modelfile_history SET applied_to_ollama = 1 WHERE id = (SELECT MAX(id) FROM modelfile_history)")
                conn.commit()

        # Evict again to ensure next inference loads freshly compiled model
        for target in [model_tag, f"{model_tag}:latest"]:
            await evict_model_vram(target)

        return {"ok": ok, "output": result.stdout or result.stderr}
    except Exception as exc:
        return {"ok": False, "output": f"Rebuild process failed: {str(exc)}"}

