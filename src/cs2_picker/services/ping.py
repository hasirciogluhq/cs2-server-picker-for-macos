import platform
import re
import subprocess
from typing import Optional


def ping_ip(ip: str, timeout_ms: int = 2000) -> Optional[int]:
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), ip],
                capture_output=True,
                text=True,
                timeout=(timeout_ms / 1000) + 1,
            )
        else:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(timeout_ms), ip],
                capture_output=True,
                text=True,
                timeout=(timeout_ms / 1000) + 1,
            )
        if result.returncode != 0:
            return None
        match = re.search(r"time=(\d+(?:\.\d+)?)\s*ms", result.stdout)
        if match:
            return int(float(match.group(1)))
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None


def ping_server(addresses: str, blocked: bool = False) -> tuple[str, str]:
    if blocked:
        return "Engelli", "blocked"

    for ip in addresses.split(","):
        ip = ip.strip()
        if not ip:
            continue
        latency = ping_ip(ip)
        if latency is not None and latency > 0:
            return f"{latency} ms", "ok"

    return "Zaman aşımı", "timeout"
