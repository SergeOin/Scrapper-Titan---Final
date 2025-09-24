"""Simple import smoke test for recently modified modules.

Ensures project root is on sys.path so that 'scraper' and 'server' packages resolve
even if executed with an unexpected working directory context.
"""
import importlib, sys, pathlib, os

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
print(f"PROJECT_ROOT={PROJECT_ROOT}")
print(f"CWD={os.getcwd()}")
mods = ["scraper.bootstrap", "scraper.worker", "server.routes"]
for m in mods:
    try:
        importlib.import_module(m)
        print(f"OK {m}")
    except Exception as e:
        print(f"FAIL {m}: {e}")
        raise SystemExit(1)
print("ALL_IMPORTS_OK")
