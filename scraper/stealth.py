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

# User agents réalistes (rotation) - Updated January 2026
# Keep these updated! Old browser versions are a major detection signal.
USER_AGENTS = [
    # Chrome 131 (current stable - January 2026)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Chrome 130 (previous stable)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Edge 131 (mirrors Chrome)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    # Firefox 133 (current stable)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Safari 17.2 (macOS Sonoma)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
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


# =============================================================================
# CONSISTENT BROWSER FINGERPRINT PROFILES
# =============================================================================
# LinkedIn correlates user-agent, timezone, locale, and screen resolution.
# Mismatched combinations are a detection signal.

FINGERPRINT_PROFILES = [
    # French corporate user (most common for this use case)
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
        "viewport": {"width": 1920, "height": 1080},
        "geolocation": {"latitude": 48.8566, "longitude": 2.3522},  # Paris
        "accept_language": "fr-FR,fr;q=0.9,en;q=0.8",
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
        "viewport": {"width": 1366, "height": 768},
        "geolocation": {"latitude": 45.7640, "longitude": 4.8357},  # Lyon
        "accept_language": "fr-FR,fr;q=0.9",
    },
    # French Mac user
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
        "viewport": {"width": 1440, "height": 900},
        "geolocation": {"latitude": 48.8566, "longitude": 2.3522},
        "accept_language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    },
    # French Firefox user
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "locale": "fr-FR",
        "timezone_id": "Europe/Paris",
        "viewport": {"width": 1536, "height": 864},
        "geolocation": {"latitude": 43.6047, "longitude": 1.4442},  # Toulouse
        "accept_language": "fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3",
    },
]

# Cache the selected profile for the session to maintain consistency
_session_fingerprint: dict[str, Any] | None = None

# Path for persisting fingerprint between app restarts (reduces LinkedIn security emails)
_FINGERPRINT_FILE: str | None = None

# =============================================================================
# DEFAULT PERSISTENT FINGERPRINT - Matches a real Chrome browser on Windows 10
# =============================================================================
# This fingerprint should NEVER change to avoid LinkedIn security emails.
# It mimics a real Chrome browser on Windows 10 in France.
DEFAULT_PERSISTENT_FINGERPRINT = {
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "locale": "fr-FR",
    "timezone_id": "Europe/Paris",
    "viewport": {"width": 1920, "height": 1080},
    "geolocation": {"latitude": 48.8566, "longitude": 2.3522},  # Paris
    "accept_language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "device_scale_factor": 1.0,
    "color_depth": 24,
    "hardware_concurrency": 8,
    "device_memory": 8,
    "platform": "Win32",
    "screen_width": 1920,
    "screen_height": 1080,
    # Sec-CH-UA headers for Chrome 131 on Windows
    "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec_ch_ua_mobile": "?0",
    "sec_ch_ua_platform": '"Windows"',
}


def _get_fingerprint_path() -> str | None:
    """Get the path to the fingerprint persistence file.
    
    Uses the same directory as STORAGE_STATE for consistency.
    """
    global _FINGERPRINT_FILE
    if _FINGERPRINT_FILE is not None:
        return _FINGERPRINT_FILE
    
    # Try to get from environment (set by desktop launcher)
    storage_state = os.environ.get("STORAGE_STATE", "")
    if storage_state:
        from pathlib import Path
        fp_path = Path(storage_state).parent / "fingerprint.json"
        _FINGERPRINT_FILE = str(fp_path)
        return _FINGERPRINT_FILE
    
    # Fallback: use AppData/Local/TitanScraper on Windows
    if os.name == "nt":
        appdata = os.environ.get("LOCALAPPDATA", "")
        if appdata:
            from pathlib import Path
            fp_path = Path(appdata) / "TitanScraper" / "fingerprint.json"
            _FINGERPRINT_FILE = str(fp_path)
            return _FINGERPRINT_FILE
    
    return None


def _load_persisted_fingerprint() -> dict[str, Any] | None:
    """Load fingerprint from disk if it exists and is valid."""
    import json
    from pathlib import Path
    
    fp_path = _get_fingerprint_path()
    if not fp_path:
        return None
    
    try:
        path = Path(fp_path)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            # Validate it has required fields
            if all(k in data for k in ("user_agent", "locale", "timezone_id", "viewport")):
                return data
    except Exception:
        pass
    return None


def _save_fingerprint(fp: dict[str, Any]) -> None:
    """Save fingerprint to disk for persistence across app restarts."""
    import json
    from pathlib import Path
    
    fp_path = _get_fingerprint_path()
    if not fp_path:
        return
    
    try:
        path = Path(fp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_consistent_fingerprint() -> dict[str, Any]:
    """Get a consistent fingerprint profile for the entire session.
    
    The fingerprint is persisted to disk to maintain the same browser identity
    across app restarts. This prevents LinkedIn from detecting a "new device"
    and sending security notification emails.
    
    IMPORTANT: We now use a FIXED fingerprint (DEFAULT_PERSISTENT_FINGERPRINT)
    that matches a real Chrome browser. This eliminates the "new device" emails
    because the browser signature never changes.
    
    Returns:
        dict: Fingerprint profile with user_agent, locale, timezone, etc.
    """
    global _session_fingerprint
    if _session_fingerprint is None:
        # Try to load persisted fingerprint first
        _session_fingerprint = _load_persisted_fingerprint()
        
        if _session_fingerprint is None:
            # Use the DEFAULT persistent fingerprint - DO NOT randomize!
            # This is critical to avoid LinkedIn "new device" security emails.
            _session_fingerprint = DEFAULT_PERSISTENT_FINGERPRINT.copy()
            _save_fingerprint(_session_fingerprint)
        else:
            # Validate loaded fingerprint has all required fields from DEFAULT
            # If any field is missing, merge with DEFAULT to ensure consistency
            for key, value in DEFAULT_PERSISTENT_FINGERPRINT.items():
                if key not in _session_fingerprint:
                    _session_fingerprint[key] = value
    
    return _session_fingerprint


def reset_session_fingerprint(regenerate: bool = False) -> None:
    """Reset the session fingerprint.
    
    Args:
        regenerate: If True, also delete the persisted fingerprint so a new
                    one is generated. If False, just clear in-memory cache.
    """
    global _session_fingerprint
    _session_fingerprint = None
    
    if regenerate:
        from pathlib import Path
        fp_path = _get_fingerprint_path()
        if fp_path:
            try:
                Path(fp_path).unlink(missing_ok=True)
            except Exception:
                pass


def get_stealth_context_options() -> dict[str, Any]:
    """Retourne les options de contexte browser pour le mode stealth.
    
    Ces options sont appliquées lors de la création du contexte Playwright.
    Elles utilisent un profil fingerprint cohérent pour éviter la détection:
    - Viewport, user agent, locale, timezone sont corrélés
    - Le même profil est utilisé pendant toute la session
    
    Returns:
        dict: Options de contexte Playwright
    """
    if not stealth_enabled():
        return {}
    
    # Use consistent fingerprint for the session
    fp = get_consistent_fingerprint()
    
    return {
        "viewport": fp["viewport"],
        "user_agent": fp["user_agent"],
        "locale": fp["locale"],
        "timezone_id": fp["timezone_id"],
        "geolocation": fp["geolocation"],
        "permissions": ["geolocation"],
        "color_scheme": "light",
        "device_scale_factor": fp.get("device_scale_factor", 1.0),  # Use persisted value, not random
        "has_touch": False,
        "is_mobile": False,
        "java_script_enabled": True,
        # Extra headers for consistency - matches real Chrome browser exactly
        # These headers are critical to avoid LinkedIn detecting a "new device"
        "extra_http_headers": {
            "Accept-Language": fp.get("accept_language", "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Cache-Control": "max-age=0",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            # Chrome Client Hints - critical for matching real Chrome browser
            "Sec-CH-UA": fp.get("sec_ch_ua", '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'),
            "Sec-CH-UA-Mobile": fp.get("sec_ch_ua_mobile", "?0"),
            "Sec-CH-UA-Platform": fp.get("sec_ch_ua_platform", '"Windows"'),
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        },
    }


# Script d'initialisation anti-détection
# These values are hardcoded to match DEFAULT_PERSISTENT_FINGERPRINT exactly
ANTI_DETECTION_SCRIPT = """
// Masquer la propriété webdriver - CRITICAL for Playwright detection
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Override navigator properties to match real Chrome on Windows
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32'
});

Object.defineProperty(navigator, 'vendor', {
    get: () => 'Google Inc.'
});

Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8
});

Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8
});

Object.defineProperty(navigator, 'maxTouchPoints', {
    get: () => 0
});

// Masquer les plugins Playwright - simulate real Chrome plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2 },
        ];
        plugins.item = (i) => plugins[i];
        plugins.namedItem = (name) => plugins.find(p => p.name === name);
        plugins.refresh = () => {};
        return plugins;
    }
});

// Masquer les langues - must match Accept-Language header
Object.defineProperty(navigator, 'languages', {
    get: () => ['fr-FR', 'fr', 'en-US', 'en']
});

Object.defineProperty(navigator, 'language', {
    get: () => 'fr-FR'
});

// Chrome runtime (évite la détection "headless") - full Chrome object simulation
window.chrome = {
    runtime: {
        id: undefined,
        connect: function() {},
        sendMessage: function() {},
        onConnect: { addListener: function() {} },
        onMessage: { addListener: function() {} }
    },
    loadTimes: function() { 
        return {
            requestTime: Date.now() / 1000 - 0.1,
            startLoadTime: Date.now() / 1000 - 0.05,
            commitLoadTime: Date.now() / 1000,
            finishDocumentLoadTime: Date.now() / 1000 + 0.1,
            finishLoadTime: Date.now() / 1000 + 0.2,
            firstPaintTime: Date.now() / 1000 + 0.05,
            firstPaintAfterLoadTime: 0,
            navigationType: 'Other'
        };
    },
    csi: function() { 
        return { 
            onloadT: Date.now(), 
            pageT: Date.now() - 1000, 
            startE: Date.now() - 2000, 
            tran: 15 
        }; 
    },
    app: {
        isInstalled: false,
        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
    }
};

// Permissions API override - simulate real permissions behavior
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Console.debug leak prevention
window.console.debug = () => {};

// WebGL vendor/renderer masking - use common Intel GPU to appear normal
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) {  // UNMASKED_VENDOR_WEBGL
        return 'Intel Inc.';
    }
    if (parameter === 37446) {  // UNMASKED_RENDERER_WEBGL
        return 'Intel(R) UHD Graphics 630';
    }
    return getParameter.call(this, parameter);
};

// WebGL2 support
if (typeof WebGL2RenderingContext !== 'undefined') {
    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) {
            return 'Intel Inc.';
        }
        if (parameter === 37446) {
            return 'Intel(R) UHD Graphics 630';
        }
        return getParameter2.call(this, parameter);
    };
}

// Screen properties - must match viewport settings
Object.defineProperty(screen, 'width', { get: () => 1920 });
Object.defineProperty(screen, 'height', { get: () => 1080 });
Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
Object.defineProperty(screen, 'availHeight', { get: () => 1040 });  // Taskbar offset
Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });

// Connection API - simulate typical broadband connection
if (navigator.connection) {
    Object.defineProperty(navigator.connection, 'effectiveType', { get: () => '4g' });
    Object.defineProperty(navigator.connection, 'rtt', { get: () => 50 });
    Object.defineProperty(navigator.connection, 'downlink', { get: () => 10 });
    Object.defineProperty(navigator.connection, 'saveData', { get: () => false });
}

// Battery API - simulate plugged-in laptop
if (navigator.getBattery) {
    navigator.getBattery = () => Promise.resolve({
        charging: true,
        chargingTime: 0,
        dischargingTime: Infinity,
        level: 1.0,
        addEventListener: () => {},
        removeEventListener: () => {}
    });
}
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

// Timezone consistent with locale (dynamique selon période été/hiver)
const _originalGetTimezoneOffset = Date.prototype.getTimezoneOffset;
Date.prototype.getTimezoneOffset = function() {
    // Retourne le vrai offset système pour cohérence avec l'heure locale
    return _originalGetTimezoneOffset.call(this);
};

// Screen properties (consistent with viewport) - ALREADY SET IN ANTI_DETECTION_SCRIPT
// Removed to avoid duplicate property definitions
// Object.defineProperty(screen, 'colorDepth', { value: 24 });
// Object.defineProperty(screen, 'pixelDepth', { value: 24 });

// Battery API - ALREADY SET IN ANTI_DETECTION_SCRIPT with consistent values
// Removed to avoid duplicate definitions

// Connection API - ALREADY SET IN ANTI_DETECTION_SCRIPT with consistent values  
// Removed to avoid duplicate definitions

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
    """Retourne le fingerprint de session persistant.
    
    IMPORTANT: Cette fonction retourne maintenant le fingerprint PERSISTANT
    au lieu de générer un nouveau fingerprint chaque jour. Cela évite que
    LinkedIn détecte un "nouvel appareil" et envoie des emails de sécurité.
    
    Returns:
        dict: Fingerprint cohérent avec DEFAULT_PERSISTENT_FINGERPRINT
    """
    fp = get_consistent_fingerprint()
    
    return {
        "screen_width": fp.get("screen_width", 1920),
        "screen_height": fp.get("screen_height", 1080),
        "color_depth": fp.get("color_depth", 24),
        "timezone_offset": -60,  # Paris (Europe/Paris = UTC+1 = -60 minutes)
        "platform": fp.get("platform", "Win32"),
        "hardware_concurrency": fp.get("hardware_concurrency", 8),
        "device_memory": fp.get("device_memory", 8),
    }


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
    "get_consistent_fingerprint",
    "reset_session_fingerprint",
    "get_natural_scroll_amount",
    "get_typing_speed",
    "simulate_natural_typing",
    "DEFAULT_PERSISTENT_FINGERPRINT",
    "USER_AGENTS",
    "VIEWPORT_PRESETS",
    "RESTRICTION_INDICATORS",
    "FALSE_POSITIVE_INDICATORS",
    "ANTI_DETECTION_SCRIPT",
    "ADVANCED_ANTI_FINGERPRINT_SCRIPT",
]
