# GitHub releases / update checks
GITHUB_REPO = "hasirciogluhq/cs2-server-picker-for-macos"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
UPDATE_CHECK_INTERVAL_MS = 60_000

STEAM_SDR_URL = "https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=730"
PF_ANCHOR = "com.apple/cs2serverpicker"

# .NET Ping default is ~5000ms
PING_TIMEOUT_MS = 5000

CLUSTER_DICT = {
    "China": ["Perfect", "Hong Kong", "Alibaba", "Tencent"],
    "Japan": ["Tokyo"],
    "Stockholm (Sweden)": ["Stockholm"],
    "India": ["Chennai", "Mumbai"],
}
