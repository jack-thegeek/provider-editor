# AI CLI Provider Editor

一个跨平台 Web 编辑器，可视化管理 **OpenCode** 与 **Codex** 的 provider 配置。

## 特性

- 🎯 双目标切换：顶栏一键在 OpenCode / Codex 之间切换，同一套 UI
- 🗂️ Provider 列表 + 快速搜索
- 🔘 启用/停用开关
  - **OpenCode**（共存模式）：可同时启用多个，启用的写入 `opencode.json`，停用的移到独立 sidecar 文件
  - **Codex**（切换模式）：全部以 `[model_providers.*]` 段共存，开关即移动顶层 `model_provider` 指针，**同时只有一个生效**
- ✏️ 可视化表单编辑
  - OpenCode：名称、Package、API Key、Base URL、Models
  - Codex：名称、API Key、Base URL、Wire API、模型列表（认证方式固定由后端接管，不在界面出现）
- ➕ 新增 / 📋 复制 / 🗑️ 删除 Provider
- 📥 **从 OpenCode 导入到 Codex**：Codex 侧栏的导入按钮，勾选后一次性搬过去（可全选）
- 🌐 从接口拉取模型列表（两个目标都适用）
- 🎯 **当前生效的模型**：Codex 同时只激活一个模型，卡片里被标记为「当前生效」的那一行即写入顶层 `model` 的值；点其他行的「当前」即可切换
- 📝 原始编辑器：OpenCode 为 JSON，Codex 为 **config.toml 全文**（含本工具不管理的 mcp_servers / projects 等段）
- 💾 写入前自动备份（`.bak`）+ 语法校验（TOML 由服务端 `tomllib` 校验后才落盘）
- 🚀 启动时自动打开浏览器
- ⌨️ `Ctrl+S` / `Cmd+S` 快捷保存
- 🖥️ 支持 Windows / macOS / Ubuntu

## 配置文件路径

| 目标 | 文件 |
|------|------|
| OpenCode | Linux/macOS `~/.config/opencode/opencode.json`；Windows `%APPDATA%\opencode\opencode.json` |
| OpenCode 停用项 | 同目录下 `opencode.disabled.json`（opencode 不读，仅本工具用） |
| Codex | `~/.codex/config.toml` |
| Codex 凭据 | `~/.codex/auth.json`（仅 `OPENAI_API_KEY` = 激活 provider 的 key） |
| Codex 候选模型 | `~/.codex/codex.models.json`（codex 不读，仅本工具用） |
| Codex key 存档 | `~/.codex/codex.keys.json`（`0600`，codex 不读，仅本工具用） |

## 安装

```bash
# 进入项目目录
cd switcher

# 安装依赖（建议使用虚拟环境）
pip install -r requirements.txt
```

## 启动

```bash
python main.py
```

服务默认在 `http://127.0.0.1:7788` 启动，并自动打开浏览器。
端口被占用时会自动往后递增。

---

## 从 OpenCode 导入到 Codex

切到 **Codex** 目标，点侧栏的导入按钮（⬇ 图标），弹窗列出 OpenCode 侧的全部 provider —— 包括 `opencode.json` 里的和停用 sidecar 里的。勾选后一次导入，支持全选。

**字段映射**

| OpenCode | Codex |
|----------|-------|
| provider `id` | `[model_providers.<id>]` 段名 |
| `name` | `name` |
| `settings.baseURL` | `base_url`（**不改写**） |
| `settings.apiKey` | 进 `codex.keys.json` 存档，provider 激活时写入 `auth.json` 槽位 |
| `models` | `codex.models.json` 候选列表 |
| `package` | 丢弃（codex 没有对应概念） |
| —— | `requires_openai_auth = true`（后端固定写入，见下节） |

`baseURL` 不用改写：OpenCode 打 `{base}/chat/completions`，Codex 打 `{base}/responses`，两者同构，实测 POST 路径一致。

**几个边界**

- **导入只新增，不动激活指针。** 谁生效是独立的一次决定 —— codex 切换模式下你可能想先导入 18 个再挑一个激活。
- **同名默认跳过。** 弹窗里已存在的项标「已存在」并置灰；要覆盖得先勾上方的「覆盖同名项」。
- **`wire_api` 逐项选。** 这是 codex 的概念，OpenCode 侧推断不出来。默认 `responses` —— codex-cli 0.155+ 会直接拒绝 `wire_api = "chat"` 并让整份 `config.toml` 拒绝加载（`wire_api = "chat" is no longer supported`），下拉里那项只留给更老的版本。
- **key 不经浏览器。** 候选清单只带 `hasKey` 布尔标记，导入时由后端直接从磁盘搬运。

---

## Codex 侧的三点说明

1. **API Key 的存放方式**（这条踩过坑，结论来自 `codex doctor` + 本地 echo server 实测，不是推测）：

   - `env_key` 是**进程环境变量名**，走 `std::env::var()`。codex **不会**把 `auth.json` 里的值注入环境 —— 把 key 写进 `auth.json` 再让 `env_key` 指过去行不通，`codex doctor` 会报 `provider auth env var XXX (missing)`。
   - 真正能用的是 `requires_openai_auth = true`：`auth.json` 里 codex 只认 `OPENAI_API_KEY` 这一个键，命中后它会真的发出去（实测 `Authorization: Bearer <该值>`）。
   - 因为 codex 同时只激活一个 provider，`auth.json` 的单个 `OPENAI_API_KEY` 槽位就够用。本工具在每个 provider 段固定写 `requires_openai_auth = true`、**删掉 `env_key` 行**，并把各 provider 的 key 全量存在 sidecar `codex.keys.json`（`0600`，codex 不读）；切换 provider 时改写 `auth.json` 那个槽位。
   - 老配置（`env_key` + `auth.json[env_key]`）首次保存时自动迁移：key 捞进 sidecar，`env_key` 行删除。`auth.json` 里会留下一个孤儿条目（如 `HUOSHAN_API_KEY`）—— 无法区分它是不是你自己放的，所以不自动删，需要时手动清理。
2. **只改该改的。** 写入采用行级段落手术，仅重写 `[model_providers.*]` 段与顶层 `model_provider` / `model` 两行；注释、`mcp_servers`、`projects`、`tui` 以及 provider 段内的其他键（如 `query_params`）逐字节保留。空保存不会产生任何 diff。
3. **模型列表存在 sidecar 里。** Codex 的 `config.toml` 没有 per-provider 模型字段（写进去 codex 认不了），所以候选列表落到 `~/.codex/codex.models.json`，codex 不读这个文件。真正生效的模型是顶层 `model`，界面里被标记为「当前生效」的那一行；即使它不在候选列表里（比如手工写的或上游已下架），也会自动补进列表并标出来。

---

## 测试

```bash
.venv/bin/python -m unittest test_codex test_codex_api
```

52 个用例，全部在临时目录上进行，**不会触碰真实的 `~/.codex` 或 `~/.config/opencode`**。

---

## 打包为单文件可执行（双击即用）

用 PyInstaller 打成单文件，双击后自动启动本地服务并打开浏览器，无需安装 Python。

> PyInstaller **不支持交叉编译**：Windows 版需在 Windows 上打包，macOS 版需在 macOS 上打包，Linux 版在 Linux 上打包。三平台共用同一份 `switcher.spec`。

### 打包命令

```bash
# 安装 PyInstaller（建议虚拟环境）
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt pyinstaller

# 打包（Windows 用 .venv\Scripts\pyinstaller）
.venv/bin/pyinstaller switcher.spec --noconfirm --clean
```

产物：
- Linux → `dist/switcher`
- Windows → `dist/switcher.exe`
- macOS → `dist/switcher`

### 使用

直接双击（或终端执行）产物文件即可，浏览器会自动打开 `http://127.0.0.1:7788`。
端口被占用时自动向后递增；关闭控制台窗口即退出服务。

### 可选项

- **无黑框版**：把 `switcher.spec` 里的 `console=True` 改为 `False` 后重新打包（Windows/macOS 下更像原生应用，但看不到日志）。
- **固定端口**：`main.py` 支持环境变量 `PORT` / `HOST` / `OPEN_BROWSER`（如 `PORT=9000`）。
- **图标**：在 spec 的 `EXE()` 里加 `icon="icon.ico"`（Windows）/ `icon="icon.icns"`（macOS）。

---

# AI CLI Provider Editor (English)

A cross-platform web editor for managing providers in **OpenCode** (`opencode.json`) and **Codex** (`config.toml` + `auth.json`).

- **OpenCode** is coexist-mode: several providers can be enabled at once.
- **Codex** is switch-mode: all providers coexist as `[model_providers.*]` sections, but the top-level `model_provider` selects exactly one active provider.

**Importing:** the Codex sidebar has an ⬇ button that copies providers from your OpenCode config in one go — id, name, `baseURL` (verbatim), API key and model list. Import only adds sections; it never moves the active pointer. Existing same-name entries are skipped unless you tick "overwrite". `wire_api` defaults to `responses` because codex-cli 0.155+ rejects `wire_api = "chat"` outright and refuses to load the whole config.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Open `http://127.0.0.1:7788` in your browser (auto-opened on launch).

## Tests

```bash
.venv/bin/python -m unittest test_codex test_codex_api
```

All 52 cases run against temp directories and never touch your real `~/.codex` or `~/.config/opencode`.
