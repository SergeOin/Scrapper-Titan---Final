#!/usr/bin/env python3
"""Script de monitoring pour la prochaine session v2.

Lance ce script pour surveiller quand la prochaine session démarrera
et recevoir des notifications.

Usage:
    python scripts/monitor_next_session.py
    
    # En arrière-plan avec notification toutes les 30 min
    python scripts/monitor_next_session.py --interval 30
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force v2 mode
os.environ["TITAN_ENABLE_V2"] = "1"


def get_session_status() -> dict:
    """Get current session orchestrator status."""
    from scraper.session_orchestrator import get_session_orchestrator
    
    orchestrator = get_session_orchestrator()
    
    can_scrape, reason = orchestrator.should_scrape_now()
    stats = orchestrator.get_daily_stats()
    wait_seconds = orchestrator.get_wait_seconds()
    next_session = orchestrator.get_next_session_time()
    
    return {
        "can_scrape": can_scrape,
        "reason": reason,
        "wait_seconds": wait_seconds,
        "wait_minutes": wait_seconds // 60,
        "next_session": next_session.strftime("%H:%M") if next_session else "N/A",
        "quota_target": stats["quota_target"],
        "posts_qualified": stats["posts_qualified"],
        "sessions_completed": stats["sessions_completed"],
    }


def print_status(status: dict):
    """Print formatted status."""
    now = datetime.now().strftime("%H:%M:%S")
    
    if status["can_scrape"]:
        print(f"[{now}] 🟢 SESSION ACTIVE - Prêt à scraper!")
        print(f"         Raison: {status['reason']}")
    else:
        print(f"[{now}] 🔴 En attente - {status['reason']}")
        print(f"         Prochaine session: {status['next_session']} "
              f"(dans {status['wait_minutes']} min)")
    
    print(f"         Quota: {status['posts_qualified']}/{status['quota_target']} posts")
    print(f"         Sessions aujourd'hui: {status['sessions_completed']}")


def main():
    parser = argparse.ArgumentParser(
        description="Monitoring de la prochaine session v2"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Intervalle de vérification en minutes (0 = une seule fois)"
    )
    parser.add_argument(
        "--alert-when-ready",
        action="store_true",
        help="Émettre un bip sonore quand la session est prête"
    )
    
    args = parser.parse_args()
    
    print("=" * 50)
    print(" TITAN SCRAPER V2 - MONITORING SESSION")
    print("=" * 50)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"Mode: {'Continu' if args.interval > 0 else 'Unique'}")
    print()
    
    try:
        while True:
            status = get_session_status()
            print_status(status)
            
            if status["can_scrape"] and args.alert_when_ready:
                # Bip sonore (Windows)
                print("\a")  # Bell character
                print("\n🔔 ALERTE: Session prête à démarrer!")
            
            if args.interval <= 0:
                break
            
            print(f"\n--- Prochaine vérification dans {args.interval} min ---\n")
            time.sleep(args.interval * 60)
            
    except KeyboardInterrupt:
        print("\n\nMonitoring arrêté.")


if __name__ == "__main__":
    main()
