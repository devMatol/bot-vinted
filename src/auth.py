import os
import json
import logging
import time
from typing import Optional, Dict

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests

logger = logging.getLogger("VintedBot.Auth")

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
COOKIES_DIR = "cookies"

COUNTRY_SPECS = {
    "fr": {"domain": "vinted.fr", "lang": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7", "locale": "fr-FR"},
    "it": {"domain": "vinted.it", "lang": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7", "locale": "it-IT"},
    "de": {"domain": "vinted.de", "lang": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7", "locale": "de-DE"},
    "es": {"domain": "vinted.es", "lang": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7", "locale": "es-ES"},
    "be": {"domain": "vinted.be", "lang": "fr-BE,nl-BE,fr;q=0.9,nl;q=0.8,en;q=0.7", "locale": "fr-BE"},
    "nl": {"domain": "vinted.nl", "lang": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7", "locale": "nl-NL"},
    "pt": {"domain": "vinted.pt", "lang": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7", "locale": "pt-PT"},
    "at": {"domain": "vinted.at", "lang": "de-AT,de;q=0.9,en-US;q=0.8,en;q=0.7", "locale": "de-AT"}
}

def get_country_from_domain(domain: str) -> str:
    """Extrait le code pays depuis le domaine (ex: 'vinted.it' -> 'it')."""
    parts = domain.lower().split(".")
    if len(parts) >= 2:
        return parts[-1]
    return "fr"

class VintedSessionManager:
    """
    Gère la récupération et le renouvellement automatique des cookies de session Vinted
    avec auto-résolution Cloudflare par domaine (Phase 3.2).
    """

    def __init__(
        self,
        domain: str = "vinted.fr",
        session_cookie: Optional[str] = None,
        country: Optional[str] = None,
        proxy: Optional[str] = None
    ):
        self.domain = domain
        self.country = country or get_country_from_domain(domain)
        self.proxy = proxy
        spec = COUNTRY_SPECS.get(self.country, {"domain": domain, "lang": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7", "locale": "fr-FR"})
        self.accept_language = spec.get("lang")
        self.locale = spec.get("locale")

        os.makedirs(COOKIES_DIR, exist_ok=True)
        if self.proxy:
            import hashlib
            p_hash = hashlib.md5(self.proxy.encode("utf-8")).hexdigest()[:8]
            self.cookies_file = os.path.join(COOKIES_DIR, f"vinted_{self.country}_{p_hash}.json")
        else:
            self.cookies_file = os.path.join(COOKIES_DIR, f"vinted_{self.country}.json")

        # Migration douce : si l'ancien vinted_cookies.json existe et qu'on est en fr
        if self.country == "fr" and not self.proxy and not os.path.exists(self.cookies_file) and os.path.exists("vinted_cookies.json"):
            try:
                import shutil
                shutil.copy("vinted_cookies.json", self.cookies_file)
            except Exception:
                pass

        self.base_url = f"https://www.{domain}"
        self.session: Optional[curl_requests.Session] = None
        self.last_cookie_fetch_time: float = 0
        self.cookie_ttl: int = 7200  # Renouveler toutes les 2h
        self.session_cookie = session_cookie
        self._last_fail_time: float = 0
        self.user_agent = DEFAULT_USER_AGENT

    def get_session(self, force_refresh: bool = False) -> curl_requests.Session:
        """Retourne une session active avec des cookies Vinted valides pour ce domaine."""
        now = time.time()
        if (now - self._last_fail_time) < 15 and self.session is not None and not force_refresh:
            return self.session

        if self.session is None or force_refresh or (now - self.last_cookie_fetch_time > self.cookie_ttl):
            self._fetch_fresh_cookies()

        return self.session

    def _load_saved_cookies(self, session: curl_requests.Session) -> bool:
        """Tente de charger des cookies valides récemment sauvegardés pour ce domaine."""
        if not os.path.exists(self.cookies_file):
            return False

        try:
            mtime = os.path.getmtime(self.cookies_file)
            if time.time() - mtime < 7200:
                with open(self.cookies_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cookies = data.get("cookies", {})
                ua = data.get("user_agent", self.user_agent)
                if cookies:
                    self.user_agent = ua
                    session.headers["User-Agent"] = ua
                    for k, v in cookies.items():
                        session.cookies.set(k, v, domain=f".{self.domain}")
                    logger.debug(f"Cookies Vinted ({self.country}) chargés depuis {self.cookies_file} ({len(cookies)} cookies).")
                    return True
        except Exception as e:
            logger.debug(f"Erreur chargement cookies sauvegardés ({self.country}): {e}")

        return False

    def _solve_cf_and_load_cookies(self, session: curl_requests.Session) -> bool:
        """Lance Chromium en mode réel pendant quelques secondes pour résoudre le défi Cloudflare."""
        try:
            from playwright.sync_api import sync_playwright
            logger.info(f"🛡️ Actualisation automatique de la session Vinted [{self.domain}] via Cloudflare...")
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"]
                )
                context = browser.new_context(
                    locale=self.locale,
                    viewport={"width": 1280, "height": 800}
                )
                page = context.new_page()
                page.goto(self.base_url, wait_until="domcontentloaded", timeout=20000)

                for _ in range(12):
                    time.sleep(0.5)
                    title = page.title()
                    if "Vinted" in title and "Please wait" not in title and "moment" not in title and "Session refresh" not in title:
                        break

                captured_cookies = context.cookies()
                captured_ua = page.evaluate("navigator.userAgent")
                browser.close()

            if captured_cookies:
                cookie_dict = {}
                self.user_agent = captured_ua
                session.headers["User-Agent"] = captured_ua
                for c in captured_cookies:
                    domain_val = c.get("domain", f".{self.domain}")
                    session.cookies.set(c["name"], c["value"], domain=domain_val)
                    cookie_dict[c["name"]] = c["value"]

                with open(self.cookies_file, "w", encoding="utf-8") as f:
                    json.dump({"cookies": cookie_dict, "user_agent": captured_ua, "timestamp": time.time()}, f, indent=2)

                logger.info(f"✅ Session Vinted [{self.domain}] renouvelée avec succès ({len(cookie_dict)} cookies) !")
                return True
        except Exception as e:
            logger.warning(f"Impossible de résoudre automatiquement le défi Cloudflare pour {self.domain}: {e}")

        return False

    def _fetch_fresh_cookies(self):
        """Effectue une requête sur Vinted et actualise les cookies avec auto-résolution Cloudflare si nécessaire."""
        try:
            if hasattr(curl_requests, "Session"):
                try:
                    session = curl_requests.Session(impersonate="chrome120")
                except TypeError:
                    session = curl_requests.Session()
            else:
                session = curl_requests.Session()

            if self.proxy:
                session.proxies = {"http": self.proxy, "https": self.proxy}

            session.headers.update({
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": self.accept_language,
                "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            })

            # Tenter de charger les cookies en cache
            self._load_saved_cookies(session)

            if self.session_cookie:
                cookie_name = f"_vinted_{self.country}_session"
                session.cookies.set(cookie_name, self.session_cookie, domain=f".{self.domain}")

            # Tester la validité de la session sur le catalogue
            test_url = f"{self.base_url}/catalog?search_text=vintage"
            res = session.get(test_url, timeout=12)

            if res.status_code == 200 and "Session refresh" not in res.text and "challenge-platform" not in res.text:
                self.session = session
                self.last_cookie_fetch_time = time.time()
                self._last_fail_time = 0
                logger.debug(f"Session Vinted [{self.domain}] validée (HTTP 200).")
                return

            if res.status_code in (401, 403) or "Session refresh" in res.text or "challenge-platform" in res.text:
                if self._solve_cf_and_load_cookies(session):
                    self.session = session
                    self.last_cookie_fetch_time = time.time()
                    self._last_fail_time = 0
                    return

            logger.warning(f"⚠️ Pause réseau Vinted/Cloudflare [{self.domain}] ({res.status_code}). Attente temporaire...")
            self._last_fail_time = time.time()
            if self.session is None:
                self.session = session

        except Exception as e:
            logger.warning(f"⚠️ Pause réseau lors du renouvellement des cookies pour {self.domain}: {e}")
            self._last_fail_time = time.time()
            if self.session is None:
                self.session = curl_requests.Session()
