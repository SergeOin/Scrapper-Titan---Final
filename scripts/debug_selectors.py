"""Debug script to analyze LinkedIn's current DOM structure."""
import asyncio
import re
from playwright.async_api import async_playwright


async def analyze_linkedin():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(storage_state='storage_state.json')
        page = await context.new_page()
        
        print("Navigating to LinkedIn search...")
        await page.goto('https://www.linkedin.com/search/results/content/?keywords=juriste', timeout=60000)
        await page.wait_for_timeout(5000)
        
        # Scroll to load content
        for i in range(3):
            await page.evaluate('window.scrollBy(0, 800)')
            await page.wait_for_timeout(1500)
        
        # Test the new selector
        posts = await page.query_selector_all('div[role="listitem"]')
        print(f"\nFound {len(posts)} posts with div[role='listitem']")
        
        for i, post in enumerate(posts[:3]):
            text = await post.inner_text()
            print(f"\n--- Post {i+1} (first 500 chars) ---")
            print(text[:500])
        
        # Get HTML and find activity IDs
        html = await page.content()
        activity_ids = list(set(re.findall(r'urn:li:activity:(\d+)', html)))
        print(f"\n\nFound {len(activity_ids)} activity IDs:")
        for aid in activity_ids:
            print(f"  - {aid}")
        
        # Try various selectors
        selectors_to_test = [
            # New patterns based on the HTML structure
            'li',
            'div[role="listitem"]',
            'article',
            'section',
            'main li',
            'main > div > div',
            '[data-chameleon-result-urn]',
            '[data-search-result]',
        ]
        
        print("\nTesting selectors:")
        for sel in selectors_to_test:
            try:
                elements = await page.query_selector_all(sel)
                print(f"  {sel}: {len(elements)} elements")
            except Exception as e:
                print(f"  {sel}: ERROR - {e}")
        
        # Find elements containing activity URNs via JavaScript
        result = await page.evaluate('''() => {
            const results = [];
            
            // Find all li elements
            const listItems = document.querySelectorAll('li');
            for (const li of listItems) {
                const html = li.innerHTML;
                if (html.includes('urn:li:activity:')) {
                    const activityMatch = html.match(/urn:li:activity:(\\d+)/);
                    if (activityMatch) {
                        results.push({
                            type: 'li',
                            activityId: activityMatch[1],
                            className: li.className || 'no-class',
                            textPreview: li.innerText.substring(0, 200).replace(/\\n/g, ' ')
                        });
                    }
                }
            }
            
            // Also check divs
            const divs = document.querySelectorAll('div');
            for (const div of divs) {
                // Only direct children of main or specific containers
                if (div.children.length > 3 && div.children.length < 20) {
                    const html = div.innerHTML;
                    if (html.includes('urn:li:activity:') && !html.includes('urn:li:activity:', 1000)) {
                        // This div contains an activity but not too many (likely a post container)
                        const activityMatch = html.match(/urn:li:activity:(\\d+)/);
                        if (activityMatch && !results.find(r => r.activityId === activityMatch[1])) {
                            results.push({
                                type: 'div',
                                activityId: activityMatch[1],
                                className: div.className || 'no-class',
                                childCount: div.children.length
                            });
                        }
                    }
                }
            }
            
            return results;
        }''')
        
        print(f"\nElements containing activity URNs: {len(result)}")
        for r in result[:10]:
            print(f"  - {r['type']}: activity={r['activityId']}, class={r.get('className', 'N/A')[:60]}")
            if 'textPreview' in r:
                print(f"    Text: {r['textPreview'][:100]}...")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(analyze_linkedin())
