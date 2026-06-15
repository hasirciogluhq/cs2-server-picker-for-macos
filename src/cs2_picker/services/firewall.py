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
PF_IPS_TMP = Path("/tmp/cs2picker-blocked-ips.txt")
PF_MERGED_TMP = Path("/tmp/cs2picker-merged.pf")


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


def _validate_regions(regions: list[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    unknown = sorted({region for region in regions if region not in server_dict})
    if not unknown:
        return True, ""
    preview = ", ".join(unknown[:5])
    if len(unknown) > 5:
        preview += f" (+{len(unknown) - 5} more)"
    return False, f"Unknown regions: {preview}"


def _collect_blocked_ips(blocked: Set[str], server_dict: Dict[str, str]) -> list[str]:
    ips: set[str] = set()
    for region in blocked:
        if region not in server_dict:
            raise ValueError(f"Unknown region: {region}")
        raw = server_dict[region]
        for ip in raw.split(","):
            ip = ip.strip()
            if ip:
                ips.add(ip)
    return sorted(ips)


def _describe_state(blocked: Set[str], server_dict: Dict[str, str]) -> str:
    if not blocked:
        return "Applied. No regions blocked."
    ips = _collect_blocked_ips(blocked, server_dict)
    preview = ", ".join(sorted(blocked)[:5])
    if len(blocked) > 5:
        preview += f" (+{len(blocked) - 5} more)"
    return (
        f"Applied. Blocked regions: {len(blocked)}. "
        f"Blocked IPs: {len(ips)}. ({preview})"
    )


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
            "table <cs2picker_blocked>",
            "block out quick proto {tcp, udp} from any to <cs2picker_blocked>",
            "block in quick proto {tcp, udp} from <cs2picker_blocked> to any",
            "",
            f"# blocked regions: {', '.join(sorted(blocked))}",
            f"# blocked ips: {ip_list}",
            "",
        ]
    )
    return "\n".join(lines)


def _build_ruleset_section() -> list[str]:
    return [
        PF_MARKER_BEGIN,
        "table <cs2picker_blocked>",
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


def _rules_active() -> bool:
    if not LAST_PF_RULESET_FILE.exists():
        return False
    try:
        return PF_MARKER_BEGIN in LAST_PF_RULESET_FILE.read_text(encoding="utf-8")
    except OSError:
        return False


def _write_pf_ips_file(ips: list[str]) -> Path:
    content = "\n".join(ips) + "\n" if ips else ""
    PF_IPS_TMP.write_text(content, encoding="utf-8")
    return PF_IPS_TMP


def _write_merged_ruleset(section: list[str]) -> Path:
    merged = _merge_ruleset(_load_base_ruleset(), section)
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    (SUPPORT_DIR / "merged.pf").write_text(merged, encoding="utf-8")
    PF_MERGED_TMP.write_text(merged, encoding="utf-8")
    return PF_MERGED_TMP


def _table_ip_count_cmd() -> str:
    return (
        "/sbin/pfctl -t cs2picker_blocked -T show 2>/dev/null"
        " | /usr/bin/grep -E '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+'"
        " | /usr/bin/wc -l | /usr/bin/tr -d ' '"
    )


def _install_pf_rules() -> tuple[bool, str]:
    _ensure_dirs()
    merged_path = _write_merged_ruleset(_build_ruleset_section())
    quoted_merged = shlex.quote(str(merged_path))
    apply_cmd = (
        f"/sbin/pfctl -vnf {quoted_merged} >/dev/null 2>&1 && "
        f"/sbin/pfctl -e 2>/dev/null; "
        f"/sbin/pfctl -f {quoted_merged} 2>&1 && "
        f"/sbin/pfctl -sr 2>&1 | /usr/bin/grep -q cs2picker_blocked"
    )
    ok, output = _run_sudo(apply_cmd)
    if not ok and PF_CONF.is_file() and not _rules_active():
        merged = _merge_ruleset(PF_CONF.read_text(encoding="utf-8"), _build_ruleset_section())
        PF_MERGED_TMP.write_text(merged, encoding="utf-8")
        ok, output = _run_sudo(apply_cmd)
    if not ok:
        return False, output or "Failed to install pf firewall rules."

    LAST_PF_RULESET_FILE.write_text(PF_MERGED_TMP.read_text(encoding="utf-8"), encoding="utf-8")
    return True, ""


def _replace_table_ips(ips: list[str]) -> tuple[bool, str]:
    if not ips:
        return True, ""

    _write_pf_ips_file(ips)
    quoted_ips = shlex.quote(str(PF_IPS_TMP))
    expected = len(ips)
    count_cmd = _table_ip_count_cmd()
    apply_cmd = (
        f"/sbin/pfctl -t cs2picker_blocked -T flush 2>/dev/null; "
        f"/sbin/pfctl -t cs2picker_blocked -T add -f {quoted_ips} 2>&1 && "
        f"COUNT=$({count_cmd}); test ${{COUNT}} -eq {expected}"
    )
    ok, output = _run_sudo(apply_cmd)
    if not ok:
        detail = output or "Failed to sync pf blocked IP table."
        return False, f"{detail}\n(expected {expected} blocked IPs in pf table)"
    return True, ""


def _remove_pf_rules() -> tuple[bool, str]:
    return _clear_pf_kernel()


def _sync_pf_kernel(ips: list[str]) -> tuple[bool, str]:
    _ensure_dirs()
    if not ips:
        return _remove_pf_rules()

    _write_pf_ips_file(ips)
    merged_path = _write_merged_ruleset(_build_ruleset_section())
    quoted_merged = shlex.quote(str(merged_path))
    quoted_ips = shlex.quote(str(PF_IPS_TMP))
    expected = len(ips)
    count_cmd = _table_ip_count_cmd()

    apply_cmd = (
        f"/sbin/pfctl -vnf {quoted_merged} >/dev/null 2>&1 && "
        f"/sbin/pfctl -e 2>/dev/null; "
        f"/sbin/pfctl -f {quoted_merged} 2>&1 && "
        f"/sbin/pfctl -t cs2picker_blocked -T flush 2>/dev/null; "
        f"/sbin/pfctl -t cs2picker_blocked -T add -f {quoted_ips} 2>&1 && "
        f"COUNT=$({count_cmd}); test ${{COUNT}} -eq {expected}"
    )
    ok, output = _run_sudo(apply_cmd)
    if not ok and PF_CONF.is_file() and not _rules_active():
        merged = _merge_ruleset(PF_CONF.read_text(encoding="utf-8"), _build_ruleset_section())
        PF_MERGED_TMP.write_text(merged, encoding="utf-8")
        ok, output = _run_sudo(apply_cmd)
    if not ok:
        detail = output or "Failed to sync pf blocked IP table."
        return False, f"{detail}\n(expected {expected} blocked IPs in pf table)"

    LAST_PF_RULESET_FILE.write_text(PF_MERGED_TMP.read_text(encoding="utf-8"), encoding="utf-8")
    return True, ""


def _clear_pf_kernel() -> tuple[bool, str]:
    _ensure_dirs()
    merged_path = _write_merged_ruleset([])
    quoted_merged = shlex.quote(str(merged_path))
    apply_cmd = (
        f"/sbin/pfctl -t cs2picker_blocked -T flush 2>/dev/null; "
        f"/sbin/pfctl -vnf {quoted_merged} >/dev/null 2>&1 && "
        f"/sbin/pfctl -e 2>/dev/null; "
        f"/sbin/pfctl -f {quoted_merged} 2>&1 && "
        f"! /sbin/pfctl -sr 2>&1 | /usr/bin/grep -q cs2picker_blocked"
    )
    ok, output = _run_sudo(apply_cmd)
    if not ok and PF_CONF.is_file() and not _rules_active():
        merged = _merge_ruleset(PF_CONF.read_text(encoding="utf-8"), [])
        PF_MERGED_TMP.write_text(merged, encoding="utf-8")
        ok, output = _run_sudo(apply_cmd)
    if not ok:
        return False, output or "Failed to remove pf firewall rules."

    LAST_PF_RULESET_FILE.write_text(PF_MERGED_TMP.read_text(encoding="utf-8"), encoding="utf-8")
    return True, output


def _apply_blocked_state(blocked: Set[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    _ensure_dirs()
    unknown = sorted(blocked - set(server_dict.keys()))
    if unknown:
        preview = ", ".join(unknown[:5])
        if len(unknown) > 5:
            preview += f" (+{len(unknown) - 5} more)"
        return False, f"Unknown regions: {preview}"

    ips = _collect_blocked_ips(blocked, server_dict)
    rules = _build_pf_rules(blocked, server_dict)
    PF_RULES_FILE.write_text(rules)
    _sync_blocked_ips_file(blocked, server_dict)

    ok, err = _sync_pf_kernel(ips)
    if not ok:
        return False, err
    return True, _describe_state(blocked, server_dict)


def block_regions(regions: list[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    """Block exactly the given regions. Use when UI selection means regions to block."""
    valid, err = _validate_regions(regions, server_dict)
    if not valid:
        return False, err

    blocked = load_blocked()
    blocked.update(regions)
    ok, err = _apply_blocked_state(blocked, server_dict)
    if ok:
        save_blocked(blocked)
    return ok, err


def unblock_regions(regions: list[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    valid, err = _validate_regions(regions, server_dict)
    if not valid:
        return False, err

    blocked = load_blocked()
    for region in regions:
        blocked.discard(region)
    ok, err = _apply_blocked_state(blocked, server_dict)
    if ok:
        save_blocked(blocked)
    return ok, err


def allow_only_regions(regions: list[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    """Allow the given regions and block every other known region.

    Use when UI selection means the servers the user wants to play on.
    """
    valid, err = _validate_regions(regions, server_dict)
    if not valid:
        return False, err
    if not regions:
        return False, "No regions selected."

    allowed = set(regions)
    blocked = set(server_dict.keys()) - allowed
    ok, err = _apply_blocked_state(blocked, server_dict)
    if ok:
        save_blocked(blocked)
    return ok, err


def block_all(server_dict: Dict[str, str]) -> tuple[bool, str]:
    blocked = set(server_dict.keys())
    ok, err = _apply_blocked_state(blocked, server_dict)
    if ok:
        save_blocked(blocked)
    return ok, err


def unblock_all(server_dict: Dict[str, str]) -> tuple[bool, str]:
    ok, err = _apply_blocked_state(set(), server_dict)
    if ok:
        save_blocked(set())
    return ok, err
