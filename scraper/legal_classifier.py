"""Legal domain intent & relevance classification utilities.

This module concentrates the logic necessary to:
- Filter posts to the legal domain (French market focus)
- Detect intent: recruitment vs other
- Score relevance based on presence of legal role keywords & context phrases
- Provide structured output (intent, relevance_score, confidence, matched_terms)

Design principles:
- Pure / side-effect free (no external I/O) to simplify unit testing.
- Heuristic & transparent (rule based) with easy extension points.
- Conservative: only label `recherche_profil` when clear recruitment signals present.

Future extension:
- Plug a ML model (e.g. logistic regression over TF-IDF) behind the same interface.
- Maintain a small false-positive suppression list if needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any
import math
import re

# Core legal role keywords (lowercase, accent-insensitive matching recommended upstream)
LEGAL_ROLE_KEYWORDS = [
    "avocat collaborateur","avocat associé","avocat counsel","paralegal","legal counsel","juriste",
    "responsable juridique","directeur juridique","notaire stagiaire","notaire associé","notaire salarié",
    "notaire assistant","clerc de notaire","rédacteur d’actes","rédacteur d'actes","responsable fiscal",
    "directeur fiscal","comptable taxateur","formaliste","juridique","legal","fiscal","droit"  # generic stems
]

# Recruitment signal phrases (complementary to utils.compute_recruitment_signal)
RECRUITMENT_PHRASES = [
    "nous recrutons","on recrute","je recrute","recherche un(e)","recherche son/sa","profil recherché",
    "poste à pourvoir","poste a pourvoir","candidature","rejoindre notre équipe","join our team","we are hiring",
    "hiring for","postulez","envoyez votre cv","offre d'emploi","offre d emploi","opportunité","opportunite"
]

# Negative / informational phrases that should suppress recruitment labeling when no strong positive phrase
NEGATIVE_CONTEXT_PHRASES = [
    "article d'opinion","article de blog","blog:","comparé","comparée","comparé entre","sans offre","pas d'offre","pas d offre","sans recrutement"
]

# Location (France) positive hints / negative hints
FR_POSITIVE = [
    "france","paris","idf","ile-de-france","lyon","marseille","bordeaux","lille","toulouse","nice","nantes","rennes","strasbourg","grenoble","lille"  # duplicate harmless
]
FR_NEGATIVE = [
    "canada","usa","belgium","belgique","switzerland","swiss","australia","uk ","united kingdom","singapore","dubai","germany","deutschland","spain","espagne","portugal"
]

# Simple tokenization
_TOKEN_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ']+")

@dataclass(slots=True)
class LegalClassification:
    intent: str  # "recherche_profil" | "autre"
    relevance_score: float  # 0..1
    confidence: float  # 0..1 heuristic confidence (coverage of signals)
    keywords_matched: List[str]
    location_ok: bool

    def as_dict(self) -> Dict[str, Any]:  # convenience for serialization
        return {
            "intent": self.intent,
            "relevance_score": self.relevance_score,
            "confidence": self.confidence,
            "keywords_matched": self.keywords_matched,
            "location_ok": self.location_ok,
        }

def _lower(text: str) -> str:
    return text.lower()


def classify_legal_post(text: str, *, language: str = "fr", intent_threshold: float = 0.35) -> LegalClassification:
    """Classify a post for legal recruitment intent & relevance.

    Args:
        text: Raw (already whitespace-normalized) post body.
        language: Detected language (only 'fr' currently considered valid).
        intent_threshold: Minimum combined recruitment + legal score to label as recherche_profil.

    Scoring heuristic:
        legal_score: log-scaled count of role keywords (multi-word matches take precedence)
        recruit_score: delegated to overlapping recruitment phrase hits
        combined = clamp( (legal_score*0.6 + recruit_score*0.4), 0, 1 )

    Confidence: fraction of distinct signal categories triggered (legal, recruit, language, location).
    """
    if not text:
        return LegalClassification("autre", 0.0, 0.0, [], False)
    low = _lower(text)

    # Language gate
    lang_ok = (language or "fr").lower() == "fr"

    # Location heuristic (positive > negative & at least one positive when a negative appears)
    location_hits_pos = [p for p in FR_POSITIVE if p in low]
    location_hits_neg = [n for n in FR_NEGATIVE if n in low]
    location_ok = bool(location_hits_pos) or not location_hits_neg  # pass if no negatives or positives present

    # Keyword matches (prefer multi-word sequences first to avoid double counting)
    matched: List[str] = []
    remaining = low
    for kw in sorted(LEGAL_ROLE_KEYWORDS, key=len, reverse=True):
        if kw in remaining:
            matched.append(kw)
            # remove once to reduce repeated counting for overlapping tokens
            remaining = remaining.replace(kw, " ")
    # Fallback token-level for generic stems if none found
    if not matched:
        tokens = set(_TOKEN_RE.findall(low))
        for stem in ("juriste","avocat","notaire","legal","fiscal","droit"):
            if stem in tokens:
                matched.append(stem)

    legal_raw = len(matched)
    legal_score = min(1.0, math.log1p(legal_raw) / math.log1p(6))  # saturate after ~6 distinct hits
    # Down-weight purely generic matches (no multi-word roles)
    if matched and all(m in {"fiscal","droit","legal","juridique"} for m in matched):
        legal_score *= 0.55  # generic penalty

    recruit_hits = [p for p in RECRUITMENT_PHRASES if p in low]
    negative_hits = [n for n in NEGATIVE_CONTEXT_PHRASES if n in low]
    recruit_score = min(1.0, math.log1p(len(recruit_hits)) / math.log1p(5))

    combined = max(0.0, min(1.0, legal_score * 0.6 + recruit_score * 0.4))
    # Early negative context penalty: if negative phrases detected and no recruitment phrases, heavily downscale combined
    if negative_hits and not recruit_hits:
        combined *= 0.25

    # Additional conservative gates:
    # 1. If only very generic legal stems matched (e.g. just 'droit' or 'fiscal') and no recruitment phrase, downgrade.
    generic_only = False
    if matched and not recruit_hits:
        # If all matches are in this generic set AND count < 2 treat as low signal
        generic_set = {"droit","fiscal","legal","juridique"}
        if all(m.split()[0] in generic_set for m in matched) and len(matched) < 2:
            generic_only = True
    # 2. Negative context phrases without any recruitment phrase should suppress.
    suppress = False
    if negative_hits and not recruit_hits:
        suppress = True
    # 3. Require at least one recruitment phrase OR (>=2 distinct legal role hits) for borderline scores within 0.05 of threshold.
    borderline = combined >= intent_threshold and combined < (intent_threshold + 0.05) and not recruit_hits and len(matched) < 2
    if borderline:
        suppress = True
    if generic_only:
        suppress = True
    # Final suppression rule: even if combined beyond threshold, if only generic matches AND a negative context phrase exists, force other.
    # Hard suppression: any negative context phrase + no recruitment phrase enforces 'autre'
    if (negative_hits and not recruit_hits):
        intent = "autre"
    elif suppress or (negative_hits and generic_only):
        intent = "autre"
    else:
        # Stricter rule: if no recruitment phrase and only generic matches, require combined >= (intent_threshold+0.1) AND at least 2 generic tokens
        if not recruit_hits and all(m in {"fiscal","droit","legal","juridique"} for m in matched):
            if not (combined >= intent_threshold + 0.1 and len(set(matched)) >= 2):
                intent = "autre"
            else:
                intent = "recherche_profil" if (lang_ok and location_ok) else "autre"
        else:
            intent = "recherche_profil" if (combined >= intent_threshold and lang_ok and location_ok and matched) else "autre"
    # Final override: negative context phrases + absence of explicit recruitment phrases => autre
    if negative_hits and not recruit_hits:
        intent = "autre"
    # Global conservative rule: without any explicit recruitment phrase we do not label as recherche_profil
    if not recruit_hits:
        intent = "autre"

    # Confidence components
    components_triggered = sum([
        1 if matched else 0,
        1 if recruit_hits else 0,
        1 if lang_ok else 0,
        1 if location_ok else 0,
    ])
    confidence = components_triggered / 4.0

    return LegalClassification(intent, combined, confidence, matched, location_ok)

__all__ = [
    "LegalClassification","classify_legal_post","LEGAL_ROLE_KEYWORDS"
]
