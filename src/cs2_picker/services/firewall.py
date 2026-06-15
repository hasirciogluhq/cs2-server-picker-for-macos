import json
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Set

from cs2_picker.core.config import (
    BLOCKED_FILE,
    BLOCKED_IPS_FILE,
    PF_MARKER_BEGIN,
    PF_MARKER_END,
    PF_RULES_FILE,
    SUPPORT_DIR,
)
from cs2_picker.services.admin import get_admin_session


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


def _run_privileged(shell_cmd: str, *, prefer_osascript: bool = False) -> tuple[bool, str]:
    """Run shell as root. osascript is the most reliable path for pfctl."""
    if prefer_osascript:
        return _run_sudo(shell_cmd)

    ok, output = get_admin_session().run_shell(shell_cmd)
    if ok:
        return True, output
    lowered = output.lower()
    if "denied" in lowered or "cancel" in lowered:
        return False, output
    return _run_sudo(shell_cmd)


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
    """Human-readable rules file (debug). Active rules use the pf table in main ruleset."""
    lines = ["# CS2 Server Picker — auto-generated", ""]
    ips = _collect_blocked_ips(blocked, server_dict)
    if not ips:
        return "\n".join(lines)

    ip_list = ", ".join(ips)
    lines.extend(
        [
            "table <cs2picker_blocked> persist file "
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
        f'table <cs2picker_blocked> persist file "{table_path}"',
        "block out quick proto {tcp, udp} from any to <cs2picker_blocked>",
        "block in quick proto {tcp, udp} from <cs2picker_blocked> to any",
        PF_MARKER_END,
    ]


def _strip_main_ruleset(current: str, section: list[str]) -> str:
    lines: list[str] = []
    skipping = False
    for line in current.splitlines():
        stripped = line.strip()
        if stripped == PF_MARKER_BEGIN:
            skipping = True
            continue
        if stripped == PF_MARKER_END:
            skipping = False
            continue
        if not skipping:
            lines.append(line)

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


def _write_temp_rules(content: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="cs2picker-rules-",
        suffix=".pf",
        delete=False,
    )
    with handle:
        handle.write(content)
        return Path(handle.name)


def _apply_main_ruleset(content: str) -> tuple[bool, str]:
    rules_path = _write_temp_rules(content)
    quoted = shlex.quote(str(rules_path))
    try:
        ok, syntax_out = _run_pf_cmd(f"/sbin/pfctl -vnf {quoted} 2>&1")
        if not ok:
            return False, syntax_out or "pf rule syntax check failed."

        lowered = syntax_out.lower()
        if "syntax error" in lowered or "rules must be in order" in lowered:
            return False, syntax_out

        ok, apply_out = _run_pf_cmd(
            f"/sbin/pfctl -e 2>/dev/null; /sbin/pfctl -f {quoted} 2>&1"
        )
        if not ok:
            return False, apply_out or "Failed to load pf rules."
        return True, apply_out
    finally:
        rules_path.unlink(missing_ok=True)


def _run_pf_cmd(shell_cmd: str) -> tuple[bool, str]:
    ok, output = _run_privileged(shell_cmd)
    if ok:
        return True, output
    return _run_privileged(shell_cmd, prefer_osascript=True)


def _read_main_ruleset() -> tuple[bool, str]:
    ok, output = _run_pf_cmd("/sbin/pfctl -sr 2>&1")
    if ok and output.strip():
        return True, output

    ok, output = _run_pf_cmd("/sbin/pfctl -e 2>/dev/null; /sbin/pfctl -sr 2>&1")
    if ok and output.strip():
        return True, output

    return _run_pf_cmd("cat /etc/pf.conf 2>&1")


def _verify_main_rules(expect_blocks: bool) -> tuple[bool, str]:
    ok, output = _read_main_ruleset()
    if not ok:
        return False, output or "Could not read pf rules."

    has_marker = PF_MARKER_BEGIN in output
    has_block = "cs2picker_blocked" in output and "block" in output
    if expect_blocks and (not has_marker or not has_block):
        detail = output.strip() or "(empty pf ruleset)"
        return False, (
            "pf block rules are not active.\n\n"
            f"pfctl -sr output:\n{detail[:1200]}"
        )
    if not expect_blocks and has_block:
        return False, "pf block rules were not removed."
    return True, output


def _apply_pf_rules(rules_content: str, blocked: Set[str], server_dict: Dict[str, str]) -> tuple[bool, str]:
    _ensure_dirs()
    PF_RULES_FILE.write_text(rules_content)

    _sync_blocked_ips_file(blocked, server_dict)
    section = _build_ruleset_section(blocked, server_dict)
    expect_blocks = bool(section)

    ok, current = _read_main_ruleset()
    if not ok:
        return False, current

    merged = _strip_main_ruleset(current, section)
    ok, err = _apply_main_ruleset(merged)
    if not ok and "syntax" in err.lower():
        ok_base, base = _run_pf_cmd("cat /etc/pf.conf 2>&1")
        if ok_base and base.strip():
            merged = _strip_main_ruleset(base, section)
            ok, err = _apply_main_ruleset(merged)
    if not ok:
        return False, err

    verified, verify_err = _verify_main_rules(expect_blocks)
    if not verified:
        return False, verify_err

    return True, err


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
