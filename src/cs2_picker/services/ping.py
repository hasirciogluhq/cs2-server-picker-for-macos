import platform
import re
import subprocess
from typing import Optional

from cs2_picker.core.constants import PING_TIMEOUT_MS


def ping_ip(ip: str, timeout_ms: int = PING_TIMEOUT_MS) -> Optional[int]:
    """
    Tek IP'ye ICMP ping.
    macOS: -W = bekleme suresi (milisaniye)
    Linux: -W = bekleme suresi (saniye)
    """
    system = platform.system()
    try:
        if system == "Darwin":
            # Eski kod timeout_ms//1000 kullaniyordu -> 5000ms icin -W 5 (= 5ms!) hata
            cmd = ["ping", "-c", "1", "-W", str(timeout_ms), ip]
            proc_timeout = (timeout_ms / 1000) + 3
        else:
            wait_sec = max(1, (timeout_ms + 999) // 1000)
            cmd = ["ping", "-c", "1", "-W", str(wait_sec), ip]
            proc_timeout = wait_sec + 3

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=proc_timeout,
        )
        if result.returncode != 0:
            return None

        output = result.stdout + result.stderr
        # time=12.345 ms  veya  time=12.345ms
        match = re.search(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
        if match:
            return int(float(match.group(1)))
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None


def ping_server(
    addresses: str,
    blocked: bool = False,
    timeout_ms: int = PING_TIMEOUT_MS,
) -> tuple[str, str]:
    if blocked:
        return "Engelli", "blocked"

    for ip in addresses.split(","):
        ip = ip.strip()
        if not ip:
            continue
        latency = ping_ip(ip, timeout_ms=timeout_ms)
        if latency is not None and latency >= 0:
            return f"{latency} ms", "ok"

    # VB: "Ping timed out, try again..."
    return "Zaman aşımı, tekrar dene…", "timeout"
