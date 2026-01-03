"""
Titan Scraper - Human Behavior Patterns
========================================
Patterns de comportement humain avancés pour éviter la détection.

Ce module implémente des stratégies sophistiquées pour imiter
un utilisateur LinkedIn réel:
- Patterns de navigation variés
- Sessions réalistes avec pauses naturelles
- Comportement contextuel basé sur l'heure
- Variabilité inter-sessions

Auteur: Titan Scraper Team (Q1 2025)
"""
from __future__ import annotations

import os
import random
import math
from datetime import datetime, time, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Tuple

import structlog

logger = structlog.get_logger(__name__)


# =============================================================================
# CONFIGURATION DU COMPORTEMENT HUMAIN AVANCÉ
# =============================================================================

class BrowsingMood(str, Enum):
    """Humeur de navigation simulée - influence le comportement."""
    FOCUSED = "focused"       # Navigation rapide, ciblée
    DISTRACTED = "distracted" # Pauses fréquentes, navigation lente
    CASUAL = "casual"         # Rythme moyen, comportement standard
    RUSHED = "rushed"         # Navigation très rapide (fin de journée)


class TimeOfDay(str, Enum):
    """Période de la journée - influence le rythme."""
    EARLY_MORNING = "early_morning"  # 6h-9h
    MORNING = "morning"               # 9h-12h
    LUNCH = "lunch"                   # 12h-14h
    AFTERNOON = "afternoon"           # 14h-17h
    EVENING = "evening"               # 17h-19h
    NIGHT = "night"                   # 19h-6h


@dataclass
class SessionProfile:
    """Profil de session pour un comportement cohérent."""
    mood: BrowsingMood
    time_of_day: TimeOfDay
    base_speed_multiplier: float = 1.0
    pause_frequency: float = 0.15  # Probabilité de pause
    max_session_duration_minutes: int = 45
    min_posts_before_break: int = 5
    
    # Variation pour cette session
    scroll_style: str = "smooth"  # smooth, jumpy, slow
    reading_depth: str = "normal"  # shallow, normal, deep


@dataclass
class HumanPatternConfig:
    """Configuration globale des patterns humains."""
    
    # Fenêtres d'activité (heures de bureau françaises)
    active_hours_start: int = 9
    active_hours_end: int = 18
    active_weekdays: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Lun-Ven
    
    # Probabilités de comportement
    mood_weights: dict = field(default_factory=lambda: {
        BrowsingMood.FOCUSED: 0.35,
        BrowsingMood.DISTRACTED: 0.20,
        BrowsingMood.CASUAL: 0.35,
        BrowsingMood.RUSHED: 0.10,
    })
    
    # Limites de session
    min_session_posts: int = 3
    max_session_posts: int = 15
    
    # Variabilité quotidienne (différent chaque jour)
    daily_variance_factor: float = 0.3


# =============================================================================
# GÉNÉRATEUR DE PROFILS DE SESSION
# =============================================================================

def get_time_of_day() -> TimeOfDay:
    """Détermine la période de la journée actuelle."""
    now = datetime.now()
    hour = now.hour
    
    if 6 <= hour < 9:
        return TimeOfDay.EARLY_MORNING
    elif 9 <= hour < 12:
        return TimeOfDay.MORNING
    elif 12 <= hour < 14:
        return TimeOfDay.LUNCH
    elif 14 <= hour < 17:
        return TimeOfDay.AFTERNOON
    elif 17 <= hour < 19:
        return TimeOfDay.EVENING
    else:
        return TimeOfDay.NIGHT


def get_mood_for_time(time_of_day: TimeOfDay) -> BrowsingMood:
    """Génère une humeur réaliste basée sur l'heure."""
    mood_distributions = {
        TimeOfDay.EARLY_MORNING: {
            BrowsingMood.DISTRACTED: 0.4,  # Pas encore réveillé
            BrowsingMood.CASUAL: 0.4,
            BrowsingMood.FOCUSED: 0.2,
            BrowsingMood.RUSHED: 0.0,
        },
        TimeOfDay.MORNING: {
            BrowsingMood.FOCUSED: 0.5,     # Productivité matinale
            BrowsingMood.CASUAL: 0.3,
            BrowsingMood.DISTRACTED: 0.1,
            BrowsingMood.RUSHED: 0.1,
        },
        TimeOfDay.LUNCH: {
            BrowsingMood.DISTRACTED: 0.5,  # Pause déjeuner = distrait
            BrowsingMood.CASUAL: 0.4,
            BrowsingMood.FOCUSED: 0.1,
            BrowsingMood.RUSHED: 0.0,
        },
        TimeOfDay.AFTERNOON: {
            BrowsingMood.FOCUSED: 0.4,
            BrowsingMood.CASUAL: 0.4,
            BrowsingMood.DISTRACTED: 0.15,
            BrowsingMood.RUSHED: 0.05,
        },
        TimeOfDay.EVENING: {
            BrowsingMood.RUSHED: 0.4,      # Fin de journée = pressé
            BrowsingMood.CASUAL: 0.3,
            BrowsingMood.FOCUSED: 0.2,
            BrowsingMood.DISTRACTED: 0.1,
        },
        TimeOfDay.NIGHT: {
            BrowsingMood.DISTRACTED: 0.6,  # Fatigué
            BrowsingMood.CASUAL: 0.3,
            BrowsingMood.FOCUSED: 0.1,
            BrowsingMood.RUSHED: 0.0,
        },
    }
    
    weights = mood_distributions.get(time_of_day, mood_distributions[TimeOfDay.MORNING])
    moods = list(weights.keys())
    probs = list(weights.values())
    
    return random.choices(moods, weights=probs, k=1)[0]


def generate_session_profile() -> SessionProfile:
    """Génère un profil de session réaliste basé sur l'heure et le hasard."""
    time_of_day = get_time_of_day()
    mood = get_mood_for_time(time_of_day)
    
    # Vitesse basée sur l'humeur
    speed_by_mood = {
        BrowsingMood.FOCUSED: random.uniform(0.8, 1.0),
        BrowsingMood.DISTRACTED: random.uniform(1.3, 1.8),
        BrowsingMood.CASUAL: random.uniform(1.0, 1.2),
        BrowsingMood.RUSHED: random.uniform(0.6, 0.8),
    }
    
    # Fréquence de pause basée sur l'humeur
    pause_by_mood = {
        BrowsingMood.FOCUSED: random.uniform(0.05, 0.10),
        BrowsingMood.DISTRACTED: random.uniform(0.20, 0.35),
        BrowsingMood.CASUAL: random.uniform(0.10, 0.18),
        BrowsingMood.RUSHED: random.uniform(0.02, 0.06),
    }
    
    # Style de scroll
    scroll_styles = ["smooth", "jumpy", "slow"]
    scroll_weights = {
        BrowsingMood.FOCUSED: [0.6, 0.3, 0.1],
        BrowsingMood.DISTRACTED: [0.3, 0.2, 0.5],
        BrowsingMood.CASUAL: [0.5, 0.25, 0.25],
        BrowsingMood.RUSHED: [0.2, 0.7, 0.1],
    }
    scroll_style = random.choices(scroll_styles, weights=scroll_weights[mood], k=1)[0]
    
    # Profondeur de lecture
    reading_depths = ["shallow", "normal", "deep"]
    reading_weights = {
        BrowsingMood.FOCUSED: [0.2, 0.5, 0.3],
        BrowsingMood.DISTRACTED: [0.4, 0.4, 0.2],
        BrowsingMood.CASUAL: [0.3, 0.5, 0.2],
        BrowsingMood.RUSHED: [0.7, 0.25, 0.05],
    }
    reading_depth = random.choices(reading_depths, weights=reading_weights[mood], k=1)[0]
    
    # Durée max de session
    duration_by_time = {
        TimeOfDay.EARLY_MORNING: random.randint(20, 35),
        TimeOfDay.MORNING: random.randint(35, 55),
        TimeOfDay.LUNCH: random.randint(15, 30),
        TimeOfDay.AFTERNOON: random.randint(30, 50),
        TimeOfDay.EVENING: random.randint(20, 35),
        TimeOfDay.NIGHT: random.randint(10, 25),
    }
    
    return SessionProfile(
        mood=mood,
        time_of_day=time_of_day,
        base_speed_multiplier=speed_by_mood[mood],
        pause_frequency=pause_by_mood[mood],
        max_session_duration_minutes=duration_by_time[time_of_day],
        min_posts_before_break=random.randint(3, 8),
        scroll_style=scroll_style,
        reading_depth=reading_depth,
    )


# =============================================================================
# GÉNÉRATEUR DE DÉLAIS HUMAINS
# =============================================================================

def get_human_delay(
    base_ms: int,
    profile: Optional[SessionProfile] = None,
    action_type: str = "general"
) -> int:
    """Génère un délai réaliste basé sur le profil de session.
    
    Args:
        base_ms: Délai de base en millisecondes
        profile: Profil de session (généré si None)
        action_type: Type d'action (scroll, read, click, navigate)
    
    Returns:
        Délai ajusté en millisecondes
    """
    if profile is None:
        profile = generate_session_profile()
    
    # Appliquer le multiplicateur de vitesse
    adjusted = base_ms * profile.base_speed_multiplier
    
    # Multiplicateurs par type d'action
    action_multipliers = {
        "scroll": random.uniform(0.8, 1.2),
        "read": random.uniform(1.0, 1.5) if profile.reading_depth == "deep" else random.uniform(0.7, 1.0),
        "click": random.uniform(0.9, 1.1),
        "navigate": random.uniform(1.0, 1.3),
        "general": 1.0,
    }
    
    adjusted *= action_multipliers.get(action_type, 1.0)
    
    # Ajouter de la variance gaussienne (±25%)
    variance = adjusted * 0.25
    adjusted = random.gauss(adjusted, variance)
    
    # Ajouter parfois un "micro-freeze" (hésitation humaine)
    if random.random() < 0.05:
        adjusted += random.randint(500, 2000)
    
    return max(100, int(adjusted))


def should_take_break(
    posts_seen: int,
    session_start: datetime,
    profile: Optional[SessionProfile] = None
) -> Tuple[bool, int]:
    """Détermine si une pause est nécessaire.
    
    Args:
        posts_seen: Nombre de posts vus dans cette session
        session_start: Début de la session
        profile: Profil de session
    
    Returns:
        (should_break, break_duration_seconds)
    """
    if profile is None:
        profile = generate_session_profile()
    
    elapsed_minutes = (datetime.now() - session_start).total_seconds() / 60
    
    # Vérifier durée max de session
    if elapsed_minutes >= profile.max_session_duration_minutes:
        # Longue pause obligatoire
        return True, random.randint(300, 600)  # 5-10 minutes
    
    # Vérifier si assez de posts vus
    if posts_seen >= profile.min_posts_before_break:
        if random.random() < profile.pause_frequency:
            # Courte pause
            return True, random.randint(60, 180)  # 1-3 minutes
    
    # Pause aléatoire basée sur le temps
    if elapsed_minutes > 10 and random.random() < 0.08:
        return True, random.randint(120, 300)  # 2-5 minutes
    
    return False, 0


# =============================================================================
# PATTERNS DE NAVIGATION
# =============================================================================

class NavigationPattern:
    """Génère des patterns de navigation réalistes."""
    
    PATTERNS = {
        "linear": ["search", "scroll", "scroll", "next_keyword"],
        "exploratory": ["search", "scroll", "profile_glance", "scroll", "scroll", "next_keyword"],
        "focused": ["search", "scroll", "next_keyword"],
        "distracted": ["search", "scroll", "pause", "scroll", "profile_glance", "pause", "next_keyword"],
    }
    
    @classmethod
    def get_pattern(cls, profile: SessionProfile) -> List[str]:
        """Retourne un pattern de navigation basé sur le profil."""
        mood_to_pattern = {
            BrowsingMood.FOCUSED: "focused",
            BrowsingMood.DISTRACTED: "distracted",
            BrowsingMood.CASUAL: "linear",
            BrowsingMood.RUSHED: "focused",
        }
        
        pattern_name = mood_to_pattern.get(profile.mood, "linear")
        
        # Parfois varier le pattern
        if random.random() < 0.2:
            pattern_name = random.choice(list(cls.PATTERNS.keys()))
        
        return cls.PATTERNS[pattern_name]


# =============================================================================
# GESTION DES SESSIONS QUOTIDIENNES
# =============================================================================

@dataclass
class DailyBehavior:
    """Comportement quotidien pour variation inter-jour."""
    date: str
    activity_level: float = 1.0  # 0.5 = demi-journée, 1.5 = journée intense
    preferred_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 14, 15, 16])
    session_count_target: int = 8


def generate_daily_behavior() -> DailyBehavior:
    """Génère un comportement quotidien varié."""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Variabilité basée sur le jour de la semaine
    weekday = datetime.now().weekday()
    
    # Lundi/Vendredi = moins actif, milieu de semaine = plus actif
    activity_by_day = {
        0: random.uniform(0.7, 0.9),   # Lundi - reprise
        1: random.uniform(0.9, 1.1),   # Mardi
        2: random.uniform(1.0, 1.2),   # Mercredi - pic
        3: random.uniform(0.9, 1.1),   # Jeudi
        4: random.uniform(0.6, 0.85),  # Vendredi - relax
        5: 0.0,                         # Samedi - repos
        6: 0.0,                         # Dimanche - repos
    }
    
    activity = activity_by_day.get(weekday, 1.0)
    
    # Heures préférées avec variabilité
    base_hours = [9, 10, 11, 14, 15, 16, 17]
    num_hours = max(3, int(len(base_hours) * activity))
    preferred_hours = sorted(random.sample(base_hours, min(num_hours, len(base_hours))))
    
    # Nombre de sessions cible
    session_count = max(4, int(10 * activity))
    
    return DailyBehavior(
        date=today,
        activity_level=activity,
        preferred_hours=preferred_hours,
        session_count_target=session_count,
    )


def is_good_time_to_scrape(daily_behavior: Optional[DailyBehavior] = None) -> Tuple[bool, str]:
    """Vérifie si c'est un bon moment pour scraper.
    
    Returns:
        (is_good_time, reason)
    """
    now = datetime.now()
    
    if daily_behavior is None:
        daily_behavior = generate_daily_behavior()
    
    # Pas de scraping le weekend
    if now.weekday() >= 5:
        return False, "weekend"
    
    # Vérifier les heures
    current_hour = now.hour
    
    if current_hour < 9 or current_hour >= 19:
        return False, "outside_business_hours"
    
    # Vérifier si c'est une heure préférée
    if current_hour in daily_behavior.preferred_hours:
        return True, "preferred_hour"
    
    # Autoriser quand même avec probabilité réduite
    if random.random() < 0.3:
        return True, "random_allowed"
    
    return False, "not_preferred_hour"


# =============================================================================
# HELPER FUNCTIONS POUR INTÉGRATION
# =============================================================================

# Cache du profil de session actuel
_current_session_profile: Optional[SessionProfile] = None
_session_start_time: Optional[datetime] = None
_posts_seen_this_session: int = 0


def start_new_session() -> SessionProfile:
    """Démarre une nouvelle session avec un profil frais."""
    global _current_session_profile, _session_start_time, _posts_seen_this_session
    
    _current_session_profile = generate_session_profile()
    _session_start_time = datetime.now()
    _posts_seen_this_session = 0
    
    logger.info(
        "human_session_started",
        mood=_current_session_profile.mood.value,
        time_of_day=_current_session_profile.time_of_day.value,
        speed_multiplier=round(_current_session_profile.base_speed_multiplier, 2),
        max_duration_min=_current_session_profile.max_session_duration_minutes,
    )
    
    return _current_session_profile


def get_current_session() -> SessionProfile:
    """Retourne le profil de session actuel ou en crée un nouveau."""
    global _current_session_profile
    
    if _current_session_profile is None:
        return start_new_session()
    
    return _current_session_profile


def record_post_seen():
    """Enregistre qu'un post a été vu."""
    global _posts_seen_this_session
    _posts_seen_this_session += 1


def check_session_break() -> Tuple[bool, int]:
    """Vérifie si une pause de session est nécessaire."""
    global _session_start_time, _posts_seen_this_session, _current_session_profile
    
    if _session_start_time is None:
        return False, 0
    
    return should_take_break(
        _posts_seen_this_session,
        _session_start_time,
        _current_session_profile,
    )


def get_adapted_delay(base_ms: int, action_type: str = "general") -> int:
    """Retourne un délai adapté au profil de session actuel."""
    return get_human_delay(base_ms, get_current_session(), action_type)
