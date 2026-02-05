#!/usr/bin/env python3
"""Login interactif à LinkedIn et sauvegarde de la session."""
import os
import sys
import time
from playwright.sync_api import sync_playwright

STORAGE_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", "."),
    "TitanScraper",
    "storage_state.json"
)

def main():
    print("=" * 60)
    print("CONNEXION LINKEDIN INTERACTIVE")
    print("=" * 60)
    print(f"\nLe navigateur va s'ouvrir. Connectez-vous à LinkedIn.")
    print("Le script attendra automatiquement que vous soyez connecté.\n")
    
    with sync_playwright() as p:
        # Lancer en mode visible
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="fr-FR",
            timezone_id="Europe/Paris",
        )
        page = context.new_page()
        
        # Aller sur LinkedIn
        page.goto("https://www.linkedin.com/login")
        
        print("⏳ En attente de votre connexion...")
        print("   1. Entrez vos identifiants LinkedIn")
        print("   2. Complétez les captchas si nécessaire")
        print("   3. La session sera capturée automatiquement une fois sur le feed")
        
        # Attendre que l'utilisateur soit connecté (max 5 minutes)
        max_wait = 300  # 5 minutes
        start = time.time()
        connected = False
        
        while time.time() - start < max_wait:
            current_url = page.url
            # Vérifie qu'on n'est plus sur login/checkpoint
            if "/feed" in current_url or (
                "linkedin.com" in current_url 
                and "/login" not in current_url 
                and "/checkpoint" not in current_url
                and "/uas/" not in current_url
            ):
                # Double-check: on attend que le feed soit visible
                try:
                    page.wait_for_selector('div[role="main"]', timeout=5000)
                    connected = True
                    break
                except:
                    pass
            
            elapsed = int(time.time() - start)
            print(f"\r⏳ Attente de connexion... {elapsed}s / {max_wait}s", end="", flush=True)
            time.sleep(2)
        
        print()  # Nouvelle ligne
        
        if not connected:
            print("❌ Timeout: connexion non détectée après 5 minutes")
            browser.close()
            return 1
        
        # Sauvegarder la session
        print("\n💾 Sauvegarde de la session...")
        context.storage_state(path=STORAGE_PATH)
        
        # Vérifier les cookies
        cookies = context.cookies()
        li_at = [c for c in cookies if c["name"] == "li_at"]
        
        print(f"✅ Session sauvegardée: {STORAGE_PATH}")
        print(f"   Cookies: {len(cookies)}")
        print(f"   li_at présent: {bool(li_at)}")
        
        if li_at:
            print("\n✅ Session LinkedIn capturée avec succès!")
        else:
            print("\n⚠️  ATTENTION: Cookie li_at non trouvé!")
            print("   La session pourrait ne pas fonctionner.")
        
        browser.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
