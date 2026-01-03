"""
Titan Scraper - Module Stealth
==============================
Anti-détection et mode furtif pour LinkedIn.

Ce module centralise toutes les fonctions de camouflage du bot:
- Options de contexte browser (viewport, user-agent, locale)
- Scripts anti-détection (masquage webdriver, plugins)
- Détection des pages de restriction LinkedIn

Créé lors de la fusion scrape_subprocess.py → worker.py (Phase 2)
"""

import os
import random
from typing import Any

# =============================================================================
# CONFIGURATION STEALTH
# =============================================================================

# User agents réalistes (rotation)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

# Viewports réalistes (résolutions courantes)
VIEWPORT_PRESETS = [
    {"width": 1920, "height": 1080},  # Full HD
    {"width": 1366, "height": 768},   # Laptop HD
    {"width": 1536, "height": 864},   # Laptop HD+
    {"width": 1280, "height": 720},   # HD
    {"width": 1440, "height": 900},   # Mac 13"
    {"width": 1680, "height": 1050},  # Mac 15"
]

# Pages de restriction/warning LinkedIn à détecter
# NOTE: Ces indicateurs doivent être TRÈS spécifiques pour éviter les faux positifs
RESTRICTION_INDICATORS = [
    "temporairement restreint",
    "temporarily restricted",
    "compte est restreint",
    "account is restricted",
    "account has been restricted",
    "votre compte a été restreint",
    "your account has been suspended",
    "compte suspendu",
    "logiciels d'automatisation",
    "automation software detected",
    "automated behavior",
    "comportement automatisé détecté",
]

# Indicateurs IGNORÉS (faux positifs fréquents) - checkpoint normal
FALSE_POSITIVE_INDICATORS = [
    "security verification",
    "vérification de sécurité",
    "unusual activity",
    "activité inhabituelle",
    "prove you're not a robot",
    "prouvez que vous n'êtes pas un robot",
    "checkpoint",
    "we've detected",
    "nous avons détecté",
]


# =============================================================================
# FONCTIONS STEALTH
# =============================================================================

def stealth_enabled() -> bool:
    """Mode stealth ACTIVÉ PAR DÉFAUT pour éviter la détection LinkedIn.
    
    Peut être désactivé avec STEALTH_ENABLED=0 si nécessaire pour le debug.
    
    Returns:
        bool: True si le mode stealth est activé
    """
    val = os.environ.get("STEALTH_ENABLED", "1")  # Activé par défaut
    return val.lower() not in ("0", "false", "no", "off")


def get_random_viewport() -> dict[str, int]:
    """Retourne un viewport aléatoire réaliste.
    
    Utilise soit un preset, soit génère des dimensions légèrement randomisées.
    
    Returns:
        dict: {"width": int, "height": int}
    """
    if random.random() < 0.7:
        # 70% du temps: preset exact
        return random.choice(VIEWPORT_PRESETS).copy()
    else:
        # 30% du temps: dimensions aléatoires
        return {
            "width": random.randint(1280, 1920),
            "height": random.randint(768, 1080),
        }


def get_random_user_agent() -> str:
    """Retourne un user agent aléatoire réaliste.
    
    Returns:
        str: User agent string
    """
    return random.choice(USER_AGENTS)


def get_stealth_context_options() -> dict[str, Any]:
    """Retourne les options de contexte browser pour le mode stealth.
    
    Ces options sont appliquées lors de la création du contexte Playwright.
    Elles imitent un navigateur réel avec:
    - Viewport réaliste
    - User agent récent
    - Locale française
    - Timezone Paris
    - Géolocalisation Paris (optionnel)
    
    Returns:
        dict: Options de contexte Playwright
    """
    if not stealth_enabled():
        return {}
    
    return {
        "viewport": get_random_viewport(),
        "user_agent": get_random_user_agent(),
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
        "geolocation": {"latitude": 48.8566, "longitude": 2.3522},  # Paris
        "permissions": ["geolocation"],
        "color_scheme": "light",
        "device_scale_factor": random.choice([1, 1.25, 1.5]),
        "has_touch": False,
        "is_mobile": False,
        "java_script_enabled": True,
    }


# Script d'initialisation anti-détection
ANTI_DETECTION_SCRIPT = """
// Masquer la propriété webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Masquer les plugins Playwright
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' },
    ]
});

// Masquer les langues
Object.defineProperty(navigator, 'languages', {
    get: () => ['fr-FR', 'fr', 'en-US', 'en']
});

// Chrome runtime (évite la détection "headless")
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

// Permissions API override
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Console.debug leak prevention
window.console.debug = () => {};

// WebGL vendor/renderer masking
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) {
        return 'Intel Inc.';
    }
    if (parameter === 37446) {
        return 'Intel Iris OpenGL Engine';
    }
    return getParameter.call(this, parameter);
};
"""


async def apply_stealth_scripts(page) -> None:
    """Applique des scripts anti-détection au navigateur.
    
    Ces scripts masquent les signatures d'automatisation Playwright:
    - Propriété navigator.webdriver
    - Plugins et langues
    - Chrome runtime
    - Permissions API
    - WebGL vendor
    
    Args:
        page: Instance Playwright Page
    """
    if not stealth_enabled():
        return
    
    await page.add_init_script(ANTI_DETECTION_SCRIPT)


async def detect_restriction_page(page) -> tuple[bool, str]:
    """Détecte si la page actuelle est une page de restriction LinkedIn.
    
    Cette fonction est conservatrice pour éviter les faux positifs.
    Les checkpoints normaux (captcha, vérification email) ne sont PAS 
    considérés comme des blocages. Seuls les vrais messages de 
    restriction/suspension déclenchent l'alerte.
    
    Args:
        page: Instance Playwright Page
        
    Returns:
        tuple: (is_restricted: bool, reason: str)
            - is_restricted: True si restriction détectée
            - reason: Description de la restriction
    """
    try:
        page_content = await page.content()
        page_content_lower = page_content.lower()
        page_url = page.url.lower()
        page_title = (await page.title()).lower()
        
        # Vérifier les vrais indicateurs de restriction
        for indicator in RESTRICTION_INDICATORS:
            if indicator.lower() in page_content_lower or indicator.lower() in page_title:
                return True, f"Detected: {indicator}"
        
        # URL-based detection - SEULEMENT pour les vrais blocages
        # NOTE: "checkpoint" et "challenge" sont des pages NORMALES
        if "restricted" in page_url or "suspended" in page_url:
            return True, f"Restricted URL: {page_url}"
        
        return False, ""
        
    except Exception as e:
        # En cas d'erreur, ne pas bloquer (faux négatif préférable à faux positif)
        return False, ""


def is_false_positive_checkpoint(page_content: str, page_url: str) -> bool:
    """Vérifie si une page est un checkpoint normal (pas une restriction).
    
    LinkedIn affiche parfois des pages de vérification légitimes qui ne sont
    pas des blocages:
    - Captcha
    - Vérification email
    - Challenge de connexion
    
    Args:
        page_content: Contenu HTML de la page (lowercase)
        page_url: URL de la page (lowercase)
        
    Returns:
        bool: True si c'est un faux positif (checkpoint normal)
    """
    for indicator in FALSE_POSITIVE_INDICATORS:
        if indicator.lower() in page_content or indicator.lower() in page_url:
            return True
    return False


# =============================================================================
# ADVANCED STEALTH TECHNIQUES (Q1 2025)
# =============================================================================

# Script avancé pour masquer les signatures de fingerprinting
ADVANCED_ANTI_FINGERPRINT_SCRIPT = """
// Canvas fingerprint randomization
const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    const context = this.getContext('2d');
    if (context) {
        const imageData = context.getImageData(0, 0, this.width, this.height);
        for (let i = 0; i < imageData.data.length; i += 4) {
            imageData.data[i] += Math.floor(Math.random() * 2) - 1;
        }
        context.putImageData(imageData, 0, 0);
    }
    return originalToDataURL.apply(this, arguments);
};

// AudioContext fingerprint protection
const originalGetChannelData = AudioBuffer.prototype.getChannelData;
AudioBuffer.prototype.getChannelData = function() {
    const results = originalGetChannelData.apply(this, arguments);
    for (let i = 0; i < results.length; i++) {
        results[i] += 0.0000001 * (Math.random() - 0.5);
    }
    return results;
};

// Client Rect noise
const originalGetBoundingClientRect = Element.prototype.getBoundingClientRect;
Element.prototype.getBoundingClientRect = function() {
    const rect = originalGetBoundingClientRect.apply(this, arguments);
    return new DOMRect(
        rect.x + Math.random() * 0.0001,
        rect.y + Math.random() * 0.0001,
        rect.width + Math.random() * 0.0001,
        rect.height + Math.random() * 0.0001
    );
};

// Timezone consistent with locale
Date.prototype.getTimezoneOffset = function() {
    return -60; // CET (Paris)
};

// Screen properties (consistent with viewport)
Object.defineProperty(screen, 'colorDepth', { value: 24 });
Object.defineProperty(screen, 'pixelDepth', { value: 24 });

// Battery API (not charging = more natural)
if (navigator.getBattery) {
    navigator.getBattery = function() {
        return Promise.resolve({
            charging: false,
            chargingTime: Infinity,
            dischargingTime: 7200,
            level: 0.75 + Math.random() * 0.15,
        });
    };
}

// Connection API
if (navigator.connection) {
    Object.defineProperty(navigator.connection, 'rtt', { value: 50 + Math.floor(Math.random() * 50) });
    Object.defineProperty(navigator.connection, 'downlink', { value: 5 + Math.random() * 10 });
    Object.defineProperty(navigator.connection, 'effectiveType', { value: '4g' });
}

// Media devices (realistic set)
navigator.mediaDevices.enumerateDevices = function() {
    return Promise.resolve([
        { deviceId: '', groupId: '', kind: 'audioinput', label: '' },
        { deviceId: '', groupId: '', kind: 'videoinput', label: '' },
        { deviceId: '', groupId: '', kind: 'audiooutput', label: '' },
    ]);
};
"""


async def apply_advanced_stealth(page) -> None:
    """Applique les techniques de stealth avancées.
    
    Inclut le fingerprint randomization et autres protections.
    """
    if not stealth_enabled():
        return
    
    await page.add_init_script(ADVANCED_ANTI_FINGERPRINT_SCRIPT)


def get_session_fingerprint() -> dict:
    """Génère un fingerprint de session cohérent.
    
    Retourne les mêmes valeurs pour toute la session pour éviter
    les incohérences détectables.
    """
    import hashlib
    import time
    
    # Seed basé sur la date (change chaque jour)
    day_seed = int(time.time() // 86400)
    random.seed(day_seed)
    
    fingerprint = {
        "screen_width": random.choice([1920, 1366, 1536, 1440, 1680]),
        "screen_height": random.choice([1080, 768, 864, 900, 1050]),
        "color_depth": 24,
        "timezone_offset": -60,  # Paris
        "platform": random.choice(["Win32", "MacIntel"]),
        "hardware_concurrency": random.choice([4, 8, 12, 16]),
        "device_memory": random.choice([4, 8, 16]),
    }
    
    # Reset random seed
    random.seed()
    
    return fingerprint


# =============================================================================
# BEHAVIORAL STEALTH - Actions plus naturelles
# =============================================================================

def get_natural_scroll_amount() -> int:
    """Retourne un montant de scroll naturel (pas toujours identique)."""
    # Les humains ne scrollent pas exactement de la même quantité
    base = random.choice([300, 350, 400, 450, 500])
    variance = random.randint(-50, 50)
    return base + variance


def get_typing_speed() -> int:
    """Retourne un délai de frappe naturel en ms."""
    # Vitesse de frappe variable (50-150ms entre touches)
    return random.randint(50, 150)


async def simulate_natural_typing(page, selector: str, text: str) -> None:
    """Simule une frappe naturelle avec vitesse variable.
    
    Args:
        page: Instance Playwright Page
        selector: Sélecteur de l'élément
        text: Texte à taper
    """
    try:
        element = await page.query_selector(selector)
        if not element:
            return
        
        await element.click()
        await page.wait_for_timeout(random.randint(200, 500))
        
        for char in text:
            await page.keyboard.type(char, delay=get_typing_speed())
            
            # Parfois une micro-pause (réflexion)
            if random.random() < 0.05:
                await page.wait_for_timeout(random.randint(100, 400))
        
    except Exception:
        pass


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "stealth_enabled",
    "get_random_viewport",
    "get_random_user_agent",
    "get_stealth_context_options",
    "apply_stealth_scripts",
    "apply_advanced_stealth",
    "detect_restriction_page",
    "is_false_positive_checkpoint",
    "get_session_fingerprint",
    "get_natural_scroll_amount",
    "get_typing_speed",
    "simulate_natural_typing",
    "USER_AGENTS",
    "VIEWPORT_PRESETS",
    "RESTRICTION_INDICATORS",
    "FALSE_POSITIVE_INDICATORS",
    "ANTI_DETECTION_SCRIPT",
    "ADVANCED_ANTI_FINGERPRINT_SCRIPT",
]
