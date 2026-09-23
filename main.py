"""
OpenCode Providers Editor — FastAPI Backend
"""
from __future__ import annotations

import json
import shutil
import socket
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

from config import CONFIG_PATH

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
        webbrowser.open(f"http://127.0.0.1:{port}")
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="OpenCode Providers Editor", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"


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
    """Return only the providers section."""
    cfg = _read_config()
    return cfg.get("providers", {})


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
    """Add or overwrite a single provider."""
    try:
        provider_data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    cfg = _read_config()
    cfg.setdefault("providers", {})[provider_id] = provider_data
    _write_config(cfg)
    return {"ok": True, "id": provider_id}


@app.delete("/api/providers/{provider_id}")
def delete_provider(provider_id: str):
    """Delete a single provider."""
    cfg = _read_config()
    providers = cfg.get("providers", {})
    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    del providers[provider_id]
    cfg["providers"] = providers
    _write_config(cfg)
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
    port = _find_free_port(7788)
    app.state.port = port
    print(f"✅  OpenCode Providers Editor running at http://127.0.0.1:{port}")
    print(f"📄  Config file: {CONFIG_PATH}")
    uvicorn.run(app, host="127.0.0.1", port=port)
