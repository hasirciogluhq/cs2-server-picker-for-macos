import json
import subprocess
from typing import Dict, Set

from cs2_picker.core.config import BLOCKED_FILE, PF_RULES_FILE, SUPPORT_DIR
from cs2_picker.core.constants import PF_ANCHOR


def _ensure_dirs() -> None:
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)


def load_blocked() -> Set[str]:
    _ensure_dirs()
    if not BLOCKED_FILE.exists():
        return set()
    try:
        data = json.loads(BLOCKED_FILE.read_text())
        return set(data.get("blocked", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_blocked(blocked: Set[str]) -> None:
    _ensure_dirs()
    BLOCKED_FILE.write_text(json.dumps({"blocked": sorted(blocked)}, indent=2))


def is_blocked(region: str) -> bool:
    return region in load_blocked()


def _run_sudo(shell_cmd: str) -> tuple[bool, str]:
    escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    script = f'do shell script "{escaped}" with administrator privileges'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            return False, err
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Command timed out."
    except OSError as exc:
        return False, str(exc)


def _build_pf_rules(blocked: Set[str], server_dict: Dict[str, str]) -> str:
    lines = ["# CS2 Server Picker — auto-generated", ""]
    for region in sorted(blocked):
        ips = server_dict.get(region, "")
        if not ips:
            continue
        ip_list = ", ".join(ip.strip() for ip in ips.split(",") if ip.strip())
        lines.append(f"# {region.replace(chr(34), '')}")
        lines.append(f"block out quick proto {{tcp, udp}} from any to {{ {ip_list} }}")
        lines.append("")
    return "\n".join(lines)


def _apply_pf_rules(rules_content: str) -> tuple[bool, str]:
    _ensure_dirs()
    PF_RULES_FILE.write_text(rules_content)

    ok, err = _run_sudo(f"/sbin/pfctl -a {PF_ANCHOR} -F all 2>/dev/null; true")
    if not ok:
        return False, err

    if not rules_content.strip() or "block out" not in rules_content:
        return True, ""

    pf_path = str(PF_RULES_FILE).replace('"', '\\"')
    cmd = f"/sbin/pfctl -e 2>/dev/null; /sbin/pfctl -a {PF_ANCHOR} -f \"{pf_path}\""
    return _run_sudo(cmd)


def block_regions(regions: list[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    blocked = load_blocked()
    blocked.update(regions)
    rules = _build_pf_rules(blocked, server_dict)
    ok, err = _apply_pf_rules(rules)
    if ok:
        save_blocked(blocked)
    return ok, err


def unblock_regions(regions: list[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    blocked = load_blocked()
    for r in regions:
        blocked.discard(r)
    rules = _build_pf_rules(blocked, server_dict)
    ok, err = _apply_pf_rules(rules)
    if ok:
        save_blocked(blocked)
    return ok, err


def block_all(server_dict: Dict[str, str]) -> tuple[bool, str]:
    return block_regions(list(server_dict.keys()), server_dict)


def unblock_all(server_dict: Dict[str, str]) -> tuple[bool, str]:
    if not load_blocked():
        return True, ""
    ok, err = _apply_pf_rules("")
    if ok:
        save_blocked(set())
    return ok, err
