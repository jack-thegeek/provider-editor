"""
Cross-platform config path resolver for opencode.json.

Windows : %APPDATA%\\opencode\\opencode.json
macOS   : ~/.config/opencode/opencode.json
Linux   : ~/.config/opencode/opencode.json
"""

import os
import sys
from pathlib import Path


def get_config_path() -> Path:
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA", "")
        if not app_data:
            raise RuntimeError("APPDATA environment variable is not set")
        return Path(app_data) / "opencode" / "opencode.json"
    else:
        return Path.home() / ".config" / "opencode" / "opencode.json"


CONFIG_PATH: Path = get_config_path()
