"""Fix cookie domains in storage_state.json.

LinkedIn cookies should use .linkedin.com domain (not .www.linkedin.com)
to work correctly across all LinkedIn subdomains.

Usage:
  python scripts/fix_cookie_domains.py [--storage-state path/to/storage_state.json]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path


def get_default_storage_path() -> Path:
    """Get default storage_state.json path."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        return Path(localappdata) / "TitanScraper" / "storage_state.json"
    return Path("storage_state.json")


def fix_cookie_domains(storage_path: Path) -> bool:
    """Fix cookie domains from .www.linkedin.com to .linkedin.com.
    
    Returns True if changes were made.
    """
    if not storage_path.exists():
        print(f"ERROR: storage_state.json not found at {storage_path}")
        return False
    
    # Read current state
    with open(storage_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    cookies = data.get("cookies", [])
    changes_made = 0
    
    # Critical cookies that should be on .linkedin.com (not .www.linkedin.com)
    # These are session cookies that need to work across all subdomains
    critical_cookies = {"li_at", "li_rm", "JSESSIONID", "bscookie", "liap"}
    
    print("=" * 60)
    print("COOKIE DOMAIN ANALYSIS")
    print("=" * 60)
    
    for cookie in cookies:
        name = cookie.get("name", "")
        domain = cookie.get("domain", "")
        
        # Check if domain starts with .www.
        if domain.startswith(".www."):
            new_domain = domain.replace(".www.", ".", 1)  # .www.linkedin.com -> .linkedin.com
            
            print(f"\n[FIX] {name}")
            print(f"  Old domain: {domain}")
            print(f"  New domain: {new_domain}")
            
            cookie["domain"] = new_domain
            changes_made += 1
        else:
            print(f"\n[OK] {name} -> {domain}")
    
    if changes_made == 0:
        print("\nNo changes needed - all cookie domains are correct.")
        return False
    
    # Backup original file
    backup_path = storage_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    shutil.copy2(storage_path, backup_path)
    print(f"\n[BACKUP] Created: {backup_path}")
    
    # Write fixed file
    with open(storage_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    
    print(f"\n[SAVED] Fixed {changes_made} cookie domains in {storage_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Fix cookie domains in storage_state.json")
    parser.add_argument("--storage-state", type=Path, default=None, 
                        help="Path to storage_state.json")
    args = parser.parse_args()
    
    storage_path = args.storage_state or get_default_storage_path()
    print(f"Storage state path: {storage_path}")
    
    success = fix_cookie_domains(storage_path)
    
    if success:
        print("\n" + "=" * 60)
        print("Cookie domains fixed! Restart the application to use the corrected cookies.")
        print("=" * 60)
    

if __name__ == "__main__":
    main()
