"""Etat des services locaux : ComfyUI, Ollama, FFmpeg et carte graphique."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from fastapi import APIRouter, Depends

from shortforge.deps import get_runtime
from shortforge.integrations.comfyui import ComfyUIError
from shortforge.runtime import Runtime

router = APIRouter(tags=["etat"])


def gpu_info(runtime: Runtime) -> dict[str, Any]:
    """Carte graphique vue par ComfyUI, sinon par nvidia-smi."""
    try:
        devices = runtime.comfy.system_stats().get("devices") or []
        if devices:
            dev = devices[0]
            return {"available": True, "name": dev.get("name", ""),
                    "vram_total_mb": round(dev.get("vram_total", 0) / 2**20),
                    "vram_free_mb": round(dev.get("vram_free", 0) / 2**20)}
    except ComfyUIError:
        pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5, check=True).stdout.splitlines()
            name, total, free = (part.strip() for part in out[0].split(","))
            return {"available": True, "name": name, "vram_total_mb": int(total), "vram_free_mb": int(free)}
        except (subprocess.SubprocessError, ValueError, IndexError, OSError):
            pass
    return {"available": False, "name": "", "vram_total_mb": 0, "vram_free_mb": 0}


@router.get("/api/status")
def services_status(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    ffmpeg = shutil.which(runtime.settings.ffmpeg_path)
    llm_ok = getattr(runtime.llm, "is_running", lambda: False)()
    return {
        "comfyui": {"running": runtime.comfy.is_running(), "url": runtime.comfy.base_url},
        "ollama": {"running": llm_ok, "model": runtime.settings.ollama_model},
        "ffmpeg": {"available": ffmpeg is not None, "path": ffmpeg or ""},
        "gpu": gpu_info(runtime),
    }
