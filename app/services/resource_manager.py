import asyncio
import os
import platform
import time
from typing import Any

from app.services.hardware import get_gpu_stats, get_ram_stats, get_storage_stats


class ResourceOverloadError(Exception):
    """Raised when active and queued generation capacity is exceeded."""
    pass


class ResourceTimeoutError(Exception):
    """Raised when a request times out waiting in the generation queue."""
    pass


class ResourceManager:
    """
    Centralized Hardware-Aware Resource Manager.
    Monitors host hardware (CPU, RAM, GPU, VRAM), estimates KV-cache and model memory overhead,
    and enforces generation concurrency limits with bounded queuing.
    """

    def __init__(self):
        self._max_concurrent = int(os.environ.get("NOVA_MAX_CONCURRENT_GENERATIONS", "1"))
        self._max_queued = int(os.environ.get("NOVA_MAX_QUEUED_GENERATIONS", "5"))
        self._queue_timeout = float(os.environ.get("NOVA_QUEUE_TIMEOUT_SECONDS", "30.0"))

        # Concurrency primitives
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._queued_count = 0
        self._lock = asyncio.Lock()

    @property
    def max_concurrent(self) -> int:
        return int(os.environ.get("NOVA_MAX_CONCURRENT_GENERATIONS", str(self._max_concurrent)))

    @property
    def max_queued(self) -> int:
        return int(os.environ.get("NOVA_MAX_QUEUED_GENERATIONS", str(self._max_queued)))

    @property
    def queue_timeout(self) -> float:
        return float(os.environ.get("NOVA_QUEUE_TIMEOUT_SECONDS", str(self._queue_timeout)))

    def get_hardware_profile(self) -> dict[str, Any]:
        """
        Inspects CPU, RAM, GPU, and Storage with fault-tolerant fallbacks.
        Never assumes GPU is zero if detection fails; reports unavailable metrics accurately.
        """
        ram = get_ram_stats()
        gpu = get_gpu_stats()
        storage = get_storage_stats()

        cpu_cores = os.cpu_count() or 4
        cpu_name = platform.processor() or f"Generic {platform.machine()} CPU"

        # Safe CPU utilization check if psutil available
        cpu_percent = None
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=None)
        except Exception:
            pass

        return {
            "cpu": {
                "name": cpu_name,
                "cores": cpu_cores,
                "percent": cpu_percent,
                "architecture": platform.machine(),
                "platform": platform.system(),
            },
            "ram": ram,
            "gpu": gpu,
            "storage": storage,
            "concurrency": {
                "max_concurrent_generations": self.max_concurrent,
                "max_queued_generations": self.max_queued,
                "current_queued": self._queued_count,
            }
        }

    @staticmethod
    def estimate_kv_cache_mb(
        context_length: int,
        model_size_b: float = 7.0,
        layers: int = 32,
        kv_heads: int = 8,
        head_dim: int = 128,
        precision_bytes: int = 2
    ) -> float:
        """
        Calculates estimated KV-cache memory requirement in megabytes.
        Formula: 2 (K and V) * layers * kv_heads * head_dim * context_length * precision_bytes
        """
        if context_length <= 0:
            return 0.0

        # Scale layers and heads if standard model sizes provided
        if model_size_b >= 60.0:
            layers, kv_heads, head_dim = 80, 8, 128
        elif model_size_b >= 13.0:
            layers, kv_heads, head_dim = 40, 8, 128
        elif model_size_b <= 3.5:
            layers, kv_heads, head_dim = 24, 4, 64

        bytes_per_token = 2 * layers * kv_heads * head_dim * precision_bytes
        total_bytes = bytes_per_token * context_length
        return round(total_bytes / (1024 * 1024), 2)

    def evaluate_model_fit(
        self,
        model_size_mb: float,
        context_length: int = 2048,
        model_name: str = "model"
    ) -> dict[str, Any]:
        """
        Generates adaptive resource recommendations for model loading and context allocation.
        """
        profile = self.get_hardware_profile()
        gpu = profile.get("gpu", {})
        ram = profile.get("ram", {})

        kv_mb = self.estimate_kv_cache_mb(context_length)
        total_estimated_mb = model_size_mb + kv_mb

        warnings = []
        is_gpu_available = gpu.get("status") == "active" and gpu.get("type") in ("nvidia", "apple_metal", "amd_rocm")
        gpu_total_mb = float(gpu.get("total_mb", 0)) if is_gpu_available and str(gpu.get("total_mb", "0")).replace(".", "", 1).isdigit() else 0.0
        gpu_used_mb = float(gpu.get("used_mb", 0)) if is_gpu_available and str(gpu.get("used_mb", "0")).replace(".", "", 1).isdigit() else 0.0
        free_vram_mb = max(0.0, gpu_total_mb - gpu_used_mb)

        ram_total_gb = float(ram.get("total_gb", 0)) if ram.get("total_gb") is not None else 8.0
        ram_used_gb = float(ram.get("used_gb", 0)) if ram.get("used_gb") is not None else 4.0
        free_ram_mb = max(0.0, (ram_total_gb - ram_used_gb) * 1024)

        fits_in_vram = False
        if is_gpu_available and free_vram_mb > 0:
            if total_estimated_mb <= free_vram_mb * 0.9:
                fits_in_vram = True
            else:
                warnings.append(
                    f"Model with {context_length} context requires ~{int(total_estimated_mb)}MB, exceeding free VRAM ({int(free_vram_mb)}MB). Partial CPU offload will occur."
                )

        fits_in_ram = total_estimated_mb <= free_ram_mb * 0.85
        if not fits_in_ram:
            warnings.append(
                f"Combined model + KV-cache footprint (~{int(total_estimated_mb)}MB) is close to or exceeds free system RAM ({int(free_ram_mb)}MB)."
            )

        # Context recommendation
        recommended_ctx = 2048
        if fits_in_vram:
            recommended_ctx = 8192 if free_vram_mb > 12000 else (4096 if free_vram_mb > 6000 else 2048)
        elif free_ram_mb > 16000:
            recommended_ctx = 4096

        return {
            "model_size_mb": round(model_size_mb, 1),
            "estimated_kv_cache_mb": kv_mb,
            "total_estimated_mb": round(total_estimated_mb, 1),
            "fits_in_vram": fits_in_vram,
            "fits_in_ram": fits_in_ram,
            "recommended_context": recommended_ctx,
            "warnings": warnings,
            "is_gpu_available": is_gpu_available,
        }

    async def acquire_generation_slot(self):
        """
        Asynchronously acquires a generation slot. If all concurrent slots are occupied,
        enters the queue up to max_queued.
        Raises:
            ResourceOverloadError if the queue is full.
            ResourceTimeoutError if waiting exceeds queue_timeout.
        """
        async with self._lock:
            if self._queued_count >= self.max_queued:
                raise ResourceOverloadError(
                    f"Generation queue capacity exceeded (maximum {self.max_queued} queued requests). Please wait for ongoing requests to complete."
                )
            self._queued_count += 1

        queue_start = time.perf_counter()
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_timeout)
            wait_time = time.perf_counter() - queue_start
            return wait_time
        except asyncio.TimeoutError:
            raise ResourceTimeoutError(
                f"Generation request timed out after {int(self.queue_timeout)}s waiting in queue for an available slot."
            )
        finally:
            async with self._lock:
                self._queued_count = max(0, self._queued_count - 1)

    def release_generation_slot(self):
        """Releases an active generation slot."""
        try:
            self._semaphore.release()
        except ValueError:
            pass


# Global singleton instance
global_resource_manager = ResourceManager()

