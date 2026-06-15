"""Cached macOS administrator authorization for the app session."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import shlex
import tempfile
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_int,
    c_uint32,
    c_void_p,
)
from pathlib import Path

Security = ctypes.CDLL(ctypes.util.find_library("Security"))

kAuthorizationFlagDefaults = 0
kAuthorizationFlagExtendRights = 1 << 1
kAuthorizationFlagInteractionAllowed = 1 << 0
errAuthorizationSuccess = 0


class AuthorizationItem(Structure):
    _fields_ = [
        ("name", c_char_p),
        ("valueLength", c_uint32),
        ("value", c_void_p),
        ("flags", c_uint32),
    ]


class AuthorizationRights(Structure):
    _fields_ = [
        ("count", c_int),
        ("items", POINTER(AuthorizationItem)),
    ]


AuthorizationCreate = Security.AuthorizationCreate
AuthorizationCreate.argtypes = [c_void_p, c_void_p, c_uint32, POINTER(c_void_p)]
AuthorizationCreate.restype = c_int

AuthorizationFree = Security.AuthorizationFree
AuthorizationFree.argtypes = [c_void_p, c_uint32]
AuthorizationFree.restype = c_int

AuthorizationCopyRights = Security.AuthorizationCopyRights
AuthorizationCopyRights.argtypes = [
    c_void_p,
    POINTER(AuthorizationRights),
    c_void_p,
    c_uint32,
    POINTER(c_void_p),
]
AuthorizationCopyRights.restype = c_int

AuthorizationExecuteWithPrivileges = Security.AuthorizationExecuteWithPrivileges
AuthorizationExecuteWithPrivileges.argtypes = [
    c_void_p,
    c_char_p,
    c_uint32,
    POINTER(c_char_p),
    POINTER(c_void_p),
]
AuthorizationExecuteWithPrivileges.restype = c_int


class AdminSession:
    """Prompts once per app session, then reuses admin rights for pfctl."""

    def __init__(self) -> None:
        self._ref = c_void_p()
        self._authorized = False

    def ensure(self) -> tuple[bool, str]:
        if self._authorized and self._ref.value:
            return True, ""

        if not self._ref.value:
            status = AuthorizationCreate(
                None,
                None,
                kAuthorizationFlagDefaults,
                byref(self._ref),
            )
            if status != errAuthorizationSuccess:
                return False, f"AuthorizationCreate failed ({status})."

        item = AuthorizationItem(
            name=b"system.privilege.admin",
            valueLength=0,
            value=None,
            flags=0,
        )
        rights = AuthorizationRights(count=1, items=ctypes.pointer(item))
        obtained = c_void_p()

        status = AuthorizationCopyRights(
            self._ref,
            byref(rights),
            None,
            kAuthorizationFlagDefaults
            | kAuthorizationFlagExtendRights
            | kAuthorizationFlagInteractionAllowed,
            byref(obtained),
        )
        if status != errAuthorizationSuccess:
            return False, "Administrator authorization was denied or canceled."

        self._authorized = True
        return True, ""

    def run_shell(self, cmd: str) -> tuple[bool, str]:
        ok, err = self.ensure()
        if not ok:
            return False, err

        out_path = Path(tempfile.gettempdir()) / f"cs2picker-admin-{os.getpid()}.out"
        wrapped = f"({cmd}) > {shlex.quote(str(out_path))} 2>&1"

        args = [b"/bin/sh", b"-c", wrapped.encode("utf-8")]
        argv = (c_char_p * (len(args) + 1))()
        for index, value in enumerate(args):
            argv[index] = value

        pipe = c_void_p()
        status = AuthorizationExecuteWithPrivileges(
            self._ref,
            b"/bin/sh",
            kAuthorizationFlagDefaults,
            argv,
            byref(pipe),
        )
        if status != errAuthorizationSuccess:
            return False, f"Failed to run privileged command ({status})."

        output = ""
        if out_path.exists():
            output = out_path.read_text(encoding="utf-8", errors="replace").strip()
            out_path.unlink(missing_ok=True)

        return True, output

    def close(self) -> None:
        if self._ref.value:
            AuthorizationFree(self._ref, kAuthorizationFlagDefaults)
            self._ref = c_void_p()
        self._authorized = False


_session: AdminSession | None = None


def get_admin_session() -> AdminSession:
    global _session
    if _session is None:
        _session = AdminSession()
    return _session
