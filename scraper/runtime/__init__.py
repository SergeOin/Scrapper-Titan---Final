"""Runtime refactor package (Sprint 2).

Ce paquet est progressivement alimenté pour extraire la logique métier du
`worker.py` monolithique. Les modules exposent des primitives testables qui
seront consommées par l'orchestrateur et, à terme, par la pipeline storage.
"""

from .models import JobResult, RuntimePost

__all__ = ["RuntimePost", "JobResult"]
