import json
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Set

from cs2_picker.core.config import (
    BLOCKED_FILE,
    BLOCKED_IPS_FILE,
    LAST_PF_RULESET_FILE,
    PF_MARKER_BEGIN,
    PF_MARKER_END,
    PF_RULES_FILE,
    SUPPORT_DIR,
)

PF_CONF = Path("/etc/pf.conf")


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
    """One administrator prompt per block/unblock operation."""
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


def _collect_blocked_ips(blocked: Set[str], server_dict: Dict[str, str]) -> list[str]:
    ips: set[str] = set()
    for region in blocked:
        raw = server_dict.get(region, "")
        for ip in raw.split(","):
            ip = ip.strip()
            if ip:
                ips.add(ip)
    return sorted(ips)


def _sync_blocked_ips_file(blocked: Set[str], server_dict: Dict[str, str]) -> None:
    ips = _collect_blocked_ips(blocked, server_dict)
    if ips:
        BLOCKED_IPS_FILE.write_text("\n".join(ips) + "\n")
    elif BLOCKED_IPS_FILE.exists():
        BLOCKED_IPS_FILE.unlink()


def _build_pf_rules(blocked: Set[str], server_dict: Dict[str, str]) -> str:
    lines = ["# CS2 Server Picker — auto-generated", ""]
    ips = _collect_blocked_ips(blocked, server_dict)
    if not ips:
        return "\n".join(lines) + "\n"

    ip_list = ", ".join(ips)
    lines.extend(
        [
            "table <cs2picker_blocked> file "
            f'"{BLOCKED_IPS_FILE}"',
            "block out quick proto {tcp, udp} from any to <cs2picker_blocked>",
            "block in quick proto {tcp, udp} from <cs2picker_blocked> to any",
            "",
            f"# flat list: {ip_list}",
            "",
        ]
    )
    return "\n".join(lines)


def _build_ruleset_section(blocked: Set[str], server_dict: Dict[str, str]) -> list[str]:
    ips = _collect_blocked_ips(blocked, server_dict)
    if not ips:
        return []

    table_path = str(BLOCKED_IPS_FILE).replace("\\", "\\\\").replace('"', '\\"')
    return [
        PF_MARKER_BEGIN,
        f'table <cs2picker_blocked> file "{table_path}"',
        "block out quick proto {tcp, udp} from any to <cs2picker_blocked>",
        "block in quick proto {tcp, udp} from <cs2picker_blocked> to any",
        PF_MARKER_END,
    ]


def _strip_cs2picker_rules(content: str) -> list[str]:
    """Remove our previous rules (markers, table, block lines)."""
    lines: list[str] = []
    skipping = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == PF_MARKER_BEGIN:
            skipping = True
            continue
        if stripped == PF_MARKER_END:
            skipping = False
            continue
        if skipping:
            continue
        if "cs2picker_blocked" in stripped:
            continue
        if stripped.startswith("# CS2PICKER"):
            continue
        lines.append(line)
    return lines


def _load_base_ruleset() -> str:
    if LAST_PF_RULESET_FILE.exists():
        try:
            text = LAST_PF_RULESET_FILE.read_text(encoding="utf-8")
            if text.strip():
                return text
        except OSError:
            pass
    if PF_CONF.is_file():
        try:
            return PF_CONF.read_text(encoding="utf-8")
        except OSError:
            pass
    return ""


def _merge_ruleset(base: str, section: list[str]) -> str:
    lines = _strip_cs2picker_rules(base)
    if not section:
        merged = "\n".join(lines)
        return merged + ("\n" if merged and not merged.endswith("\n") else "")

    insert_at = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("pass out") or stripped.startswith("pass in"):
            insert_at = index
            break

    merged_lines = lines[:insert_at] + section + [""] + lines[insert_at:]
    merged = "\n".join(merged_lines)
    return merged + ("\n" if not merged.endswith("\n") else "")


def _apply_pf_rules(rules_content: str, blocked: Set[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    _ensure_dirs()
    PF_RULES_FILE.write_text(rules_content)
    _sync_blocked_ips_file(blocked, server_dict)

    section = _build_ruleset_section(blocked, server_dict)
    expect_blocks = bool(section)
    merged = _merge_ruleset(_load_base_ruleset(), section)

    merged_path = SUPPORT_DIR / "merged.pf"
    merged_path.write_text(merged, encoding="utf-8")
    quoted = shlex.quote(str(merged_path))
    quoted_ips = shlex.quote(str(BLOCKED_IPS_FILE))

    if expect_blocks:
        apply_cmd = (
            f"/sbin/pfctl -vnf {quoted} >/dev/null 2>&1 || exit 1; "
            f"/sbin/pfctl -e 2>/dev/null; "
            f"/sbin/pfctl -f {quoted} 2>&1; "
            f"/sbin/pfctl -t cs2picker_blocked -T replace -f {quoted_ips} 2>&1; "
            f"/sbin/pfctl -sr 2>&1 | grep -q cs2picker_blocked"
        )
    else:
        apply_cmd = (
            f"/sbin/pfctl -vnf {quoted} >/dev/null 2>&1 || exit 1; "
            f"/sbin/pfctl -e 2>/dev/null; "
            f"/sbin/pfctl -f {quoted} 2>&1; "
            f"! /sbin/pfctl -sr 2>&1 | grep -q cs2picker_blocked"
        )

    ok, output = _run_sudo(apply_cmd)
    if not ok:
        if PF_CONF.is_file() and not LAST_PF_RULESET_FILE.exists():
            merged = _merge_ruleset(PF_CONF.read_text(encoding="utf-8"), section)
            merged_path.write_text(merged, encoding="utf-8")
            ok, output = _run_sudo(apply_cmd)
        if not ok:
            return False, output or "Failed to apply pf firewall rules."

    LAST_PF_RULESET_FILE.write_text(merged, encoding="utf-8")
    return True, output


def block_regions(regions: list[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    blocked = load_blocked()
    blocked.update(regions)
    rules = _build_pf_rules(blocked, server_dict)
    ok, err = _apply_pf_rules(rules, blocked, server_dict)
    if ok:
        save_blocked(blocked)
    return ok, err


def unblock_regions(regions: list[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    blocked = load_blocked()
    for r in regions:
        blocked.discard(r)
    rules = _build_pf_rules(blocked, server_dict)
    ok, err = _apply_pf_rules(rules, blocked, server_dict)
    if ok:
        save_blocked(blocked)
    return ok, err


def block_all(server_dict: Dict[str, str]) -> tuple[bool, str]:
    return block_regions(list(server_dict.keys()), server_dict)


def unblock_all(server_dict: Dict[str, str]) -> tuple[bool, str]:
    blocked: Set[str] = set()
    rules = _build_pf_rules(blocked, server_dict)
    ok, err = _apply_pf_rules(rules, blocked, server_dict)
    if ok:
        save_blocked(set())
    return ok, err
