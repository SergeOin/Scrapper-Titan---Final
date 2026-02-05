#!/usr/bin/env python3
"""Script de reconnexion manuelle à LinkedIn avec les credentials sauvegardés."""
import base64
import json
import os
import sys
from pathlib import Path

try:
    import win32crypt
except ImportError:
    print("ERREUR: pywin32 n'est pas installé. Installez-le avec: pip install pywin32")
    sys.exit(1)

from playwright.sync_api import sync_playwright

# Add parent directory to path for importing scraper modules
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from scraper.stealth import get_consistent_fingerprint, ANTI_DETECTION_SCRIPT
except ImportError:
    # Fallback if import fails
    get_consistent_fingerprint = None
    ANTI_DETECTION_SCRIPT = None

LOCALAPPDATA = os.environ.get("LOCALAPPDATA", ".")
CREDS_PATH = Path(LOCALAPPDATA) / "TitanScraper" / "credentials.json"
STORAGE_PATH = Path(LOCALAPPDATA) / "TitanScraper" / "storage_state.json"


def decrypt_password(pw_protected: str) -> str:
    """Décrypte le mot de passe avec DPAPI."""
    raw = base64.b64decode(pw_protected)
    decrypted = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
    return decrypted[1].decode("utf-8", errors="ignore")


def main():
    print("=" * 60)
    print("RECONNEXION LINKEDIN AUTOMATIQUE")
    print("=" * 60)
    
    # 1. Charger les credentials
    if not CREDS_PATH.exists():
        print(f"ERREUR: Fichier credentials non trouvé: {CREDS_PATH}")
        return 1
    
    creds = json.loads(CREDS_PATH.read_text(encoding="utf-8"))
    email = creds.get("email")
    pw_protected = creds.get("password_protected")
    
    if not email or not pw_protected:
        print("ERREUR: Credentials incomplets")
        return 1
    
    print(f"Email: {email}")
    
    # 2. Décrypter le mot de passe
    try:
        password = decrypt_password(pw_protected)
        print("Mot de passe décrypté avec succès")
    except Exception as e:
        print(f"ERREUR: Impossible de décrypter le mot de passe: {e}")
        return 1
    
    # 3. Lancer Playwright pour le login
    print("\nLancement du navigateur...")
    
    # Get consistent fingerprint to match the scraper's identity
    if get_consistent_fingerprint:
        fp = get_consistent_fingerprint()
        print(f"Using persistent fingerprint (UA: {fp.get('user_agent', 'N/A')[:60]}...)")
    else:
        # Fallback fingerprint matching DEFAULT_PERSISTENT_FINGERPRINT
        fp = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "locale": "fr-FR",
            "timezone_id": "Europe/Paris",
            "viewport": {"width": 1920, "height": 1080},
            "accept_language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        print("Using fallback fingerprint (stealth module not available)")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # Mode visible pour CAPTCHA/MFA
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport=fp.get("viewport", {"width": 1920, "height": 1080}),
            user_agent=fp.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            locale=fp.get("locale", "fr-FR"),
            timezone_id=fp.get("timezone_id", "Europe/Paris"),
            extra_http_headers={
                "Accept-Language": fp.get("accept_language", "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"),
                "Sec-CH-UA": fp.get("sec_ch_ua", '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'),
                "Sec-CH-UA-Mobile": fp.get("sec_ch_ua_mobile", "?0"),
                "Sec-CH-UA-Platform": fp.get("sec_ch_ua_platform", '"Windows"'),
            },
        )
        page = context.new_page()
        
        # Apply anti-detection scripts if available
        if ANTI_DETECTION_SCRIPT:
            page.add_init_script(ANTI_DETECTION_SCRIPT)
        
        # Aller sur LinkedIn login
        print("Navigation vers LinkedIn login...")
        page.goto("https://www.linkedin.com/login", timeout=30000)
        
        # Remplir les champs
        print("Remplissage des identifiants...")
        page.fill("input#username", email)
        page.fill("input#password", password)
        page.click("button[type=submit]")
        
        # Attendre le résultat
        print("\n⏳ Attente de la connexion...")
        print("   Si un CAPTCHA ou 2FA apparaît, complétez-le manuellement.")
        
        max_wait = 120000  # 2 minutes
        total_wait = 0
        step = 2000
        connected = False
        
        while total_wait < max_wait:
            cookies = context.cookies()
            has_li_at = any(c.get("name") == "li_at" for c in cookies)
            
            if has_li_at:
                connected = True
                break
            
            if page.url.startswith("https://www.linkedin.com/feed"):
                connected = True
                break
            
            elapsed = total_wait // 1000
            print(f"\r   Attente... {elapsed}s / {max_wait // 1000}s - URL: {page.url[:50]}...", end="", flush=True)
            page.wait_for_timeout(step)
            total_wait += step
        
        print()  # Nouvelle ligne
        
        if not connected:
            print("❌ Timeout: connexion échouée")
            browser.close()
            return 1
        
        # Sauvegarder la session
        print("\n💾 Sauvegarde de la session...")
        context.storage_state(path=str(STORAGE_PATH))
        
        # Vérifier les cookies finaux
        cookies = context.cookies()
        li_at = [c for c in cookies if c["name"] == "li_at"]
        
        print(f"✅ Session sauvegardée: {STORAGE_PATH}")
        print(f"   Cookies: {len(cookies)}")
        print(f"   li_at présent: {bool(li_at)}")
        
        browser.close()
    
    print("\n✅ Reconnexion réussie!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
