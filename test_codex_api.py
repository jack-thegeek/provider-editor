"""
Codex 路由的 HTTP 层校验 —— 全部在临时目录上进行，不触碰真实 ~/.codex。

不引入 httpx / TestClient：路由处理函数本身就是普通函数，直接调用即可
（只有需要读 body 的那几个用 FakeRequest 顶替）。

跑法： .venv/bin/python -m unittest test_codex_api
"""
import asyncio
import json
import tempfile
import tomllib
import unittest
from pathlib import Path

import codex
import main
from fastapi import HTTPException


class FakeRequest:
    """顶替 starlette Request，只提供路由用到的 .json()。"""

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


ORIGINAL = '''model_provider = "aerolink"
model = "gpt-5.6-terra"

[model_providers.aerolink]
name = "aerolink"
base_url = "https://cgapi.aerolink.lat"
wire_api = "responses"
requires_openai_auth = true

[mcp_servers.codegraph]
command = "codegraph"
args = ["serve", "--mcp"]
'''


class CodexApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.cfg = d / "config.toml"
        self.auth = d / "auth.json"
        self.models_path = d / "codex.models.json"
        self.keys_path = d / "codex.keys.json"
        # 关键：把适配器路径重定向到沙箱，绝不写真实 ~/.codex
        codex.CONFIG_PATH, codex.AUTH_PATH = self.cfg, self.auth
        codex.MODELS_PATH, codex.KEYS_PATH = self.models_path, self.keys_path
        self.cfg.write_text(ORIGINAL, encoding="utf-8")
        self.auth.write_text('{"OPENAI_API_KEY": "sk-real"}', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _state(self):
        return main.codex_get_providers()

    def _add(self, pid, body):
        return asyncio.run(main.codex_add_provider(pid, FakeRequest(body)))

    def _put(self, body):
        return asyncio.run(main.codex_put_providers(FakeRequest(body)))

    def _doc(self):
        return tomllib.loads(self.cfg.read_text(encoding="utf-8"))

    # ── 读 ──
    def test_get_returns_state_and_path(self):
        s = self._state()
        self.assertEqual(s["active"], "aerolink")
        self.assertEqual(s["model"], "gpt-5.6-terra")
        self.assertEqual(s["configPath"], str(self.cfg))
        self.assertEqual(s["providers"]["aerolink"]["settings"]["apiKey"], "sk-real")

    # ── 单活切换 ──
    def test_add_sets_openai_auth_and_does_not_steal_active_slot(self):
        r = self._add("agnes", {"name": "Agnes", "settings": {"apiKey": "sk-a", "baseURL": "https://a/v1"}})
        self.assertEqual(r["active"], "aerolink")
        tbl = self._doc()["model_providers"]["agnes"]
        self.assertIs(tbl["requires_openai_auth"], True)
        self.assertNotIn("env_key", tbl)
        self.assertNotIn("envKey", r["providers"]["agnes"]["settings"])
        # 不激活就不会占用 auth.json 那个槽位
        self.assertEqual(json.loads(self.auth.read_text())["OPENAI_API_KEY"], "sk-real")
        self.assertEqual(json.loads(self.keys_path.read_text())["agnes"], "sk-a")

    def test_enable_switches_pointer_and_swaps_auth_slot(self):
        self._add("agnes", {"name": "Agnes", "settings": {"apiKey": "sk-a"}})
        r = main.codex_enable_provider("agnes")
        self.assertEqual(r["active"], "agnes")
        self.assertEqual(sorted(r["providers"]), ["aerolink", "agnes"])
        # 激活项的 key 落到 auth.json 唯一的槽位
        self.assertEqual(json.loads(self.auth.read_text())["OPENAI_API_KEY"], "sk-a")

    def test_disable_active_falls_back_to_another(self):
        self._add("agnes", {"name": "Agnes", "settings": {}})
        main.codex_enable_provider("agnes")
        self.assertEqual(main.codex_disable_provider("agnes")["active"], "aerolink")

    def test_cannot_disable_the_last_active_one(self):
        with self.assertRaises(HTTPException) as cm:
            main.codex_disable_provider("aerolink")
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("至少保留一个", cm.exception.detail)
        self.assertEqual(self._state()["active"], "aerolink")  # 未被改动

    def test_disable_inactive_is_a_noop(self):
        self._add("agnes", {"name": "Agnes", "settings": {}})
        self.assertEqual(main.codex_disable_provider("agnes")["active"], "aerolink")

    # ── 增删改 ──
    def test_delete_active_repoints_pointer(self):
        r = main.codex_delete_provider("aerolink")
        self.assertEqual(r["providers"], {})
        self.assertIsNone(r["active"])
        self.assertNotIn("model_provider", self._doc())  # 不留悬空指针
        self.assertIn("[mcp_servers.codegraph]", self.cfg.read_text())  # 无关表保留

    def test_404_on_unknown_provider(self):
        for call in (lambda: main.codex_enable_provider("nope"),
                     lambda: main.codex_disable_provider("nope"),
                     lambda: main.codex_delete_provider("nope")):
            with self.assertRaises(HTTPException) as cm:
                call()
            self.assertEqual(cm.exception.status_code, 404)

    def test_full_put_persists_base_url_and_model(self):
        p = self._state()["providers"]
        p["aerolink"]["settings"]["baseURL"] = "https://changed/v1"
        r = self._put({"providers": p, "active": "aerolink", "model": "gpt-9"})
        self.assertEqual(r["model"], "gpt-9")
        d = self._doc()
        self.assertEqual(d["model_providers"]["aerolink"]["base_url"], "https://changed/v1")
        self.assertEqual(d["model"], "gpt-9")

    def test_put_with_unknown_active_falls_back(self):
        r = self._put({"providers": self._state()["providers"], "active": "ghost", "model": "m"})
        self.assertEqual(r["active"], "aerolink")

    def test_invalid_json_body_is_400(self):
        class Boom(FakeRequest):
            async def json(self):
                raise ValueError("bad json")

        with self.assertRaises(HTTPException) as cm:
            asyncio.run(main.codex_put_providers(Boom({})))
        self.assertEqual(cm.exception.status_code, 400)

    # ── 原始 TOML 视图 ──
    def test_raw_view_roundtrip(self):
        text = main.codex_get_config()["text"]
        self.assertIn("[mcp_servers.codegraph]", text)
        self.assertTrue(asyncio.run(main.codex_put_config(FakeRequest({"text": text})))["ok"])

    def test_raw_view_rejects_broken_toml_without_writing(self):
        before = self.cfg.read_text()
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(main.codex_put_config(FakeRequest({"text": "[oops\n"})))
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("TOML", cm.exception.detail)
        self.assertEqual(self.cfg.read_text(), before)  # 坏配置没落盘

    def test_backup_written_on_change(self):
        main.codex_delete_provider("aerolink")
        self.assertTrue(self.cfg.with_suffix(".toml.bak").exists())

    # ── 候选模型列表 ──
    def test_models_survive_put_roundtrip(self):
        s = self._state()
        s["providers"]["aerolink"]["models"] = {"gpt-5.6-terra": {"name": "Terra"}, "gpt-5.1": {}}
        s["model"] = "gpt-5.1"
        r = self._put(s)

        self.assertEqual(r["model"], "gpt-5.1")
        self.assertEqual(
            r["providers"]["aerolink"]["models"],
            {"gpt-5.6-terra": {"name": "Terra"}, "gpt-5.1": {}},
        )
        self.assertEqual(self._doc()["model"], "gpt-5.1")
        self.assertNotIn("models", self.cfg.read_text(encoding="utf-8"))  # 不污染 config.toml

    def test_enabling_another_provider_keeps_both_model_lists(self):
        self._put({**self._state(), "providers": {
            **self._state()["providers"],
            "agnes": {"name": "Agnes", "settings": {"apiKey": "sk-a"},
                      "models": {"agnes-model": {}}},
        }})
        r = main.codex_enable_provider("agnes")
        self.assertEqual(r["providers"]["agnes"]["models"], {"agnes-model": {}})
        self.assertEqual(r["providers"]["aerolink"]["models"], {})


OPENCODE_SRC = {
    "providers": {
        "huoshan": {
            "name": "Huoshan",
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"apiKey": "ark-src", "baseURL": "https://ark.example.com/api/coding/v3"},
            "models": {"deepseek-v4-flash": {"name": "Flash"}, "glm-5.3-flash": {}},
        },
        "nokey": {
            "name": "NoKey",
            "settings": {"baseURL": "https://nokey.example.com/v1"},
        },
    }
}
DISABLED_SRC = {
    "legacy-off": {
        "name": "Legacy Off",
        "settings": {"apiKey": "sk-off", "baseURL": "https://off.example.com/v1"},
        "models": {},
    }
}


class CodexImportTest(unittest.TestCase):
    """从 opencode 导入到 codex。两个配置路径都要沙箱化。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.cfg = d / "config.toml"
        self.auth = d / "auth.json"
        self.keys_path = d / "codex.keys.json"
        self.models_path = d / "codex.models.json"
        codex.CONFIG_PATH, codex.AUTH_PATH = self.cfg, self.auth
        codex.MODELS_PATH, codex.KEYS_PATH = self.models_path, self.keys_path
        self.cfg.write_text(ORIGINAL, encoding="utf-8")
        self.auth.write_text('{"OPENAI_API_KEY": "sk-real"}', encoding="utf-8")

        self.oc = d / "opencode.json"
        self.oc_disabled = d / "opencode.disabled.json"
        self.oc.write_text(json.dumps(OPENCODE_SRC), encoding="utf-8")
        self.oc_disabled.write_text(json.dumps(DISABLED_SRC), encoding="utf-8")
        main.CONFIG_PATH, main.DISABLED_PATH = self.oc, self.oc_disabled

    def tearDown(self):
        self.tmp.cleanup()

    def _import(self, items, **kw):
        return asyncio.run(main.codex_import(FakeRequest({"items": items, **kw})))

    def _add(self, pid, body):
        return asyncio.run(main.codex_add_provider(pid, FakeRequest(body)))

    def _doc(self):
        return tomllib.loads(self.cfg.read_text(encoding="utf-8"))

    # ── 候选清单 ──
    def test_candidates_cover_enabled_and_disabled(self):
        ids = [i["id"] for i in main.codex_import_candidates()["items"]]
        self.assertEqual(ids, ["huoshan", "legacy-off", "nokey"])  # 含停用 sidecar 里的

    def test_candidates_never_expose_the_key(self):
        raw = json.dumps(main.codex_import_candidates())
        self.assertNotIn("ark-src", raw)
        item = next(i for i in main.codex_import_candidates()["items"] if i["id"] == "huoshan")
        self.assertTrue(item["hasKey"])
        self.assertFalse(next(i for i in main.codex_import_candidates()["items"] if i["id"] == "nokey")["hasKey"])

    def test_candidates_flag_name_collisions(self):
        items = {i["id"]: i for i in main.codex_import_candidates()["items"]}
        self.assertFalse(items["huoshan"]["exists"])   # codex 侧叫 aerolink
        self.assertEqual(items["legacy-off"]["modelCount"], 0)
        self.assertEqual(items["huoshan"]["modelCount"], 2)

    # ── 导入 ──
    def test_import_maps_every_field(self):
        r = self._import([{"id": "huoshan", "wireApi": "chat"}])
        self.assertEqual(r["imported"], ["huoshan"])
        tbl = self._doc()["model_providers"]["huoshan"]
        self.assertEqual(tbl["name"], "Huoshan")
        self.assertEqual(tbl["base_url"], "https://ark.example.com/api/coding/v3")  # 不改写
        self.assertEqual(tbl["wire_api"], "chat")
        self.assertIs(tbl["requires_openai_auth"], True)
        self.assertNotIn("env_key", tbl)
        # key 进了存档（未激活，不占 auth.json 槽位）；模型进了 models sidecar
        self.assertEqual(json.loads(self.keys_path.read_text())["huoshan"], "ark-src")
        self.assertEqual(json.loads(self.auth.read_text())["OPENAI_API_KEY"], "sk-real")
        self.assertEqual(sorted(r["providers"]["huoshan"]["models"]), ["deepseek-v4-flash", "glm-5.3-flash"])

    def test_import_can_bulk_and_includes_disabled_sidecar(self):
        r = self._import([{"id": "huoshan"}, {"id": "legacy-off"}, {"id": "nokey"}])
        self.assertEqual(sorted(r["imported"]), ["huoshan", "legacy-off", "nokey"])
        self.assertEqual(sorted(r["providers"]), ["aerolink", "huoshan", "legacy-off", "nokey"])

    def test_import_does_not_touch_the_active_pointer(self):
        self._import([{"id": "huoshan"}])
        self.assertEqual(self._doc()["model_provider"], "aerolink")

    def test_import_skips_collisions_unless_overwrite(self):
        self._add("huoshan", {"name": "Codex 原版", "settings": {"apiKey": "sk-codex"}})
        r = self._import([{"id": "huoshan", "wireApi": "chat"}])
        self.assertEqual(r["imported"], [])
        self.assertEqual(r["skipped"], [{"id": "huoshan", "reason": "codex 侧已存在"}])
        self.assertEqual(r["providers"]["huoshan"]["settings"]["apiKey"], "sk-codex")  # 原样保留

        r = self._import([{"id": "huoshan", "wireApi": "chat"}], overwrite=True)
        self.assertEqual(r["imported"], ["huoshan"])
        self.assertEqual(r["providers"]["huoshan"]["settings"]["apiKey"], "ark-src")

    def test_import_reports_vanished_source(self):
        r = self._import([{"id": "ghost", "wireApi": "chat"}])
        self.assertEqual(r["skipped"], [{"id": "ghost", "reason": "opencode 侧已不存在"}])

    def test_import_rejects_bogus_wire_api(self):
        with self.assertRaises(HTTPException) as cm:
            self._import([{"id": "huoshan", "wireApi": "grpc"}])
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("responses", cm.exception.detail)

    def test_import_defaults_wire_api_to_responses(self):
        """codex-cli 0.155+ 拒绝 wire_api = "chat"（整份配置加载失败），故默认必须是 responses。"""
        self._import([{"id": "huoshan"}])
        self.assertEqual(self._doc()["model_providers"]["huoshan"]["wire_api"], "responses")

    def test_import_tolerates_malformed_source_entries(self):
        broken = {"providers": {"ok": {"name": "Ok", "settings": {"baseURL": "u"}}, "bad": "不是对象"}}
        self.oc.write_text(json.dumps(broken), encoding="utf-8")
        self.oc_disabled.unlink()
        self.assertEqual([i["id"] for i in main.codex_import_candidates()["items"]], ["ok"])
        self.assertEqual(self._import([{"id": "ok"}])["imported"], ["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
