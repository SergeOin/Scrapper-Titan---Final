"""Helper script to create or update DPAPI-protected credentials.json for TitanScraper auto-login.

Usage (PowerShell):
  python scripts/store_credentials.py

Creates %LOCALAPPDATA%/TitanScraper/credentials.json with structure:
{
  "email": "...",
  "password_protected": "<base64>",
  "auto_login": true,
  "version": 1
}

Only implemented for Windows (uses CryptProtectData via win32 APIs). On other platforms it exits.
"""
from __future__ import annotations
import base64
import getpass
import json
import os
import sys
import ctypes
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = os.name == "nt"

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

if IS_WINDOWS:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    CryptProtectData = crypt32.CryptProtectData
    CryptProtectData.argtypes = [ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB), wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
    CryptProtectData.restype = wintypes.BOOL


def _dpapi_protect(plaintext: bytes) -> bytes:
    if not IS_WINDOWS:
        raise RuntimeError("DPAPI protection only available on Windows")
    in_blob = _DATA_BLOB(len(plaintext), (ctypes.c_byte * len(plaintext)).from_buffer_copy(plaintext))
    out_blob = _DATA_BLOB()
    if not CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):  # type: ignore[name-defined]
        raise OSError("CryptProtectData failed")
    try:
        result = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:  # type: ignore[attr-defined]
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)  # type: ignore[attr-defined]
    return result


def build_credentials(email: str, password: str) -> dict:
    protected = _dpapi_protect(password.encode("utf-8"))
    return {
        "email": email,
        "password_protected": base64.b64encode(protected).decode("ascii"),
        "auto_login": True,
        "version": 1,
    }


def main() -> int:
    if not IS_WINDOWS:
        print("This helper currently supports Windows only (DPAPI).", file=sys.stderr)
        return 1

    email = input("Email LinkedIn: ").strip()
    if not email:
        print("Email manquant", file=sys.stderr)
        return 2
    password = getpass.getpass("Mot de passe LinkedIn: ")
    if not password:
        print("Mot de passe manquant", file=sys.stderr)
        return 3

    creds = build_credentials(email, password)
    target_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "TitanScraper"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "credentials.json"
    with target_file.open("w", encoding="utf-8") as f:
        json.dump(creds, f, ensure_ascii=False, indent=2)
    print(f"Credentials stored at: {target_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
