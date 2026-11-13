import json
import re
import subprocess
import time
from typing import Any
import httpx
from app.config import MODELFILE_PATH, PARAM_LIMITS, OLLAMA_HOST, DEFAULT_MODEL
from app.database import get_db

def read_modelfile() -> dict[str, Any]:
    text = MODELFILE_PATH.read_text(encoding="utf-8") if MODELFILE_PATH.exists() else ""
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
    if not MODELFILE_PATH.exists():
        raise ValueError("Modelfile is missing")
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
        new_prompt = values["system_prompt"].strip()
        if 'SYSTEM """' in text:
            text = re.sub(r'SYSTEM\s+""".*?"""', f'SYSTEM """\n{new_prompt}\n"""', text, flags=re.DOTALL)
        elif re.search(r'SYSTEM\s+".*?"', text, flags=re.DOTALL):
            text = re.sub(r'SYSTEM\s+".*?"', f'SYSTEM """\n{new_prompt}\n"""', text, flags=re.DOTALL)
        else:
            text += f'\n\nSYSTEM """\n{new_prompt}\n"""\n'

    MODELFILE_PATH.write_text(text, encoding="utf-8")
    mf = read_modelfile()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO modelfile_history (system_prompt, parameters_json, applied_to_ollama)
            VALUES (?, ?, 0)
        """, (mf["system_prompt"], json.dumps(mf["parameters"])))
        conn.commit()
    return mf

async def evict_model_vram(model_name: str) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(f"{OLLAMA_HOST}/api/generate", json={"model": model_name, "keep_alive": 0})
        except Exception:
            pass

async def rebuild_nova_model(model_tag: str = "nova") -> dict[str, Any]:
    # 1. Evict running instances of model from VRAM so weights recompile cleanly
    for target in [model_tag, f"{model_tag}:latest"]:
        await evict_model_vram(target)

    # 2. Run ollama create
    try:
        result = subprocess.run(["ollama", "create", model_tag, "-f", str(MODELFILE_PATH)], capture_output=True, text=True, timeout=300)
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

