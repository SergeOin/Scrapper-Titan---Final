from __future__ import annotations
from datetime import datetime, timezone
from typing import List
import random

from domain.models import PostModel
from scraper import utils
from scraper.bootstrap import SCRAPE_RECRUITMENT_POSTS, SCRAPE_MOCK_POSTS_EXTRACTED


class MockGenerator:
    """Generate synthetic legal/recruitment oriented posts for demo / fallback.

    Previously inline in worker.process_keyword; extracted for clarity & testability.
    """

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
        "Opportunité: poste de {role} ouvert ({contrat}). {urgence}. Contactez-nous.",
        "Dans le cadre de notre croissance, nous recrutons un(e) {role} ({contrat}) motivé(e) – {urgence}.",
        "Rejoignez une équipe dynamique : poste {role} ({contrat}) à pourvoir ({urgence}).",
        "Annonce: création de poste {role} ({contrat}) – {urgence} (profil rigoureux & esprit d’équipe).",
        "Talents juridiques : votre profil de {role} ({contrat}) nous intéresse ! ({urgence})",
        "Envie d’évoluer ? Poste {role} ({contrat}) avec responsabilités transverses – {urgence}.",
    ]

    @classmethod
    def generate(cls, keyword: str, ctx) -> List[PostModel]:
        now_iso = datetime.now(timezone.utc).isoformat()
        limit = min(int(getattr(ctx.settings, 'max_mock_posts', 5) or 5), ctx.settings.max_posts_per_keyword)
        out: List[PostModel] = []
        for i in range(limit):
            role = cls.ROLES[(i + hash(keyword)) % len(cls.ROLES)]
            template = cls.TEMPLATES[i % len(cls.TEMPLATES)]
            contrat = cls.CONTRATS[(i * 3 + len(keyword)) % len(cls.CONTRATS)]
            urgence = cls.URGENCES[(i * 5 + hash(role)) % len(cls.URGENCES)]
            text = template.format(role=role, contrat=contrat, urgence=urgence)
            if i % 2 == 0 and keyword.lower() not in text.lower():
                text += f" (#{keyword})"
            rscore = utils.compute_recruitment_signal(text)
            if rscore >= ctx.settings.recruitment_signal_threshold:
                SCRAPE_RECRUITMENT_POSTS.inc()
            pid = utils.make_post_id(keyword, f"legal-mock-{i}-{role}", now_iso)
            out.append(PostModel(
                id=pid,
                keyword=keyword,
                author="demo_recruteur",
                author_profile=None,
                company=None,
                text=text,
                language="fr",
                published_at=now_iso,
                collected_at=now_iso,
                permalink=f"https://www.linkedin.com/feed/update/{pid}",
                raw={"mode":"mock","role":role,"contrat":contrat,"urgence":urgence}
            ))
        SCRAPE_MOCK_POSTS_EXTRACTED.inc(len(out))
        return out
