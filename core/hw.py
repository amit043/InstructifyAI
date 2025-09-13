import os
import platform
import shutil
import subprocess
from typing import Any, Dict, Optional


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _get_cpu_cores() -> int:
    cores = os.cpu_count()
    return cores if isinstance(cores, int) and cores > 0 else 1


def _get_total_ram_bytes() -> Optional[int]:
    # Try psutil if available
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().total)
    except Exception:
        pass

    # Linux: /proc/meminfo fallback
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        # Format: MemTotal:      32543160 kB
                        parts = line.split()
                        if len(parts) >= 2:
                            kib = _safe_int(parts[1])
                            if kib is not None:
                                return kib * 1024
    except Exception:
        pass

    # Windows fallback via GlobalMemoryStatusEx
    try:
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
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys)
    except Exception:
        pass

    # POSIX generic fallback
    try:
        if hasattr(os, "sysconf"):
            if os.sysconf_names.get("SC_PAGE_SIZE") and os.sysconf_names.get("SC_PHYS_PAGES"):
                pagesize = int(os.sysconf("SC_PAGE_SIZE"))
                pages = int(os.sysconf("SC_PHYS_PAGES"))
                return pagesize * pages
    except Exception:
        pass

    return None


def _bytes_to_gb(x: Optional[int]) -> float:
    if x is None:
        return 0.0
    try:
        return float(x) / (1024 ** 3)
    except Exception:
        return 0.0


def _detect_gpu_via_nvml() -> Dict[str, Optional[Any]]:
    info: Dict[str, Optional[Any]] = {
        "has_cuda": False,
        "gpu_name": None,
        "vram_mb": None,
        "cuda_cc": None,
    }

    try:
        import pynvml as nvml  # type: ignore

        try:
            nvml.nvmlInit()
        except Exception:
            return info

        try:
            count = nvml.nvmlDeviceGetCount()
            if count and count > 0:
                handle = nvml.nvmlDeviceGetHandleByIndex(0)
                # Name can be bytes in some versions
                try:
                    name = nvml.nvmlDeviceGetName(handle)
                    if isinstance(name, bytes):  # pragma: no cover - depends on env
                        name = name.decode("utf-8", errors="ignore")
                except Exception:
                    name = None

                try:
                    mem_info = nvml.nvmlDeviceGetMemoryInfo(handle)
                    vram_mb = int(round(int(mem_info.total) / (1024 ** 2)))
                except Exception:
                    vram_mb = None

                cc_str: Optional[str] = None
                try:
                    # Not available on older NVML
                    major_minor = getattr(nvml, "nvmlDeviceGetCudaComputeCapability", None)
                    if callable(major_minor):
                        maj, min_ = major_minor(handle)
                        cc_str = f"{maj}.{min_}"
                except Exception:
                    cc_str = None

                info.update(
                    {
                        "has_cuda": True,
                        "gpu_name": name if isinstance(name, str) else None,
                        "vram_mb": vram_mb,
                        "cuda_cc": cc_str,
                    }
                )
        finally:
            try:
                nvml.nvmlShutdown()
            except Exception:
                pass
    except Exception:
        # pynvml not installed or NVML unavailable
        pass

    return info


def _detect_gpu_via_nvidia_smi() -> Dict[str, Optional[Any]]:
    info: Dict[str, Optional[Any]] = {
        "has_cuda": False,
        "gpu_name": None,
        "vram_mb": None,
        "cuda_cc": None,
    }

    exe = shutil.which("nvidia-smi")
    if not exe:
        return info

    def _run(cmd):
        try:
            p = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if p.returncode == 0:
                return (p.stdout or "").strip()
        except Exception:
            pass
        return ""

    # Prefer querying name, memory and compute capability in one call
    out = _run([exe, "--query-gpu=name,memory.total,compute_cap", "--format=csv,noheader,nounits"])
    if not out:
        # Fallback without compute_cap column
        out = _run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if not out:
        return info

    first = out.splitlines()[0].strip()
    # CSV values may be separated by comma+space or comma
    parts = [p.strip() for p in first.split(",")]
    if not parts:
        return info

    name = parts[0] if parts[0] else None
    vram_mb = _safe_int(parts[1]) if len(parts) > 1 else None
    cc_str = None
    if len(parts) > 2 and parts[2]:
        cc_str = parts[2]

    info.update(
        {
            "has_cuda": True if name else False,
            "gpu_name": name,
            "vram_mb": vram_mb,
            "cuda_cc": cc_str,
        }
    )
    return info


def detect_hardware() -> Dict[str, Any]:
    """
    Detect host hardware capabilities with best-effort fallbacks.

    Returns a dict with keys:
      - has_cuda: bool
      - gpu_name: str | None
      - vram_mb: int | None
      - cuda_cc: str | None
      - cpu_cores: int
      - ram_gb: float

    Never raises; returns sane defaults on failure.
    """

    cpu_cores = _get_cpu_cores()
    ram_bytes = _get_total_ram_bytes()
    ram_gb = _bytes_to_gb(ram_bytes)

    # Prefer NVML
    gpu_info = _detect_gpu_via_nvml()
    if not gpu_info.get("has_cuda"):
        # Fallback to nvidia-smi
        gpu_info = _detect_gpu_via_nvidia_smi()

    result: Dict[str, Any] = {
        "has_cuda": bool(gpu_info.get("has_cuda", False)),
        "gpu_name": gpu_info.get("gpu_name"),
        "vram_mb": gpu_info.get("vram_mb"),
        "cuda_cc": gpu_info.get("cuda_cc"),
        "cpu_cores": cpu_cores,
        "ram_gb": ram_gb,
    }

    return result


__all__ = ["detect_hardware"]

