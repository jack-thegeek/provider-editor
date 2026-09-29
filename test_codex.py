"""
codex.py 的行级 TOML 手术校验 —— 重点是「不弄坏用户配置里我们不管的部分」。

跑法： .venv/bin/python -m unittest test_codex
"""
import json
import tempfile
import tomllib
import unittest
from pathlib import Path

import codex

SAMPLE = '''# 我的 codex 配置
model_provider = "aerolink"
model = "gpt-5.6-terra"
model_reasoning_effort = "high"

[model_providers.aerolink]
name = "aerolink"
base_url = "https://cgapi.aerolink.lat"
wire_api = "responses"
requires_openai_auth = true

[model_providers.legacy]
name = "Legacy"
base_url = "https://old.example.com"
requires_openai_auth = true
query_params = { "v" = "1" }
wire_api = "responses"

[windows]
sandbox = "elevated"

[mcp_servers.codegraph]
command = "codegraph"
args = ["serve", "--mcp"]
'''

# 迁移前的老配置：靠 env_key 指向 auth.json 里的变量名（这条路径实际不通，
# 见 codex.py 模块注释）。仅供迁移测试使用。
LEGACY_SAMPLE = SAMPLE.replace(
    'requires_openai_auth = true\nquery_params', 'env_key = "OLD_API_KEY"\nquery_params'
)


class CodexTomlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.cfg = d / "config.toml"
        self.auth = d / "auth.json"
        self.models_path = d / "codex.models.json"
        self.keys_path = d / "codex.keys.json"
        codex.CONFIG_PATH, codex.AUTH_PATH = self.cfg, self.auth
        codex.MODELS_PATH, codex.KEYS_PATH = self.models_path, self.keys_path
        self.cfg.write_text(SAMPLE, encoding="utf-8")
        self.auth.write_text(
            '{"OPENAI_API_KEY": "aero_live_xxx", "VB_API_KEY": "sk-keepme", "OLD_API_KEY": "sk-legacy-old"}',
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _doc(self):
        return tomllib.loads(self.cfg.read_text(encoding="utf-8"))

    # ── 读 ──
    def test_reads_providers_active_and_key(self):
        s = codex.read_state()
        self.assertEqual(sorted(s["providers"]), ["aerolink", "legacy"])
        self.assertEqual(s["active"], "aerolink")
        self.assertEqual(s["model"], "gpt-5.6-terra")
        # 激活项的 key 从 auth.json 的 OPENAI_API_KEY 读；非激活项没有 key 可读
        self.assertEqual(s["providers"]["aerolink"]["settings"]["apiKey"], "aero_live_xxx")
        self.assertEqual(s["providers"]["legacy"]["settings"]["apiKey"], "")
        # 认证方式不外露给前端
        self.assertNotIn("envKey", s["providers"]["aerolink"]["settings"])

    # ── 写：不动无关内容 ──
    def test_no_op_write_preserves_bytes(self):
        before = self.cfg.read_text(encoding="utf-8")
        codex.write_state(codex.read_state()["providers"], "aerolink", "gpt-5.6-terra")
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), before)

    def test_write_keeps_comments_mcp_and_unknown_keys(self):
        s = codex.read_state()
        s["providers"]["aerolink"]["settings"]["baseURL"] = "https://new.example.com"
        codex.write_state(s["providers"], s["active"], s["model"])
        out = self.cfg.read_text(encoding="utf-8")
        self.assertIn("# 我的 codex 配置", out)          # 注释
        self.assertIn("[mcp_servers.codegraph]", out)   # 不归我们管的表
        self.assertIn("[windows]", out)
        self.assertIn('args = ["serve", "--mcp"]', out)
        self.assertIn('query_params = { "v" = "1" }', out)  # legacy 段内的额外键
        self.assertIn("https://new.example.com", out)
        self.assertEqual(tomllib.loads(out)["model_providers"]["aerolink"]["base_url"],
                         "https://new.example.com")

    def test_activate_moves_pointer_only(self):
        codex.write_state(codex.read_state()["providers"], "legacy", "gpt-5.6-terra")
        d = self._doc()
        self.assertEqual(d["model_provider"], "legacy")
        self.assertIn("aerolink", d["model_providers"])  # 段落仍在
        self.assertEqual(d["model"], "gpt-5.6-terra")                   # model 未被动

    def test_delete_drops_section_and_falls_back(self):
        s = codex.read_state()
        del s["providers"]["aerolink"]  # 删掉当前激活项
        codex.write_state(s["providers"], "aerolink", s["model"])
        d = self._doc()
        self.assertNotIn("aerolink", d["model_providers"])
        self.assertEqual(d["model_provider"], "legacy")  # 指针自动回退
        self.assertEqual(self._doc()["model_providers"]["legacy"]["base_url"], "https://old.example.com")

    def test_delete_all_clears_pointer(self):
        codex.write_state({}, "aerolink", "gpt-5.6-terra")
        d = self._doc()
        self.assertEqual(d.get("model_provider", None), None)
        self.assertEqual(d.get("model_providers", {}), {})
        self.assertIn("[mcp_servers.codegraph]", self.cfg.read_text(encoding="utf-8"))

    # ── 写：认证（requires_openai_auth + auth.json 的 OPENAI_API_KEY）──
    def test_env_key_line_is_always_stripped(self):
        """env_key 走 std::env::var()，auth.json 桥不过去 —— 那一行必须消失。"""
        s = codex.read_state()
        codex.write_state(s["providers"], s["active"], s["model"])
        for pid, tbl in self._doc()["model_providers"].items():
            self.assertNotIn("env_key", tbl, f"{pid} 仍残留 env_key")
            self.assertIs(tbl["requires_openai_auth"], True)

    def test_auth_json_holds_active_provider_key_only(self):
        s = codex.read_state()
        s["providers"]["legacy"]["settings"]["apiKey"] = "sk-legacy"
        codex.write_state(s["providers"], s["active"], s["model"])
        auth = json.loads(self.auth.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(self.auth.read_text())["OPENAI_API_KEY"], "aero_live_xxx")  # 激活的是 aerolink
        self.assertEqual(auth["VB_API_KEY"], "sk-keepme")          # 无关变量不动
        # 非激活项的 key 只能存在 sidecar 里，auth.json 没有它的槽位
        self.assertEqual(json.loads(self.keys_path.read_text())["legacy"], "sk-legacy")
        self.assertNotIn("legacy", auth)

    def test_switching_active_rewrites_the_single_slot(self):
        s = codex.read_state()
        s["providers"]["legacy"]["settings"]["apiKey"] = "sk-legacy"
        codex.write_state(s["providers"], s["active"], s["model"])
        codex.write_state(s["providers"], "legacy", s["model"])
        self.assertEqual(json.loads(self.auth.read_text())["OPENAI_API_KEY"], "sk-legacy")
        # 两个 provider 的 key 都还在存档里，随时能切回去
        self.assertEqual(
            json.loads(self.keys_path.read_text()), {"aerolink": "aero_live_xxx", "legacy": "sk-legacy"}
        )
        codex.write_state(s["providers"], "aerolink", s["model"])
        self.assertEqual(json.loads(self.auth.read_text())["OPENAI_API_KEY"], "aero_live_xxx")

    def test_new_provider_key_goes_to_archive_and_active_slot(self):
        codex.write_state(
            {"my-provider": {"name": "MP", "settings": {"apiKey": "sk-mp", "baseURL": "u"}}},
            "my-provider", "m",
        )
        self.assertEqual(json.loads(self.auth.read_text())["OPENAI_API_KEY"], "sk-mp")
        self.assertEqual(json.loads(self.keys_path.read_text()), {"my-provider": "sk-mp"})

    def test_frontend_cannot_override_auth_mechanism(self):
        """前端伪造 envKey 也不行：认证方式固定由后端接管。"""
        s = codex.read_state()
        s["providers"]["legacy"]["settings"]["envKey"] = "HACKED"
        s["providers"]["legacy"]["settings"]["apiKey"] = "sk-new"
        codex.write_state(s["providers"], s["active"], s["model"])
        self.assertNotIn("env_key", self._doc()["model_providers"]["legacy"])
        self.assertNotIn("HACKED", self.auth.read_text())
        self.assertNotIn("HACKED", self.keys_path.read_text())

    def test_migrates_legacy_env_key_key_into_new_mechanism(self):
        """老配置（env_key + auth.json[env_key]）首次保存后应自动迁到新路径。"""
        self.cfg.write_text(LEGACY_SAMPLE, encoding="utf-8")
        self.assertEqual(self._doc()["model_providers"]["legacy"]["env_key"], "OLD_API_KEY")
        self.assertEqual(codex.read_state()["providers"]["legacy"]["settings"]["apiKey"], "sk-legacy-old")

        s = codex.read_state()
        codex.write_state(s["providers"], s["active"], s["model"])

        tbl = self._doc()["model_providers"]["legacy"]
        self.assertNotIn("env_key", tbl)
        self.assertIs(tbl["requires_openai_auth"], True)
        self.assertEqual(json.loads(self.keys_path.read_text())["legacy"], "sk-legacy-old")
        # 孤儿条目保留（无法区分是不是用户自己放的），但不再被引用
        self.assertIn("OLD_API_KEY", json.loads(self.auth.read_text()))

    def test_keys_sidecar_removed_when_nothing_left(self):
        s = codex.read_state()
        codex.write_state(s["providers"], s["active"], s["model"])
        self.assertTrue(self.keys_path.exists())
        for p in s["providers"].values():
            p["settings"]["apiKey"] = ""
        codex.write_state(s["providers"], s["active"], s["model"])
        self.assertFalse(self.keys_path.exists())
        self.assertEqual(json.loads(self.auth.read_text())["OPENAI_API_KEY"], "aero_live_xxx")  # 不动

    def test_keys_sidecar_is_private(self):
        s = codex.read_state()
        codex.write_state(s["providers"], s["active"], s["model"])
        self.assertEqual(oct(self.keys_path.stat().st_mode & 0o777), "0o600")

    def test_corrupt_keys_sidecar_degrades_to_empty(self):
        self.keys_path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(codex.read_keys(), {})
        # 激活项仍能从 auth.json 的 OPENAI_API_KEY 兜底
        self.assertEqual(codex.read_state()["providers"]["aerolink"]["settings"]["apiKey"], "aero_live_xxx")

    # ── 边界 ──
    def test_inline_model_providers_table_is_normalised(self):
        self.cfg.write_text('model_providers = { a = { name = "A", base_url = "u" } }\n', encoding="utf-8")
        s = codex.read_state()
        self.assertEqual(list(s["providers"]), ["a"])
        codex.write_state(s["providers"], "a", "m")
        d = self._doc()
        self.assertEqual(d["model_providers"]["a"]["base_url"], "u")  # 不会因重复键而炸

    def test_quotes_ids_that_are_not_bare_keys(self):
        codex.write_state({"my.provider": {"name": "Dotted", "settings": {"baseURL": "u"}}}, "my.provider", "m")
        d = self._doc()
        self.assertIn("my.provider", d["model_providers"])
        self.assertEqual(d["model_providers"]["my.provider"]["base_url"], "u")
        self.assertEqual(list(codex.read_state()["providers"]), ["my.provider"])

    def test_escapes_quotes_in_values(self):
        codex.write_state({"p": {"name": 'He said "hi"', "settings": {"baseURL": "u"}}}, "p", "m")
        self.assertEqual(self._doc()["model_providers"]["p"]["name"], 'He said "hi"')

    def test_validate_rejects_bad_toml(self):
        self.assertIsNone(codex.validate('a = "b"\n'))
        self.assertIsNotNone(codex.validate("[unclosed\n"))

    def test_missing_config_file(self):
        self.cfg.unlink()
        self.assertEqual(codex.read_state(), {"providers": {}, "active": None, "model": ""})


class CodexModelListTest(unittest.TestCase):
    """候选模型列表：落在 sidecar，config.toml 一行都不许多。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.cfg = d / "config.toml"
        self.auth = d / "auth.json"
        self.models_path = d / "codex.models.json"
        self.keys_path = d / "codex.keys.json"
        codex.CONFIG_PATH, codex.AUTH_PATH = self.cfg, self.auth
        codex.MODELS_PATH, codex.KEYS_PATH = self.models_path, self.keys_path
        self.cfg.write_text(SAMPLE, encoding="utf-8")
        self.auth.write_text('{"OPENAI_API_KEY": "sk-1"}', encoding="utf-8")
        self.before = self.cfg.read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_models_round_trip_through_sidecar(self):
        s = codex.read_state()
        s["providers"]["aerolink"]["models"] = {"gpt-5.6-terra": {"name": "Terra"}, "gpt-5.1": {}}
        codex.write_state(s["providers"], s["active"], s["model"])

        self.assertEqual(
            json.loads(self.models_path.read_text(encoding="utf-8")),
            {"aerolink": {"gpt-5.6-terra": {"name": "Terra"}, "gpt-5.1": {}}},
        )
        back = codex.read_state()["providers"]["aerolink"]["models"]
        self.assertEqual(back, {"gpt-5.6-terra": {"name": "Terra"}, "gpt-5.1": {}})

    def test_models_never_leak_into_config_toml(self):
        """codex 不认识 per-provider models 字段，写进去会污染用户的 config.toml。"""
        s = codex.read_state()
        s["providers"]["aerolink"]["models"] = {"gpt-5.6-terra": {}}
        s["model"] = "gpt-5.6-terra"          # 与 SAMPLE 相同，值不变
        codex.write_state(s["providers"], s["active"], s["model"])

        self.assertNotIn("models", self.cfg.read_text(encoding="utf-8"))
        # 唯一允许的差异是顶层 model 那一行，值没变 ⇒ 整份文件逐字节不变
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), self.before)

    def test_deleting_provider_drops_its_model_list(self):
        s = codex.read_state()
        s["providers"]["aerolink"]["models"] = {"a": {}}
        s["providers"]["legacy"]["models"] = {"b": {}}
        codex.write_state(s["providers"], s["active"], s["model"])
        del s["providers"]["legacy"]
        codex.write_state(s["providers"], s["active"], s["model"])

        self.assertEqual(list(json.loads(self.models_path.read_text(encoding="utf-8"))), ["aerolink"])

    def test_sidecar_removed_when_nothing_left(self):
        s = codex.read_state()
        s["providers"]["aerolink"]["models"] = {"a": {}}
        codex.write_state(s["providers"], s["active"], s["model"])
        self.assertTrue(self.models_path.exists())

        s["providers"]["aerolink"]["models"] = {}
        codex.write_state(s["providers"], s["active"], s["model"])
        self.assertFalse(self.models_path.exists())

    def test_corrupt_sidecar_degrades_to_empty(self):
        self.models_path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(codex.read_models(), {})
        self.assertEqual(codex.read_state()["providers"]["aerolink"]["models"], {})

    def _doc(self):
        return tomllib.loads(self.cfg.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
