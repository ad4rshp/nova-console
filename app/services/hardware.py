import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

def get_ram_stats() -> dict[str, Any]:
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            "total_gb": round(vm.total / (1024 ** 3), 1),
            "used_gb": round(vm.used / (1024 ** 3), 1),
            "percent": int(vm.percent)
        }
    except Exception:
        # Fallback if psutil is somehow missing
        if platform.system() == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total = stat.ullTotalPhys / (1024 ** 3)
            used = (stat.ullTotalPhys - stat.ullAvailPhys) / (1024 ** 3)
            return {"total_gb": round(total, 1), "used_gb": round(used, 1), "percent": int(stat.dwMemoryLoad)}
        return {"total_gb": 16.0, "used_gb": 8.0, "percent": 50}

def get_gpu_stats() -> dict[str, Any]:
    sys_name = platform.system()

    # 1. Check NVIDIA GPU via nvidia-smi
    nvsmi = shutil.which("nvidia-smi")
    if nvsmi:
        try:
            cmd = [
                nvsmi,
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                line = res.stdout.strip().split("\n")[0]
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    return {
                        "type": "nvidia",
                        "name": parts[0],
                        "used_mb": parts[1],
                        "total_mb": parts[2],
                        "utilization": parts[3],
                        "vram_percent": int(float(parts[1]) / max(float(parts[2]), 1) * 100)
                    }
        except Exception:
            pass

    # 2. Check Apple Silicon (macOS Metal / Unified Memory)
    if sys_name == "Darwin":
        try:
            model_res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True)
            chip_name = model_res.stdout.strip()
            if not chip_name or "Apple" not in chip_name:
                model_res = subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True)
                chip_name = f"Apple Silicon ({model_res.stdout.strip()})"

            ram = get_ram_stats()
            # On Apple Silicon, unified memory acts as VRAM
            return {
                "type": "apple_metal",
                "name": chip_name or "Apple Silicon (Metal)",
                "used_mb": str(int(ram["used_gb"] * 1024)),
                "total_mb": str(int(ram["total_gb"] * 1024)),
                "utilization": str(ram["percent"]),
                "vram_percent": ram["percent"],
                "unified_memory": True
            }
        except Exception:
            pass

    # 3. Check AMD ROCm (Linux / Windows)
    rocm_smi = shutil.which("rocm-smi")
    if rocm_smi:
        try:
            cmd = [rocm_smi, "--showuse", "--showmeminfo", "vram", "--csv"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                return {
                    "type": "amd_rocm",
                    "name": "AMD Radeon (ROCm)",
                    "used_mb": "0",
                    "total_mb": "0",
                    "utilization": "0",
                    "vram_percent": 0
                }
        except Exception:
            pass

    # 4. CPU-Only / Integrated Graphics Fallback
    ram = get_ram_stats()
    cpu_cores = os.cpu_count() or 4
    return {
        "type": "cpu_only",
        "name": f"CPU Mode ({cpu_cores} Cores)",
        "used_mb": str(int(ram["used_gb"] * 1024)),
        "total_mb": str(int(ram["total_gb"] * 1024)),
        "utilization": str(ram["percent"]),
        "vram_percent": ram["percent"],
        "is_cpu_mode": True
    }

def get_storage_stats() -> dict[str, Any]:
    home = Path.home()
    # Check Ollama storage locations across platforms
    ollama_dir = None
    if "OLLAMA_MODELS" in os.environ:
        ollama_dir = Path(os.environ["OLLAMA_MODELS"])
    else:
        candidates = [
            home / ".ollama" / "models",
            home / "AppData" / "Local" / "Programs" / "Ollama" / "models",
            Path("/usr/share/ollama/.ollama/models")
        ]
        for c in candidates:
            if c.exists():
                ollama_dir = c
                break

    if not ollama_dir or not ollama_dir.exists():
        ollama_dir = home / ".ollama" / "models"

    model_dir_gb = 0.0
    if ollama_dir.exists():
        try:
            total_bytes = sum(f.stat().st_size for f in ollama_dir.rglob("*") if f.is_file())
            model_dir_gb = round(total_bytes / (1024 ** 3), 1)
        except Exception:
            model_dir_gb = 0.0

    target_disk = ollama_dir if ollama_dir.exists() else home
    disk_free_gb = round(shutil.disk_usage(target_disk).free / (1024 ** 3), 1)

    return {
        "model_dir_gb": model_dir_gb,
        "disk_free_gb": disk_free_gb,
        "path": str(ollama_dir)
    }

