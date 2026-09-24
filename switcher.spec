# switcher.spec — PyInstaller 打包配置（Windows / macOS / Linux 通用）
# 用法：pyinstaller switcher.spec  （需在对应平台各自打包一次）
import sys

from PyInstaller.utils.hooks import collect_all


def _collect(pkg):
    """收集模块的全部数据/二进制/隐藏导入，失败则静默跳过。"""
    try:
        datas, binaries, hiddenimports = collect_all(pkg)
    except Exception:
        return [], [], []
    return datas, binaries, hiddenimports


datas, binaries, hiddenimports = [], [], []

# FastAPI 栈的框架包，内部有大量动态导入，必须完整收集
for pkg in ("uvicorn", "fastapi", "starlette", "pydantic", "httptools", "websockets"):
    d, b, h = _collect(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# uvloop 不支持 Windows，仅在非 Windows 平台收集
if sys.platform != "win32":
    d, b, h = _collect("uvloop")
    datas += d
    binaries += b
    hiddenimports += h

# 前端静态资源
datas += [("static", "static")]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="switcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 保留控制台：可看地址/日志，关闭窗口即退出。想无黑框改 False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
