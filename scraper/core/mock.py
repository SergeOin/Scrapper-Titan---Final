"""Mock post generation logic (extracted from worker)."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List
import random
from ..bootstrap import SCRAPE_MOCK_POSTS_EXTRACTED, SCRAPE_RECRUITMENT_POSTS
from .. import utils

ROLES = [
    "avocat collaborateur","avocat associé","avocat counsel","paralegal","legal counsel","juriste",
    "responsable juridique","directeur juridique","notaire stagiaire","notaire associé","notaire salarié",
    "notaire assistant","clerc de notaire","rédacteur d’actes","responsable fiscal","directeur fiscal",
    "comptable taxateur","formaliste"
]
CONTRATS = ["CDI","CDD","Stage","Alternance","Freelance"]
URGENCES = [
    "prise de poste immédiate","démarrage sous 30 jours","urgence recrutement","création de poste",
    "remplacement départ retraite","renforcement d’équipe"
]
TEMPLATES = [
    "Nous sommes à la recherche d’un {role} ({contrat}) pour renforcer notre équipe ({urgence}).",
    "Vous souhaitez rejoindre notre étude en tant que {role} ({contrat}) ? Postulez ! ({urgence})",
    "Opportunité: poste de {role} ({contrat}). {urgence}. Contactez-nous.",
    "Dans le cadre de notre croissance, nous recrutons un(e) {role} ({contrat}) motivé(e) – {urgence}.",
    "Rejoignez une équipe dynamique : poste {role} ({contrat}) à pourvoir ({urgence}).",
    "Annonce: création de poste {role} ({contrat}) – {urgence} (profil rigoureux & esprit d’équipe).",
    "Talents juridiques : votre profil de {role} ({contrat}) nous intéresse ! ({urgence})",
    "Envie d’évoluer ? Poste {role} ({contrat}) avec responsabilités transverses – {urgence}.",
]

def generate_mock_posts(keyword: str, limit: int, settings, recruitment_threshold: float):
    now_iso = datetime.now(timezone.utc).isoformat()
    posts = []
    limit = max(1, limit)
    for i in range(limit):
        role = ROLES[(i + hash(keyword)) % len(ROLES)]
        template = TEMPLATES[i % len(TEMPLATES)]
        contrat = CONTRATS[(i * 3 + len(keyword)) % len(CONTRATS)]
        urgence = URGENCES[(i * 5 + hash(role)) % len(URGENCES)]
        text = template.format(role=role, contrat=contrat, urgence=urgence)
        if i % 2 == 0 and keyword.lower() not in text.lower():
            text += f" (#{keyword})"
        rscore = utils.compute_recruitment_signal(text)
        if rscore >= recruitment_threshold:
            SCRAPE_RECRUITMENT_POSTS.inc()
        pid = utils.make_post_id(keyword, f"legal-mock-{i}-{role}", now_iso)
        posts.append({
            "id": pid,
            "keyword": keyword,
            "author": "demo_recruteur",
            "text": text,
            "language": "fr",
            "published_at": now_iso,
            "collected_at": now_iso,
            "permalink": f"https://www.linkedin.com/feed/update/{pid}",
            "raw": {"mode": "mock", "role": role, "contrat": contrat, "urgence": urgence},
        })
    SCRAPE_MOCK_POSTS_EXTRACTED.inc(len(posts))
    return posts
