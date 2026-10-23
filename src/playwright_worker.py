import asyncio
import logging
import urllib.parse
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright

logger = logging.getLogger("VintedBot.PlaywrightWorker")

class PlaywrightCheckoutWorker:
    """Worker Playwright headless qui pré-crée la commande et capture l'URL de paiement finale."""

    def __init__(self, session_cookie: str = "", access_token: str = "", v_uid: str = "68815764", v_sid: str = "a9a7908d-1787428038", anon_id: str = "5854c12c-211e-4ada-aef9-ad9bd6b3985e"):
        self.session_cookie = urllib.parse.unquote(session_cookie or "")
        self.access_token = access_token or ""
        self.v_uid = str(v_uid or "68815764")
        self.v_sid = v_sid or "a9a7908d-1787428038"
        self.anon_id = anon_id or "5854c12c-211e-4ada-aef9-ad9bd6b3985e"

    async def get_direct_checkout_url(self, item_url: str) -> Optional[str]:
        """
        Charge la page de l'article avec la session de l'utilisateur, clique sur 'Acheter'
        et capture l'URL finale de paiement (https://www.vinted.fr/checkout?purchase_id=...&order_id=...).
        """
        if not item_url.startswith("http"):
            item_url = f"https://www.vinted.fr{item_url}"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1440, "height": 900}
                )

                if self.session_cookie:
                    cookies_to_set = []
                    for domain in [".vinted.fr", "www.vinted.fr"]:
                        cookies_to_set.extend([
                            {"name": "_vinted_fr_session", "value": self.session_cookie, "domain": domain, "path": "/"},
                            {"name": "access_token_web", "value": self.access_token, "domain": domain, "path": "/"},
                            {"name": "v_uid", "value": self.v_uid, "domain": domain, "path": "/"},
                            {"name": "v_sid", "value": self.v_sid, "domain": domain, "path": "/"},
                            {"name": "anon_id", "value": self.anon_id, "domain": domain, "path":"/"}
                        ])
                    await context.add_cookies(cookies_to_set)

                page = await context.new_page()
                logger.info(f"⚡ PlaywrightWorker : Chargement de l'annonce {item_url}...")
                await page.goto(item_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1.0)

                buy_button = page.locator('[data-testid="item-buy-button"]')
                if await buy_button.count() > 0:
                    logger.info("⚡ PlaywrightWorker : Bouton 'Acheter' trouvé, déclenchement du clic de pré-commande...")
                    try:
                        await buy_button.click(force=True, timeout=3000)
                    except Exception:
                        await page.evaluate("document.querySelector('[data-testid=\"item-buy-button\"]')?.click()")
                    
                    try:
                        await page.wait_for_url("**/checkout**", wait_until="domcontentloaded", timeout=8000)
                        checkout_url = page.url
                        logger.info(f"🎉 PlaywrightWorker : URL de paiement direct capturée avec succès : {checkout_url}")
                        await browser.close()
                        return checkout_url
                    except Exception:
                        if "checkout" in page.url:
                            checkout_url = page.url
                            logger.info(f"🎉 PlaywrightWorker : URL checkout capturée : {checkout_url}")
                            await browser.close()
                            return checkout_url
                        else:
                            logger.warning(f"PlaywrightWorker timeout navigation. URL actuelle: {page.url}")
                            await browser.close()
                            return None
                else:
                    logger.warning("PlaywrightWorker : Bouton [data-testid='item-buy-button'] introuvable sur la page.")
                    await browser.close()
                    return None
        except Exception as e:
            logger.error(f"Erreur lors de la capture Playwright du checkout URL: {e}")
            return None

    def fetch_checkout_url_sync(self, item_url: str) -> Optional[str]:
        """Version synchrone exécutable depuis le bot principal."""
        try:
            return asyncio.run(self.get_direct_checkout_url(item_url))
        except Exception as e:
            logger.error(f"Erreur Playwright sync execution: {e}")
            return None
