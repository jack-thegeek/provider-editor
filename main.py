"""
OpenCode Providers Editor — FastAPI Backend
"""
from __future__ import annotations

import json
import shutil
import socket
import sys
import urllib.error
import urllib.request
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import CONFIG_PATH, DISABLED_PATH

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _write_config(data: dict[str, Any]) -> None:
    # Backup before writing
    if CONFIG_PATH.exists():
        backup = CONFIG_PATH.with_suffix(".json.bak")
        shutil.copy2(CONFIG_PATH, backup)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_disabled() -> dict[str, Any]:
    """读取停用 provider 列表（sidecar 文件，opencode 不会读取它）。"""
    if not DISABLED_PATH.exists():
        return {}
    with open(DISABLED_PATH, encoding="utf-8") as f:
        return json.load(f)


def _write_disabled(data: dict[str, Any]) -> None:
    if DISABLED_PATH.exists():
        backup = DISABLED_PATH.with_suffix(".json.bak")
        shutil.copy2(DISABLED_PATH, backup)
    DISABLED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DISABLED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _find_free_port(start: int = 7788) -> int:
    port = start
    while port < start + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    port = getattr(app.state, "port", None)
    if port:
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass  # 无桌面/无默认浏览器时静默跳过
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="OpenCode Providers Editor", lifespan=lifespan)

# PyInstaller onefile 运行时，资源位于 sys._MEIPASS 临时解压目录
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = BASE_DIR / "static"


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/config")
def get_config():
    """Return the full opencode.json content."""
    return _read_config()


@app.put("/api/config")
async def put_config(request: Request):
    """Replace the full opencode.json content."""
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    _write_config(body)
    return {"ok": True}


@app.get("/api/providers")
def get_providers():
    """Return enabled providers (from config) and disabled providers (sidecar)."""
    cfg = _read_config()
    return {"enabled": cfg.get("providers", {}), "disabled": _read_disabled()}


@app.put("/api/providers")
async def put_providers(request: Request):
    """Replace the entire providers section."""
    try:
        providers = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    cfg = _read_config()
    cfg["providers"] = providers
    _write_config(cfg)
    return {"ok": True}


@app.post("/api/providers/{provider_id}")
async def add_provider(provider_id: str, request: Request):
    """Add or overwrite a single provider (new providers are enabled)."""
    try:
        provider_data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    cfg = _read_config()
    cfg.setdefault("providers", {})[provider_id] = provider_data
    _write_config(cfg)
    # 若该 ID 之前被停用，则从停用列表移除
    disabled = _read_disabled()
    if provider_id in disabled:
        del disabled[provider_id]
        _write_disabled(disabled)
    return {"ok": True, "id": provider_id}


@app.post("/api/providers/{provider_id}/enable")
def enable_provider(provider_id: str):
    """启用 provider：从停用列表移回 opencode.json 的 providers。"""
    disabled = _read_disabled()
    cfg = _read_config()
    provider = disabled.pop(provider_id, None)
    if provider is not None:
        cfg.setdefault("providers", {})[provider_id] = provider
        _write_config(cfg)
        _write_disabled(disabled)
    elif provider_id not in cfg.get("providers", {}):
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return {"ok": True, "id": provider_id, "enabled": True}


@app.post("/api/providers/{provider_id}/disable")
def disable_provider(provider_id: str):
    """停用 provider：从 opencode.json 移入停用列表。"""
    cfg = _read_config()
    providers = cfg.get("providers", {})
    provider = providers.pop(provider_id, None)
    if provider is None:
        # 可能已是停用状态，幂等返回
        disabled = _read_disabled()
        if provider_id in disabled:
            return {"ok": True, "id": provider_id, "enabled": False}
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    disabled = _read_disabled()
    disabled[provider_id] = provider
    cfg["providers"] = providers
    _write_config(cfg)
    _write_disabled(disabled)
    return {"ok": True, "id": provider_id, "enabled": False}


@app.put("/api/providers/disabled")
async def put_disabled_providers(request: Request):
    """Replace the entire disabled-providers section (sidecar)."""
    try:
        disabled = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    _write_disabled(disabled)
    return {"ok": True}


@app.delete("/api/providers/{provider_id}")
def delete_provider(provider_id: str):
    """Delete a single provider (from both enabled and disabled lists)."""
    cfg = _read_config()
    providers = cfg.get("providers", {})
    disabled = _read_disabled()
    if provider_id not in providers and provider_id not in disabled:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    providers.pop(provider_id, None)
    disabled.pop(provider_id, None)
    cfg["providers"] = providers
    _write_config(cfg)
    _write_disabled(disabled)
    return {"ok": True}


class ProxyModelsRequest(BaseModel):
    baseURL: str
    apiKey: str = ""


@app.post("/api/proxy/models")
def proxy_models(req: ProxyModelsRequest):
    """
    Fetch the /models list from the given baseURL server-side to avoid CORS.
    Supports OpenAI-compatible /v1/models or bare /models endpoints.
    """
    base = req.baseURL.rstrip("/")
    url  = f"{base}/models"
    headers = {"Accept": "application/json"}
    if req.apiKey:
        headers["Authorization"] = f"Bearer {req.apiKey}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=e.code, detail=f"上游错误 {e.code}: {body[:300]}")
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"无法连接: {e.reason}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/shutdown")
def shutdown():
    """Stop the uvicorn server. 被网页端「退出」按钮调用。"""
    server = getattr(app.state, "server", None)
    if server is None:
        raise HTTPException(status_code=409, detail="服务未以可关闭方式启动")
    server.should_exit = True
    return {"ok": True}


# ---------------------------------------------------------------------------
# Static files / SPA fallback
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "0") or 0) or _find_free_port(7788)
    if os.environ.get("OPEN_BROWSER", "1") == "1":
        app.state.port = port  # 仅交互式启动时自动开浏览器
    print(f"✅  OpenCode Providers Editor running at http://127.0.0.1:{port}")
    print(f"📄  Config file: {CONFIG_PATH}")
    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    app.state.server = server  # 供 /api/shutdown 优雅关闭
    server.run()
