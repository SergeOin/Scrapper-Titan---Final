"""
Titan Scraper - Module Human Actions
=====================================
Simulation de comportement humain sur LinkedIn.

Ce module centralise toutes les actions qui imitent un utilisateur réel:
- Mouvements de souris (courbes de Bézier)
- Scrolling naturel avec vitesse variable
- Pauses de lecture
- Likes occasionnels
- Expansion des posts (voir plus)
- Visites de profil
- Pauses café

L'objectif est de rendre le comportement du bot indiscernable
d'un utilisateur humain pour éviter la détection LinkedIn.

Créé lors de la fusion scrape_subprocess.py -> worker.py (Phase 2)
"""

import random
import logging
from typing import Any, Optional

from scraper.timing import (
    random_delay,
    POST_READ_DELAY_MIN,
    POST_READ_DELAY_MAX,
    MICRO_PAUSE_MIN,
    MICRO_PAUSE_MAX,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION ACTIONS HUMAINES - OPTIMISÉ LONGÉVITÉ COMPTE
# =============================================================================

# Probabilités d'actions par post - TOUT DÉSACTIVÉ pour éviter détection
LIKE_PROBABILITY = 0.0           # DÉSACTIVÉ - risque de ban
PROFILE_VISIT_PROBABILITY = 0.0  # DÉSACTIVÉ - risque de ban
EXPAND_POST_PROBABILITY = 0.0    # DÉSACTIVÉ - crée un pattern détectable

# Probabilité de pause café par session - TRÈS FRÉQUENT pour naturalité
COFFEE_BREAK_PROBABILITY = 0.15  # 15% de chance par keyword (très naturel)

# Délais pour actions humaines (ms) - MODE ULTRA-PRUDENT
LIKE_DELAY_MIN = 1000
LIKE_DELAY_MAX = 3000
PROFILE_VISIT_DURATION_MIN = 15000   # 15 secondes
PROFILE_VISIT_DURATION_MAX = 45000   # 45 secondes
COFFEE_BREAK_MIN = 600000   # 10 minutes minimum (très long)
COFFEE_BREAK_MAX = 1800000  # 30 minutes maximum (très long)

# Sélecteurs pour les boutons d'action LinkedIn
LIKE_BUTTON_SELECTORS = [
    "button.react-button__trigger[aria-label*='J\\'aime']",
    "button.react-button__trigger[aria-label*='Like']",
    "button.reactions-react-button[aria-label*='J\\'aime']",
    "button.reactions-react-button[aria-label*='Like']",
    "button[aria-label*='Réagir'][aria-pressed='false']",
    "button[aria-label*='React'][aria-pressed='false']",
    "span.reactions-react-button button",
    "button.artdeco-button[aria-label*='aime']",
]

EXPAND_POST_SELECTORS = [
    "button.feed-shared-inline-show-more-text__see-more-less-toggle",
    "button[aria-label*='voir plus']",
    "button[aria-label*='see more']",
    "span.feed-shared-inline-show-more-text__see-more-less-toggle",
]


# =============================================================================
# MOUVEMENTS DE SOURIS
# =============================================================================

async def simulate_human_mouse_movement(
    page,
    target_x: Optional[int] = None,
    target_y: Optional[int] = None
) -> None:
    """Simule un mouvement de souris humain avec courbe de Bézier.
    
    Le mouvement n'est pas linéaire - il suit une courbe ease-in-out
    avec un léger bruit aléatoire pour imiter le tremblement naturel
    de la main humaine.
    
    Args:
        page: Instance Playwright Page
        target_x: Coordonnée X cible (aléatoire si None)
        target_y: Coordonnée Y cible (aléatoire si None)
    """
    try:
        viewport = page.viewport_size
        if not viewport:
            return
        
        # Position cible ou aléatoire
        end_x = target_x if target_x else random.randint(100, viewport['width'] - 100)
        end_y = target_y if target_y else random.randint(100, viewport['height'] - 100)
        
        # Position de départ aléatoire
        start_x = random.randint(50, viewport['width'] - 50)
        start_y = random.randint(50, viewport['height'] - 50)
        
        # Nombre de pas (plus de pas = mouvement plus fluide)
        steps = random.randint(5, 15)
        
        for i in range(steps):
            # Interpolation avec courbe ease-in-out
            progress = i / steps
            progress = progress * progress * (3 - 2 * progress)  # Smoothstep
            
            # Ajout de bruit pour simuler le tremblement de la main
            x = int(start_x + (end_x - start_x) * progress + random.randint(-5, 5))
            y = int(start_y + (end_y - start_y) * progress + random.randint(-5, 5))
            
            await page.mouse.move(x, y)
            await page.wait_for_timeout(random.randint(10, 50))
            
    except Exception:
        pass  # Ignorer les erreurs de mouvement souris


async def move_to_element(page, element) -> bool:
    """Déplace la souris vers un élément de manière naturelle.
    
    Args:
        page: Instance Playwright Page
        element: Élément DOM Playwright
        
    Returns:
        bool: True si le mouvement a réussi
    """
    try:
        box = await element.bounding_box()
        if not box:
            return False
        
        # Cibler le centre avec un léger décalage aléatoire
        target_x = int(box['x'] + box['width'] / 2 + random.randint(-5, 5))
        target_y = int(box['y'] + box['height'] / 2 + random.randint(-3, 3))
        
        await simulate_human_mouse_movement(page, target_x, target_y)
        return True
        
    except Exception:
        return False


# =============================================================================
# SCROLLING
# =============================================================================

async def simulate_human_scroll(
    page,
    direction: str = "down",
    amount: Optional[int] = None
) -> None:
    """Simule un scroll humain avec vitesse variable.
    
    Le scroll est effectué en plusieurs étapes avec des vitesses
    légèrement différentes pour imiter le comportement d'un doigt
    sur un trackpad ou d'une molette de souris.
    
    Args:
        page: Instance Playwright Page
        direction: "down" ou "up"
        amount: Pixels à scroller (aléatoire si None)
    """
    try:
        if amount is None:
            amount = random.randint(200, 500)
        
        if direction == "up":
            amount = -amount
        
        # Scroll en plusieurs étapes avec vitesse variable
        steps = random.randint(3, 7)
        per_step = amount // steps
        
        for _ in range(steps):
            # Ajout de variation à chaque étape
            step_amount = per_step + random.randint(-20, 20)
            await page.mouse.wheel(0, step_amount)
            await page.wait_for_timeout(random.randint(50, 150))
            
    except Exception:
        # Fallback au scroll JavaScript
        try:
            await page.evaluate(f"window.scrollBy(0, {amount})")
        except Exception:
            pass


async def scroll_to_element(page, element) -> bool:
    """Scroll vers un élément de manière naturelle.
    
    Args:
        page: Instance Playwright Page
        element: Élément DOM Playwright
        
    Returns:
        bool: True si le scroll a réussi
    """
    try:
        await element.scroll_into_view_if_needed()
        await page.wait_for_timeout(random.randint(300, 600))
        return True
    except Exception:
        return False


# =============================================================================
# PAUSES ET LECTURE
# =============================================================================

async def simulate_reading_pause(page) -> None:
    """Simule une pause de lecture naturelle.
    
    Un utilisateur réel prend le temps de lire les posts.
    Cette fonction ajoute une pause réaliste avec parfois
    un petit mouvement de souris pendant la lecture.
    
    Args:
        page: Instance Playwright Page
    """
    await page.wait_for_timeout(random_delay(POST_READ_DELAY_MIN, POST_READ_DELAY_MAX))
    
    # Parfois, simuler un petit mouvement de souris pendant la lecture
    if random.random() < 0.3:
        await simulate_human_mouse_movement(page)


async def simulate_coffee_break(page) -> None:
    """Simule une pause café (longue inactivité naturelle).
    
    Cette fonction est appelée occasionnellement pour simuler
    le comportement d'un utilisateur qui fait une pause.
    La durée est de 2 à 5 minutes.
    
    Args:
        page: Instance Playwright Page
    """
    pause_duration = random.randint(COFFEE_BREAK_MIN, COFFEE_BREAK_MAX)
    
    logger.info(f"Taking coffee break ({pause_duration/1000:.0f}s)")
    
    # Parfois, revenir au feed pendant la pause
    if random.random() < 0.3:
        try:
            await page.goto("https://www.linkedin.com/feed/", timeout=15000)
        except Exception:
            pass
    
    # Attendre
    await page.wait_for_timeout(pause_duration)
    
    # Petit mouvement de souris au retour
    await simulate_human_mouse_movement(page)


def should_take_coffee_break() -> bool:
    """Détermine si on devrait prendre une pause café.
    
    Returns:
        bool: True si on devrait prendre une pause
    """
    return random.random() < COFFEE_BREAK_PROBABILITY


# =============================================================================
# ACTIONS SUR LES POSTS
# =============================================================================

async def simulate_like_post(page, post_element) -> bool:
    """Simule un like sur un post de manière humaine.
    
    Le like n'est effectué que selon une probabilité (8% par défaut)
    pour imiter le comportement d'un utilisateur réel qui ne like
    pas tous les posts.
    
    Args:
        page: Instance Playwright Page
        post_element: Élément DOM du post
        
    Returns:
        bool: True si le like a été effectué
    """
    try:
        # Vérifier la probabilité
        if random.random() > LIKE_PROBABILITY:
            return False
        
        # Chercher le bouton like dans le post
        like_button = None
        for selector in LIKE_BUTTON_SELECTORS:
            try:
                like_button = await post_element.query_selector(selector)
                if like_button:
                    # Vérifier que le bouton n'est pas déjà "liké"
                    aria_pressed = await like_button.get_attribute("aria-pressed")
                    if aria_pressed == "true":
                        return False  # Déjà liké
                    break
            except Exception:
                continue
        
        if not like_button:
            return False
        
        # 1. Mouvement de souris vers le bouton
        await move_to_element(page, like_button)
        
        # 2. Petite pause avant le clic (hésitation humaine)
        await page.wait_for_timeout(random.randint(MICRO_PAUSE_MIN, MICRO_PAUSE_MAX))
        
        # 3. Cliquer sur le bouton like
        await like_button.click()
        
        # 4. Pause après le like (satisfaction humaine)
        await page.wait_for_timeout(random_delay(LIKE_DELAY_MIN, LIKE_DELAY_MAX))
        
        logger.debug("Liked a post (human behavior simulation)")
        return True
        
    except Exception as e:
        logger.debug(f"Error simulating like: {e}")
        return False


async def simulate_expand_post(page, post_element) -> bool:
    """Simule un clic sur "voir plus" pour étendre un post.
    
    Args:
        page: Instance Playwright Page
        post_element: Élément DOM du post
        
    Returns:
        bool: True si l'expansion a été effectuée
    """
    try:
        # Vérifier la probabilité
        if random.random() > EXPAND_POST_PROBABILITY:
            return False
        
        # Chercher le bouton "voir plus"
        expand_button = None
        for selector in EXPAND_POST_SELECTORS:
            try:
                expand_button = await post_element.query_selector(selector)
                if expand_button:
                    is_visible = await expand_button.is_visible()
                    if is_visible:
                        break
                    expand_button = None
            except Exception:
                continue
        
        if not expand_button:
            return False
        
        # Mouvement souris naturel
        await move_to_element(page, expand_button)
        
        # Micro-pause puis clic
        await page.wait_for_timeout(random.randint(MICRO_PAUSE_MIN, MICRO_PAUSE_MAX))
        await expand_button.click()
        
        # Pause pour "lire" le contenu étendu
        await page.wait_for_timeout(random_delay(POST_READ_DELAY_MIN * 2, POST_READ_DELAY_MAX * 2))
        
        logger.debug("Expanded a post (see more)")
        return True
        
    except Exception as e:
        logger.debug(f"Error expanding post: {e}")
        return False


async def simulate_visit_profile(page, profile_url: str) -> bool:
    """Simule une visite de profil occasionnelle.
    
    Cette action est très humaine - les utilisateurs cliquent souvent
    sur les profils des personnes qui postent des offres intéressantes.
    
    Args:
        page: Instance Playwright Page
        profile_url: URL du profil à visiter
        
    Returns:
        bool: True si la visite a été effectuée
    """
    try:
        # Vérifier la probabilité
        if random.random() > PROFILE_VISIT_PROBABILITY:
            return False
        
        if not profile_url or not profile_url.startswith("https://"):
            return False
        
        # Sauvegarder l'URL actuelle pour revenir
        current_url = page.url
        
        # Naviguer vers le profil
        logger.debug(f"Visiting profile {profile_url[:50]}...")
        await page.goto(profile_url, timeout=15000)
        
        # Attendre le chargement
        await page.wait_for_timeout(random_delay(2000, 4000))
        
        # Simuler la lecture du profil
        await simulate_human_scroll(page, "down", random.randint(200, 400))
        await page.wait_for_timeout(
            random_delay(PROFILE_VISIT_DURATION_MIN, PROFILE_VISIT_DURATION_MAX)
        )
        
        # Parfois scroller un peu plus
        if random.random() < 0.4:
            await simulate_human_scroll(page, "down", random.randint(150, 300))
            await page.wait_for_timeout(random_delay(1500, 3000))
        
        # Revenir à la page précédente
        await page.goto(current_url, timeout=15000)
        await page.wait_for_timeout(random_delay(2000, 4000))
        
        logger.debug("Profile visit completed, returned to search")
        return True
        
    except Exception as e:
        logger.debug(f"Error visiting profile: {e}")
        # Essayer de revenir à la page de recherche
        try:
            await page.go_back()
        except Exception:
            pass
        return False


async def perform_human_actions_on_post(
    page,
    post_element,
    post_data: dict[str, Any]
) -> dict[str, bool]:
    """Effectue des actions humaines aléatoires sur un post.
    
    Cette fonction orchestre les différentes actions possibles
    (like, expand, visit profile) de manière naturelle et probabiliste.
    
    Args:
        page: Instance Playwright Page
        post_element: Élément DOM du post
        post_data: Données du post extrait (doit contenir 'author_profile')
        
    Returns:
        dict: {"liked": bool, "expanded": bool, "profile_visited": bool}
    """
    actions = {
        "liked": False,
        "expanded": False,
        "profile_visited": False,
    }
    
    try:
        # 1. Parfois étendre le post d'abord (voir plus)
        actions["expanded"] = await simulate_expand_post(page, post_element)
        
        # 2. Simuler la lecture
        await simulate_reading_pause(page)
        
        # 3. Parfois liker le post
        actions["liked"] = await simulate_like_post(page, post_element)
        
        # 4. Très rarement, visiter le profil de l'auteur
        # Seulement si on n'a pas fait trop d'actions déjà
        if not actions["liked"] and not actions["expanded"]:
            profile_url = post_data.get("author_profile")
            if profile_url:
                actions["profile_visited"] = await simulate_visit_profile(page, profile_url)
        
    except Exception as e:
        logger.debug(f"Error in human actions: {e}")
    
    return actions


# =============================================================================
# ULTRA-PRUDENT SESSION MANAGEMENT - ÉVITE LA DÉTECTION LINKEDIN
# =============================================================================

# Compteur de keywords traités dans la session
_session_keyword_count = 0
_session_start_time = None

# Limites de session ultra-prudentes
SESSION_KEYWORD_LIMIT = 8   # Max 8 keywords par session avant pause longue
SESSION_MAX_DURATION_MIN = 45  # Max 45 minutes de session continue


async def should_take_session_break() -> tuple[bool, str]:
    """Détermine si on devrait prendre une pause de session.
    
    Pour éviter les patterns détectables, on limite:
    - Le nombre de keywords par session
    - La durée continue de scraping
    
    Returns:
        tuple: (should_break: bool, reason: str)
    """
    global _session_keyword_count, _session_start_time
    import time
    
    if _session_start_time is None:
        _session_start_time = time.time()
    
    _session_keyword_count += 1
    
    # Vérifier limite de keywords
    if _session_keyword_count >= SESSION_KEYWORD_LIMIT:
        return True, f"keyword_limit ({SESSION_KEYWORD_LIMIT} keywords)"
    
    # Vérifier durée de session
    elapsed_min = (time.time() - _session_start_time) / 60
    if elapsed_min >= SESSION_MAX_DURATION_MIN:
        return True, f"duration_limit ({SESSION_MAX_DURATION_MIN} min)"
    
    return False, ""


async def simulate_session_break(page) -> None:
    """Simule une pause de session longue (comme un utilisateur qui part).
    
    Cette pause est beaucoup plus longue qu'une pause café.
    Elle simule un utilisateur qui ferme LinkedIn pour faire autre chose.
    
    Args:
        page: Instance Playwright Page
    """
    global _session_keyword_count, _session_start_time
    import time
    
    # Pause de 20-45 minutes
    pause_duration = random.randint(1200000, 2700000)  # 20-45 min en ms
    
    logger.info(f"Taking session break ({pause_duration/60000:.0f} min) - simulating user leaving")
    
    # Parfois naviguer vers une autre page LinkedIn (comme un vrai utilisateur)
    if random.random() < 0.4:
        try:
            await page.goto("https://www.linkedin.com/", timeout=15000)
            await page.wait_for_timeout(random.randint(5000, 15000))
        except Exception:
            pass
    
    # Attendre la pause longue
    await page.wait_for_timeout(pause_duration)
    
    # Reset des compteurs de session
    _session_keyword_count = 0
    _session_start_time = time.time()
    
    # Mouvement de souris au "retour"
    await simulate_human_mouse_movement(page)
    
    logger.info("Session break ended, resuming activity")


def reset_session_counters() -> None:
    """Reset les compteurs de session (à appeler au démarrage)."""
    global _session_keyword_count, _session_start_time
    import time
    _session_keyword_count = 0
    _session_start_time = time.time()


async def add_random_human_noise(page) -> None:
    """Ajoute du bruit aléatoire pour casser les patterns.
    
    Actions aléatoires qui n'ont pas de but fonctionnel mais
    qui rendent le comportement plus imprévisible.
    
    Args:
        page: Instance Playwright Page
    """
    action = random.choice([
        "mouse_move",
        "scroll_up",
        "micro_pause",
        "nothing",
        "nothing",  # Plus de chance de ne rien faire
    ])
    
    try:
        if action == "mouse_move":
            await simulate_human_mouse_movement(page)
        elif action == "scroll_up":
            await simulate_human_scroll(page, direction="up", amount=random.randint(50, 150))
        elif action == "micro_pause":
            await page.wait_for_timeout(random.randint(1000, 3000))
    except Exception:
        pass


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Mouvements souris
    "simulate_human_mouse_movement",
    "move_to_element",
    # Scrolling
    "simulate_human_scroll",
    "scroll_to_element",
    # Pauses
    "simulate_reading_pause",
    "simulate_coffee_break",
    "should_take_coffee_break",
    # Session management (ULTRA-PRUDENT)
    "should_take_session_break",
    "simulate_session_break",
    "reset_session_counters",
    "add_random_human_noise",
    # Actions posts
    "simulate_like_post",
    "simulate_expand_post",
    "simulate_visit_profile",
    "perform_human_actions_on_post",
    # Configuration
    "LIKE_PROBABILITY",
    "PROFILE_VISIT_PROBABILITY",
    "EXPAND_POST_PROBABILITY",
    "COFFEE_BREAK_PROBABILITY",
    "SESSION_KEYWORD_LIMIT",
    "SESSION_MAX_DURATION_MIN",
    "LIKE_BUTTON_SELECTORS",
    "EXPAND_POST_SELECTORS",
]
