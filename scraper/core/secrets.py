"""Encryption helpers for storage_state using Fernet if STORAGE_STATE_KEY is provided.

If STORAGE_STATE_ENCRYPT=1 and a plaintext storage_state.json exists, it will be encrypted once
into storage_state.enc and the original removed. Decryption occurs on-demand when reading.
"""
from __future__ import annotations
import os, base64, json
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet  # type: ignore
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore


def _get_key() -> Optional[bytes]:
    key = os.environ.get("STORAGE_STATE_KEY")
    if not key:
        return None
    # Accept raw 32-byte base64 or plain passphrase (derive)
    try:
        if len(key) == 44 and key.endswith('='):
            return key.encode('utf-8')
    except Exception:
        pass
    # Derive deterministic Fernet key from passphrase
    import hashlib
    h = hashlib.sha256(key.encode('utf-8', errors='ignore')).digest()
    return base64.urlsafe_b64encode(h)


def ensure_encrypted_storage_state(settings, logger) -> None:
    if not os.environ.get("STORAGE_STATE_ENCRYPT", "0").lower() in ("1","true","yes","on"):
        return
    if Fernet is None:
        logger.warning("fernet_unavailable", action="skip_encryption")
        return
    key = _get_key()
    if not key:
        logger.warning("storage_state_key_missing")
        return
    f = Fernet(key)
    plain_path = Path(settings.storage_state)
    enc_path = Path(str(plain_path) + ".enc")
    if enc_path.exists():
        return  # already encrypted
    if not plain_path.exists():
        return
    try:
        data = plain_path.read_bytes()
        # Basic validation: must be JSON
        try:
            json.loads(data.decode('utf-8', errors='ignore'))
        except Exception:
            logger.warning("storage_state_not_json", path=str(plain_path))
        token = f.encrypt(data)
        enc_path.write_bytes(token)
        plain_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        logger.info("storage_state_encrypted", path=str(enc_path))
    except Exception as exc:  # pragma: no cover
        logger.error("storage_state_encrypt_failed", error=str(exc))


def load_storage_state_bytes(settings, logger) -> bytes | None:
    """Return decrypted storage_state content if encrypted, else raw bytes."""
    plain = Path(settings.storage_state)
    enc = Path(str(plain) + ".enc")
    if enc.exists():
        if Fernet is None:
            logger.error("fernet_unavailable_decrypt")
            return None
        key = _get_key()
        if not key:
            logger.error("storage_state_key_missing_decrypt")
            return None
        f = Fernet(key)
        try:
            return f.decrypt(enc.read_bytes())
        except Exception as exc:  # pragma: no cover
            logger.error("storage_state_decrypt_failed", error=str(exc))
            return None
    if plain.exists():
        try:
            return plain.read_bytes()
        except Exception:
            return None
    return None
