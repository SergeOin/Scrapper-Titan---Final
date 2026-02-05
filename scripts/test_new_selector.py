"""Test simple de scraping avec le nouveau sélecteur."""
import asyncio
import re
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright


async def test_scraping():
    """Test le scraping avec le nouveau sélecteur div[role='listitem']."""
    print("=" * 60)
    print("TEST DE SCRAPING LINKEDIN AVEC LE NOUVEAU SÉLECTEUR")
    print("=" * 60)
    
    storage_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'TitanScraper', 'storage_state.json')
    if not os.path.exists(storage_path):
        storage_path = 'storage_state.json'
    
    async with async_playwright() as pw:
        print("\n1. Lancement du navigateur...")
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=storage_path)
        page = await context.new_page()
        
        print("2. Navigation vers LinkedIn search...")
        await page.goto(
            'https://www.linkedin.com/search/results/content/?keywords=juriste',
            timeout=60000
        )
        await page.wait_for_timeout(5000)
        
        print("3. Scroll pour charger le contenu...")
        for i in range(3):
            await page.evaluate('window.scrollBy(0, 800)')
            await page.wait_for_timeout(1500)
        
        print("4. Extraction des posts avec div[role='listitem']...")
        posts = await page.query_selector_all('div[role="listitem"]')
        print(f"   ✅ {len(posts)} posts trouvés!")
        
        extracted_data = []
        for i, post in enumerate(posts):
            text = await post.inner_text()
            html = await post.inner_html()
            
            # Extract activity ID from HTML
            activity_match = re.search(r'urn:li:activity:(\d+)', html)
            activity_id = activity_match.group(1) if activity_match else None
            
            # Parse author (first non-empty line usually)
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            author = "Unknown"
            for line in lines:
                if line and line != "Post du fil d'actualité" and len(line) > 3:
                    author = line
                    break
            
            # Get text preview
            text_preview = ' '.join(lines[2:6]) if len(lines) > 2 else text[:200]
            
            extracted_data.append({
                'activity_id': activity_id,
                'author': author[:50],
                'text_preview': text_preview[:150]
            })
            
            print(f"\n   Post {i+1}:")
            print(f"     Activity ID: {activity_id}")
            print(f"     Author: {author[:50]}")
            print(f"     Text: {text_preview[:100]}...")
        
        await browser.close()
        
        print("\n" + "=" * 60)
        print(f"RÉSULTAT: {len(extracted_data)} posts extraits avec succès!")
        print("=" * 60)
        
        return extracted_data


if __name__ == "__main__":
    result = asyncio.run(test_scraping())
    print(f"\nRetourné: {len(result)} posts")
