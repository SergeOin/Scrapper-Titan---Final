"""Importe les cookies LinkedIn depuis Edge/Chrome/Firefox via browser-cookie3
et génère storage_state.json utilisable par Playwright.

Usage:
  python scripts/import_cookies.py

Prerequis:
  - Être connecté à LinkedIn dans au moins un navigateur local.
  - Le paquet browser-cookie3 est déjà installé (requirements.txt).

Après succès:
  - Vérifier storage_state.json créé (taille > 0)
  - Relancer le worker / run_all
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

try:
    import browser_cookie3 as bc3  # type: ignore
except Exception as e:  # pragma: no cover
    print("[import] browser-cookie3 introuvable:", e)
    sys.exit(1)

TARGET = Path("storage_state.json")

BROWSERS = [
    ("edge", getattr(bc3, "edge", None)),
    ("chrome", getattr(bc3, "chrome", None)),
    ("firefox", getattr(bc3, "firefox", None)),
]


def main() -> int:
    for name, getter in BROWSERS:
        if not getter:
            continue
        print(f"[import] Tentative {name} ...")
        try:
            jar = getter(domain_name=".linkedin.com")
            cookies = []
            for c in jar:
                cookies.append({
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    "expires": c.expires or 0,
                    "httpOnly": c.has_nonstandard_attr("HttpOnly"),
                    "secure": c.secure,
                    "sameSite": "Lax",
                })
            has_li = any(c["name"] == "li_at" for c in cookies)
            if cookies and has_li:
                TARGET.write_text(json.dumps({"cookies": cookies}, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[import] Succès via {name}: {len(cookies)} cookies (li_at présent) -> {TARGET}")
                return 0
            print(f"[import] {name}: cookies={len(cookies)} li_at={has_li} -> échec partiel")
        except Exception as exc:
            print(f"[import] {name}: erreur {exc}")
    print("[import] Aucune session LinkedIn valide détectée. Ouvrez LinkedIn, connectez-vous puis réessayez.")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
