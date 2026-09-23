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

# OpenCode Providers Editor (English)

A cross-platform web editor for managing `providers` in `opencode.json`.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Open `http://127.0.0.1:7788` in your browser (auto-opened on launch).
