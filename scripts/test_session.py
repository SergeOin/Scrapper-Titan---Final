#!/usr/bin/env python3
"""Test if the current LinkedIn session is valid."""
import json
import sys
from playwright.sync_api import sync_playwright

STORAGE_PATH = r"C:\Users\plogr\AppData\Local\TitanScraper\storage_state.json"

def main():
    # Load storage state
    try:
        with open(STORAGE_PATH) as f:
            storage = json.load(f)
    except FileNotFoundError:
        print("ERROR: storage_state.json not found")
        return 1
    
    cookies = storage.get("cookies", [])
    print(f"Cookies loaded: {len(cookies)}")
    
    li_at = [c for c in cookies if c["name"] == "li_at"]
    print(f"li_at present: {bool(li_at)}")
    
    if not li_at:
        print("ERROR: No li_at cookie - session invalid")
        return 1
    
    # Test with Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STORAGE_PATH)
        page = context.new_page()
        
        print("Navigating to LinkedIn feed...")
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        
        url = page.url
        title = page.title()
        print(f"URL: {url}")
        print(f"Title: {title}")
        
        is_login = "/login" in url or "/uas/login" in url or "/checkpoint" in url
        print(f"Is login/checkpoint page: {is_login}")
        
        if is_login:
            print("SESSION INVALID - redirected to login")
            browser.close()
            return 1
        
        # Check if feed content is present
        try:
            page.wait_for_selector('div[role="main"]', timeout=5000)
            print("Feed main container found - SESSION VALID")
        except:
            print("Feed main container not found")
        
        browser.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
