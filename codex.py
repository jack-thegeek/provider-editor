"""
Codex 配置适配器 —— ~/.codex/config.toml (TOML) + ~/.codex/auth.json (JSON)。

Codex 是「切换模式」：所有 provider 以 `[model_providers.<id>]` 段落共存于
config.toml，由顶层 `model_provider` 指向其中唯一生效的一个。

API Key 的存放方式（`codex doctor` + 本地 echo server 实测确定，别想当然）：
  * `env_key` 是**进程环境变量名**，走 `std::env::var()`。codex 不会把
    auth.json 里的值注入环境 —— 把 key 写进 auth.json 再让 env_key 指过去
    是行不通的，`doctor` 会报 `provider auth env var XXX (missing)`。
  * `requires_openai_auth = true` 才走 auth.json，且 AuthDotJson 只认
    `OPENAI_API_KEY` 这一个键。实测会真的发出去：
    `Authorization: Bearer <auth.json 的 OPENAI_API_KEY>`。
  * 因为 codex 同时只激活一个 provider，单个 `OPENAI_API_KEY` 槽位够用；
    各 provider 的 key 全量存在 sidecar `codex.keys.json`（codex 不读），
    切换时把激活项的 key 写进 auth.json。

读：stdlib `tomllib`（3.11+）。
写：行级段落手术 —— 只重写 `[model_providers.*]` 段和顶层 `model_provider` /
    `model` 两行，其余内容（注释、mcp_servers、projects、tui...）逐字节保留。
    这是 Python 侧对 Rust `toml_edit` 的等价做法；引入 tomli-w 重写全文件
    会丢掉用户注释和排版。

provider 的对外结构与 opencode 侧保持一致（前端共用同一套 UI）：
    {
      "name": "aerolink",
      "settings": {
        "baseURL":  "https://…",        # → base_url
        "apiKey":   "sk-…",            # → codex.keys.json[id] / auth.json
        "wireApi":  "responses",       # → wire_api（codex 专有）
      },
      "models": {"gpt-5.6-terra": {}},  # → codex.models.json（codex 不读）
    }
顶层 `model` 是全局单值（codex 只有一个），不属于任何单个 provider。
认证方式（`requires_openai_auth = true`）由后端固定接管，不在界面上出现。
"""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

# ── 路径 ────────────────────────────────────────────────────────────────────

def get_codex_dir() -> Path:
    return Path.home() / ".codex"


CONFIG_PATH: Path = get_codex_dir() / "config.toml"
AUTH_PATH: Path = get_codex_dir() / "auth.json"

# 每个 provider 的候选模型列表（codex 的 config.toml 没有 per-provider models
# 字段，激活的模型是顶层 `model`；候选列表对本工具而言是辅助信息，故放 sidecar，
# codex 不读这个文件）。与 opencode 侧的 opencode.disabled.json 同一套路。
MODELS_PATH: Path = get_codex_dir() / "codex.models.json"

# 各 provider 的 API Key 全量存档。auth.json 只有一个 OPENAI_API_KEY 槽位给
# 激活项用，非激活项的 key 必须另存，否则切换 provider 后就找不回来了。
KEYS_PATH: Path = get_codex_dir() / "codex.keys.json"

# auth.json 里 codex 唯一认的键；配合 requires_openai_auth = true 才会被使用。
OPENAI_KEY = "OPENAI_API_KEY"

# ── 底层读写 ────────────────────────────────────────────────────────────────

def _backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))


def read_raw() -> str:
    return CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else ""


def write_raw(text: str) -> None:
    """整文件覆盖（原始 TOML 视图用）。写前用 tomllib 校验，避免落盘坏配置。"""
    tomllib.loads(text)  # 语法错误直接抛 tomllib.TOMLDecodeError
    _backup(CONFIG_PATH)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(text, encoding="utf-8")


def read_auth() -> dict[str, Any]:
    if not AUTH_PATH.exists():
        return {}
    try:
        with open(AUTH_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_auth(data: dict[str, Any]) -> None:
    _backup(AUTH_PATH)
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUTH_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_models() -> dict[str, Any]:
    """读候选模型 sidecar：{provider_id: {model_id: {name}}}。"""
    if not MODELS_PATH.exists():
        return {}
    try:
        with open(MODELS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_models(data: dict[str, Any]) -> None:
    if not data:
        if MODELS_PATH.exists():
            MODELS_PATH.unlink()
        return
    _backup(MODELS_PATH)
    with open(MODELS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_keys() -> dict[str, str]:
    """读 key 存档 sidecar：{provider_id: api_key}。"""
    if not KEYS_PATH.exists():
        return {}
    try:
        with open(KEYS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v}
    except (json.JSONDecodeError, OSError):
        return {}


def write_keys(data: dict[str, Any]) -> None:
    """写 key 存档。只收非空字符串，provider 被删掉的条目自然消失。"""
    clean = {str(k): str(v) for k, v in (data or {}).items() if str(v or "").strip()}
    if not clean:
        if KEYS_PATH.exists():
            KEYS_PATH.unlink()
        return
    _backup(KEYS_PATH)
    with open(KEYS_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    try:
        KEYS_PATH.chmod(0o600)  # 明文密钥，只给本人读写
    except OSError:
        pass


# ── TOML 文本工具 ───────────────────────────────────────────────────────────

_SECTION_RE = re.compile(r"^\s*\[\[?([^\]]*)\]\]?\s*$")
_ASSIGN_RE = re.compile(r"^\s*([A-Za-z0-9_-]+|\"[^\"]*\")\s*=")
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def toml_str(value: str) -> str:
    """转成 TOML 基本字符串字面量。"""
    body = "".join(_ESCAPES.get(c, c) for c in value)
    return f'"{body}"'


def toml_key(key: str) -> str:
    """TOML 键名：裸键合法就直接用，否则加引号。"""
    return key if _BARE_KEY_RE.match(key) else toml_str(key)


def unquote_key(key: str) -> str:
    key = key.strip()
    if len(key) >= 2 and key[0] == key[-1] == '"':
        return key[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(key) >= 2 and key[0] == key[-1] == "'":
        return key[1:-1]
    return key


def _split(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """拆成 (顶层行, [(表名, 段内行)])。"""
    head: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            sections.append((unquote_key(m.group(1)), [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            head.append(line)
    return head, sections


def _set_top_key(head: list[str], key: str, value: str | None) -> list[str]:
    """在顶层替换或插入 `key = value`；value 为 None 则删除该键。插入位置在开头注释块之后。"""
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    if value is None:
        return [l for l in head if not pat.match(l)]
    line = f"{key} = {value}"
    for i, cur in enumerate(head):
        if pat.match(cur):
            head[i] = line
            return head
    at = 0
    while at < len(head) and (head[at].lstrip().startswith("#") or not head[at].strip()):
        at += 1
    head.insert(at, line)
    return head


def _managed_fields(provider_id: str, provider: dict[str, Any]) -> list[tuple[str, str | None]]:
    """本工具接管的键及其新值；值为 None 表示这行应被删掉。

    `env_key` 恒为 None —— 那一行必须删掉。codex 的 env_key 走 std::env::var()，
    把 key 写进 auth.json 再让 env_key 指过去是行不通的（doctor 会报 missing），
    所以认证一律改走 requires_openai_auth = true + auth.json 的 OPENAI_API_KEY。
    """
    settings = provider.get("settings") or {}
    name = (provider.get("name") or "").strip() or provider_id
    return [
        ("name", toml_str(name)),
        ("base_url", _opt(settings.get("baseURL"))),
        ("wire_api", _opt(settings.get("wireApi"))),
        ("env_key", None),
        ("requires_openai_auth", "true"),
    ]


def _opt(value: Any) -> str | None:
    val = (value or "").strip()
    return toml_str(val) if val else None


def _update_section(body: list[str], fields: list[tuple[str, str | None]]) -> list[str]:
    """原地更新受管键。注释、额外键（query_params 等）的内容与位置均不变。"""
    wanted = dict(fields)
    out: list[str] = [body[0]]
    seen: set[str] = set()
    for line in body[1:]:
        m = _ASSIGN_RE.match(line)
        key = unquote_key(m.group(1)) if m else None
        if key in wanted:
            seen.add(key)
            if wanted[key] is not None:
                out.append(f"{key} = {wanted[key]}")
            continue  # 值为 None → 丢弃这一行
        out.append(line)
    missing = [f"{k} = {v}" for k, v in fields if v is not None and k not in seen]
    return [out[0], *missing, *out[1:]]


def _render_document(
    text: str,
    providers: dict[str, Any],
    active_id: str | None,
    model: str,
) -> str:
    """以 providers 为准做段落对账：更新/删除已有的，追加新增的，其余原样保留。"""
    head, sections = _split(text)

    # `model_providers = { … }` 内联写法与段落写法互斥，统一重生成为段落。
    head = [l for l in head if not re.match(r"^\s*model_providers\s*=", l)]

    # active 为空时必须删掉 model_provider，否则会指向已不存在的 provider，codex 起不来
    head = _set_top_key(head, "model_provider", toml_str(active_id) if active_id else None)
    head = _set_top_key(head, "model", toml_str(model.strip()) if model.strip() else None)

    kept: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for name, body in sections:
        if not name.startswith("model_providers."):
            kept.append((name, body))
            continue
        pid = unquote_key(name[len("model_providers."):])
        if pid not in providers:
            continue  # provider 已被删除 → 丢掉整个段落
        seen.add(pid)
        kept.append((name, _update_section(body, _managed_fields(pid, providers[pid]))))

    for pid, provider in providers.items():
        if pid not in seen:
            header = f"[model_providers.{toml_key(pid)}]"
            kept.append((pid, _update_section([header], _managed_fields(pid, provider))))

    chunks = ["\n".join(head).strip("\n")]
    chunks += ["\n".join(b).strip("\n") for _, b in kept]
    return "\n\n".join(c for c in chunks if c.strip()) + "\n"


# ── 对外接口 ────────────────────────────────────────────────────────────────

def read_state() -> dict[str, Any]:
    """读出全部 provider、候选模型、当前激活的 id 和顶层 model。"""
    try:
        data = tomllib.loads(read_raw())
    except tomllib.TOMLDecodeError:
        data = {}
    auth = read_auth()
    models = read_models()
    keys = read_keys()
    active_id = data.get("model_provider") or None

    providers: dict[str, Any] = {}
    for pid, table in (data.get("model_providers") or {}).items():
        if not isinstance(table, dict):
            continue
        # key 的来源优先级：sidecar 存档 → 激活项读 auth.json 的 OPENAI_API_KEY
        # → 老配置遗留的 auth.json[env_key]（迁移兜底，首次保存后即改用新路径）。
        # env_key 本身已不再作为认证手段，只是为了把旧 key 捞出来迁移一次。
        api_key = keys.get(pid, "")
        if not api_key and pid == active_id:
            api_key = str(auth.get(OPENAI_KEY, "") or "")
        if not api_key:
            legacy_env = (table.get("env_key") or "").strip()
            if legacy_env:
                api_key = str(auth.get(legacy_env, "") or "")
        candidates = models.get(pid) or {}
        providers[pid] = {
            "name": (table.get("name") or "").strip() or pid,
            "settings": {
                "baseURL": (table.get("base_url") or "").strip(),
                "apiKey": api_key,
                "wireApi": (table.get("wire_api") or "").strip(),
            },
            "models": candidates if isinstance(candidates, dict) else {},
        }
    return {"providers": providers, "active": active_id, "model": data.get("model") or ""}


def write_state(providers: dict[str, Any], active_id: str | None, model: str) -> None:
    """对账写入：config.toml 段落 + 各 provider 的 key 存档 + auth.json 的激活槽位。

    认证固定为 `requires_openai_auth = true` + auth.json 的 OPENAI_API_KEY，
    段里的 env_key 一律删掉（它走 std::env::var()，auth.json 桥不过去）。
    """
    # 激活的 provider 若被删掉，回退到列表首个；一个不剩则清空指针。
    if active_id not in providers:
        active_id = next(iter(providers), None)

    # 认证方式后端固定接管，剥掉前端可能塞进来的东西，避免被篡改。
    for provider in providers.values():
        (provider.get("settings") or {}).pop("envKey", None)

    write_raw(_render_document(read_raw(), providers, active_id, model))

    # 候选模型列表：只给仍存在的 provider 留条目，删除 provider 时连带清掉
    write_models({pid: p.get("models") or {} for pid, p in providers.items() if p.get("models")})

    keys = {pid: ((p.get("settings") or {}).get("apiKey") or "").strip() for pid, p in providers.items()}
    keys = {pid: k for pid, k in keys.items() if k}
    write_keys(keys)

    # auth.json 只承载激活项的 key —— codex 同时只激活一个 provider。
    active_key = keys.get(active_id or "", "")
    auth = read_auth()
    if active_key and auth.get(OPENAI_KEY) != active_key:
        auth[OPENAI_KEY] = active_key
        write_auth(auth)
    # 激活项没有 key 时不动 auth.json：那里可能有用户自己放的 OPENAI_API_KEY
    # （比如配内建 openai provider 时），删掉代价比留一个陈旧值更大。
    # ponytail: 迁移后 auth.json 里会留下 env_key 的孤儿条目（如 HUOSHAN_API_KEY）。
    # 无法区分它是不是用户自己放的，需要清理时手动删即可。


def validate(text: str) -> str | None:
    """校验 TOML，返回 None 表示合法，否则返回错误信息。"""
    try:
        tomllib.loads(text)
        return None
    except tomllib.TOMLDecodeError as exc:
        return str(exc)
