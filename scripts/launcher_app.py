#!/usr/bin/env python3
"""Simple launcher that starts TitanScraper.exe after installation.

This is compiled to a small EXE that WiX Bootstrapper runs after MSI installation.
It waits 2 seconds then launches the main app.
"""

import os
import sys
import time
import subprocess


def main():
    """Launch TitanScraper.exe from the installation directory."""
    # Wait for MSI to fully complete
    time.sleep(2)
    
    # Check Program Files first (perMachine install)
    program_files = os.environ.get('ProgramFiles', r'C:\Program Files')
    app_path_pf = os.path.join(program_files, 'TitanScraper', 'TitanScraper.exe')
    
    # Also check LocalAppData (perUser install)
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    app_path_user = os.path.join(local_appdata, 'TitanScraper', 'TitanScraper.exe') if local_appdata else ''
    
    # Try Program Files first, then user folder
    for app_path in [app_path_pf, app_path_user]:
        if app_path and os.path.isfile(app_path):
            try:
                # Launch detached (don't wait for it)
                subprocess.Popen(
                    [app_path],
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                    close_fds=True
                )
                return 0
            except Exception:
                pass
    
    # If not found, just exit silently (app might be installed elsewhere)
    return 0


if __name__ == '__main__':
    sys.exit(main())
