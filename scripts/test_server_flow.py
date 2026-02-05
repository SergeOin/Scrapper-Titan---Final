"""Test du flux serveur: feed puis recherche."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright


async def test_server_flow():
    """Test le flux exact du serveur: feed d'abord, puis recherche."""
    print("=" * 60)
    print("TEST DU FLUX SERVEUR (feed → recherche)")
    print("=" * 60)
    
    storage_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'TitanScraper', 'storage_state.json')
    if not os.path.exists(storage_path):
        storage_path = 'storage_state.json'
    
    print(f"\nStorage state: {storage_path}")
    
    async with async_playwright() as pw:
        print("\n1. Lancement du navigateur (headless=True comme le serveur)...")
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=storage_path)
        page = await context.new_page()
        
        # Étape 1: Comme le serveur - aller au feed d'abord
        print("\n2. Navigation vers le feed (comme le serveur)...")
        try:
            await page.goto("https://www.linkedin.com/feed/", timeout=60000)
            await page.wait_for_timeout(3000)
            print("   ✅ Feed chargé")
        except Exception as e:
            print(f"   ❌ Erreur feed: {e}")
            await browser.close()
            return
        
        # Vérifier les cookies
        cookies = await context.cookies()
        li_at = [c for c in cookies if c['name'] == 'li_at']
        print(f"   Cookies: {len(cookies)}, li_at présent: {bool(li_at)}")
        
        # Sauvegarder le storage_state (comme le serveur)
        print("\n3. Sauvegarde du storage_state (comme le serveur)...")
        await context.storage_state(path="storage_state.json")
        print("   ✅ Storage state sauvegardé")
        
        # Étape 2: Aller à la recherche
        print("\n4. Navigation vers la recherche avec geo_hint...")
        search_url = 'https://www.linkedin.com/search/results/content/?keywords=recrute juriste France'
        try:
            await page.goto(search_url, timeout=60000)
            await page.wait_for_timeout(5000)
            print("   ✅ Recherche chargée")
        except Exception as e:
            print(f"   ❌ Erreur recherche: {e}")
            
            # Prendre un screenshot pour diagnostic
            await page.screenshot(path="screenshots/error_search.png")
            print("   Screenshot sauvé dans screenshots/error_search.png")
            
            # Vérifier l'URL actuelle
            print(f"   URL actuelle: {page.url}")
            
            await browser.close()
            return
        
        # Extraction des posts
        print("\n5. Extraction des posts...")
        posts = await page.query_selector_all('div[role="listitem"]')
        print(f"   ✅ {len(posts)} posts trouvés!")
        
        await browser.close()
        print("\n" + "=" * 60)
        print("TEST TERMINÉ AVEC SUCCÈS")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_server_flow())
