from pathlib import Path

from cs2_picker._version import __version__

APP_NAME = "CS2 Server Picker"
APP_VERSION = __version__
APP_BUNDLE_ID = "com.cs2serverpicker.macos"

SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "CS2ServerPicker"
SETTINGS_FILE = SUPPORT_DIR / "settings.json"
BLOCKED_FILE = SUPPORT_DIR / "blocked.json"
PF_RULES_FILE = SUPPORT_DIR / "rules.pf"
BLOCKED_IPS_FILE = SUPPORT_DIR / "blocked-ips.txt"
LAST_PF_RULESET_FILE = SUPPORT_DIR / "last-ruleset.pf"
PF_MARKER_BEGIN = "# CS2PICKER-BEGIN"
PF_MARKER_END = "# CS2PICKER-END"
