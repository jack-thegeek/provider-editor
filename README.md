# OpenCode Providers Editor

一个跨平台 Web 编辑器，用于可视化管理 `opencode.json` 中的 `providers` 配置。

## 特性

- 🗂️ Provider 列表 + 快速搜索
- ✏️ 可视化表单编辑（名称、API Key、Base URL、Models）
- ➕ 新增 / 🗑️ 删除 Provider
- 📝 原始 JSON 编辑器（实时校验）
- 💾 写入前自动备份（`.json.bak`）
- 🚀 启动时自动打开浏览器
- ⌨️ `Ctrl+S` / `Cmd+S` 快捷保存
- 🖥️ 支持 Windows / macOS / Ubuntu

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

## 配置文件路径

| 平台 | 路径 |
|------|------|
| Linux / macOS | `~/.config/opencode/opencode.json` |
| Windows | `%APPDATA%\opencode\opencode.json` |

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

# OpenCode Providers Editor (English)

A cross-platform web editor for managing `providers` in `opencode.json`.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Open `http://127.0.0.1:7788` in your browser (auto-opened on launch).
