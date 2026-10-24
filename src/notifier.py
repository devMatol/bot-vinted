import logging
import requests
import html
import json
from typing import Dict, Any, Optional, List

logger = logging.getLogger("VintedBot.Notifier")

COUNTRY_FLAGS = {
    "fr": "🇫🇷",
    "it": "🇮🇹",
    "de": "🇩🇪",
    "es": "🇪🇸",
    "be": "🇧🇪",
    "nl": "🇳🇱",
    "pt": "🇵🇹",
    "at": "🇦🇹"
}

def _clean_status(raw_status: str) -> str:
    """Normalise les libellés de condition Vinted multilingues en français lisible."""
    if not raw_status:
        return ""
    s_clean = raw_status.lower().replace(" ", "").replace("_", "").replace("-", "")
    translations = {
        "neufavecetiquette": "Neuf avec étiquette",
        "neufsansetiquette": "Neuf sans étiquette",
        "tresbonetat": "Très bon état",
        "bonetat": "Bon état",
        "satisfaisant": "Satisfaisant",
        "newwithtags": "Neuf avec étiquette",
        "newwithouttags": "Neuf sans étiquette",
        "verygood": "Très bon état",
        "verygoodcondition": "Très bon état",
        "good": "Bon état",
        "goodcondition": "Bon état",
        "nuovoconcartellino": "Neuf avec étiquette",
        "nuovasenzacartellino": "Neuf sans étiquette",
        "ottimecondizioni": "Très bon état",
        "ottimo": "Très bon état",
        "buonecondizioni": "Bon état",
        "buono": "Bon état",
        "nuevoconetiquetas": "Neuf avec étiquette",
        "nuevosinetiquetas": "Neuf sans étiquette",
        "muybueno": "Très bon état",
        "bueno": "Bon état"
    }
    return translations.get(s_clean, raw_status)


class TelegramNotifier:
    """Gestionnaire des notifications envoyées sur Telegram avec vision IA, drapeaux pays et boutons d'évaluation."""

    def __init__(self, telegram_config: Dict[str, Any], session_config: Optional[Dict[str, Any]] = None):
        self.config = telegram_config
        self.enabled = telegram_config.get("enabled", False)
        self.bot_token = telegram_config.get("bot_token", "")
        self.chat_id = telegram_config.get("chat_id", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.session_config = session_config or {}

    def is_configured(self) -> bool:
        """Vérifie si les identifiants Telegram sont bien remplis."""
        return bool(
            self.enabled 
            and self.bot_token 
            and self.bot_token != "VOTRE_BOT_TOKEN_TELEGRAM_ICI"
            and self.chat_id 
            and self.chat_id != "VOTRE_CHAT_ID_TELEGRAM_ICI"
        )

    def send_deal_alert(
        self,
        item: Dict[str, Any],
        search_name: str,
        domain: str = "vinted.fr",
        vision_result: Optional[Dict[str, Any]] = None,
        country: str = "fr",
        shipping_cost: float = 0.0,
        margin: Optional[float] = None,
        resale_estimate: Optional[float] = None,
        ai_pending: bool = False
    ) -> Optional[int]:
        """
        Mets en forme et envoie l'alerte d'une bonne affaire sur Telegram avec :
        - Drapeau du pays (Phase 3.8)
        - Prix, prix port compris et domaine (Phase 3.8)
        - Revente estimée et marge estimée (ou 'Analyse IA en cours' si ai_pending=True)
        - URLs pointant sur le bon domaine
        - Boutons d'évaluation interactifs
        Retourne le message_id Telegram envoyé (ou None si échec).
        """
        if not self.is_configured():
            logger.info(f"[MODE DEMO / TELEGRAM DESACTIVE] Alerte détectée : '{item.get('title')}' à {self._extract_price(item)}€")
            return None

        item_id = item.get("id")
        title = html.escape(str(item.get("title", "Sans titre")))
        search_name_esc = html.escape(str(search_name))
        
        # Formatage prix et drapeau pays (Phase 3.8)
        raw_price_str = self._extract_price(item)
        try:
            p_val = float(raw_price_str)
        except ValueError:
            p_val = 0.0

        flag = COUNTRY_FLAGS.get(country.lower(), "🌍")
        if shipping_cost > 0:
            total_cost = p_val + shipping_cost
            price_formatted = f"<b>{p_val:.2f} €</b> <i>(Total port inclus : <b>{total_cost:.2f} €</b> {flag})</i>"
        else:
            price_formatted = f"<b>{p_val:.2f} €</b> {flag}"

        # Ligne d'estimation financière (Revente estimée et marge nette)
        financial_line = ""
        if ai_pending:
            financial_line = "⏳ <b>Analyse IA en cours...</b> <i>(évaluation revente & état)</i>\n"
        else:
            resale_val = resale_estimate
            if resale_val is None and vision_result:
                try:
                    resale_val = float(vision_result.get("resale_estimate_eur", 0.0))
                except (ValueError, TypeError):
                    resale_val = None

            margin_val = margin
            if resale_val is not None and resale_val > 0:
                if margin_val is not None:
                    financial_line = (
                        f"📈 <b>Revente estimée :</b> ~{resale_val:.2f} €\n"
                        f"💵 <b>Marge estimée :</b> <b>+{margin_val:.2f} €</b>\n"
                    )
                else:
                    financial_line = f"📈 <b>Revente estimée :</b> ~{resale_val:.2f} €\n"

        brand = html.escape(str(item.get("brand_title") or "Non spécifié"))
        size = html.escape(str(item.get("size_title") or "Non spécifié"))
        status = html.escape(str(item.get("status") or "Non spécifié"))
        
        user_info = item.get("user") or {}
        seller_login = html.escape(str(user_info.get("login", "Inconnu")))
        feedback_rep = user_info.get("feedback_reputation")
        if feedback_rep is not None:
            rating_stars = f"⭐ {float(feedback_rep) * 5.0:.1f}/5"
        else:
            rating_stars = "Pas d'évaluations"

        # URLs d'accès direct sur le bon domaine (Phase 3.4)
        raw_item_url = str(item.get("url") or "")
        if raw_item_url.startswith("http"):
            direct_url = raw_item_url
        else:
            direct_url = f"https://www.{domain}/items/{item_id}"

        # Block d'analyse visuelle par l'IA Vision
        vision_text = ""
        vision_short = ""
        photos = item.get("photos") or []
        photos_count = len(photos)
        
        if vision_result:
            score = vision_result.get("score", 80)
            verdict = vision_result.get("verdict", "NEEDS_REVIEW")
            summary = html.escape(str(vision_result.get("summary", ""))[:180])
            condition = html.escape(str(vision_result.get("condition_assessment", ""))[:110])
            defects = vision_result.get("defects_detected", [])
            
            badge_icon = "🟢 PÉPITE CERTIFIÉE" if score >= 85 else ("🟡 APPRÉCIATION" if score >= 60 else "🔴 REJETÉ")
            vision_text = (
                f"\n🤖 <b>IA VISION SCORE :</b> {score}/100 ({badge_icon})\n"
                f"📸 <b>Inspection :</b> {photos_count} photo(s) analysées\n"
                f"🔍 <b>Analyse IA :</b> <i>{summary}</i>\n"
            )
            short_summary = html.escape(str(vision_result.get("summary", ""))[:220])
            vision_short = f"\n🤖 <b>IA :</b> {score}/100 ({badge_icon})\n🔍 <i>{short_summary}</i>\n"
            if condition:
                vision_text += f"🧵 <b>État :</b> <i>{condition}</i>\n"
            if defects and len(defects) > 0:
                defects_esc = html.escape(", ".join(defects)[:100])
                vision_text += f"⚠️ <b>Anomalies :</b> <i>{defects_esc}</i>\n"

        # Description du vendeur (snippet compact)
        desc_snippet = ""
        raw_desc = item.get("description", "").strip()
        if raw_desc:
            clean_desc = html.escape(raw_desc[:90] + ("..." if len(raw_desc) > 90 else ""))
            desc_snippet = f"📝 <b>Description :</b> <i>\"{clean_desc}\"</i>\n"

        # Photo principale
        photo_url = None
        if photos and len(photos) > 0:
            photo_url = photos[0].get("url") or photos[0].get("full_size_url")

        caption = (
            f"⚡ <b>ALERTE PÉPITE VINTED {flag} !</b>\n\n"
            f"📌 <b>Recherche :</b> {search_name_esc}\n"
            f"🏷️ <b>Titre :</b> {title}\n"
            f"💰 <b>Prix :</b> {price_formatted}\n"
            f"{financial_line}"
            f"🌐 <b>Domaine :</b> <code>{domain}</code>\n"
            f"📏 <b>Taille :</b> {size}\n"
            f"🏢 <b>Marque :</b> {brand}\n"
            f"✨ <b>État Vinted :</b> {status}\n"
            f"👤 <b>Vendeur :</b> {seller_login} ({rating_stars})\n"
            f"{desc_snippet}"
            f"{vision_text}\n"
            f"🔗 <a href='{direct_url}'>👉 ⚡ Cliquer ici pour voir l'article</a>"
        )

        # Sécurité stricte Telegram sendPhoto (limite 1024 caractères)
        if len(caption) > 1000:
            caption = (
                f"⚡ <b>ALERTE PÉPITE VINTED {flag} !</b>\n\n"
                f"📌 <b>Recherche :</b> {search_name_esc}\n"
                f"🏷️ <b>Titre :</b> {title}\n"
                f"💰 <b>Prix :</b> {price_formatted} | 🏢 {brand} | 🌐 {domain}\n"
                f"{financial_line}"
                f"{vision_short}\n"
                f"🔗 <a href='{direct_url}'>👉 ⚡ Cliquer ici pour voir l'article</a>"
            )

        # Boutons interactifs : Bouton direct vers l'application Vinted + boutons d'évaluation
        reply_markup = json.dumps({
            "inline_keyboard": [
                [
                    {"text": "⚡ OUVRIR DANS L'APPLI VINTED 🛍️", "url": direct_url}
                ],
                [
                    {"text": "🎯 🟢 MUST BUY", "callback_data": f"fb:must_buy:{item_id}"},
                    {"text": "🤔 🟡 AVIS MAMA", "callback_data": f"fb:wife_opinion:{item_id}"},
                    {"text": "❌ 🔴 REJET", "callback_data": f"fb:reject:{item_id}"}
                ],
                [
                    {"text": "🛡️ Vérifier Authenticité (Legit Check) 🔍", "callback_data": f"fb:check_auth:{item_id}"}
                ]
            ]
        })

        try:
            if photo_url:
                response = requests.post(
                    f"{self.base_url}/sendPhoto",
                    data={
                        "chat_id": self.chat_id,
                        "photo": photo_url,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup
                    },
                    timeout=10
                )
                if response.status_code == 400 and "caption is too long" in response.text:
                    fallback_caption = f"⚡ <b>{title}</b> ({price_formatted})\n🔗 <a href='{direct_url}'>👉 Voir l'article</a>"
                    response = requests.post(
                        f"{self.base_url}/sendPhoto",
                        data={
                            "chat_id": self.chat_id,
                            "photo": photo_url,
                            "caption": fallback_caption,
                            "parse_mode": "HTML",
                            "reply_markup": reply_markup
                        },
                        timeout=10
                    )
            else:
                response = requests.post(
                    f"{self.base_url}/sendMessage",
                    data={
                        "chat_id": self.chat_id,
                        "text": caption,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                        "reply_markup": reply_markup
                    },
                    timeout=10
                )

            if response.status_code == 200:
                logger.info(f"Notification Telegram envoyée pour l'article ID {item_id} ({country.upper()})")
                data = response.json()
                msg_id = data.get("result", {}).get("message_id")
                return msg_id
            else:
                logger.error(f"Erreur Telegram API ({response.status_code}): {response.text}")
                return None
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de la notification Telegram: {e}")
            return None

    def send_v2_deal_alert(
        self,
        item: Dict[str, Any],
        decision_res: Any,
        comparables: List[Dict[str, Any]],
        search_name: str,
        domain: str = "vinted.fr",
        country: str = "fr",
        shipping_cost: float = 0.0,
        final_check_notes: Optional[str] = None,
        taste_score: Optional[float] = None,
        favourite_matches: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[int]:
        """
        Envoie l'alerte v2 Telegram selon le cahier des charges Lot 8 :
        photo, titre, prix + coût total, revente retenue et marge, score final et niveau,
        catégorie, 3 comparables vendus, 2 raisons principales, lien, boutons.
        """
        if not self.is_configured():
            logger.info(f"[MODE DEMO / TELEGRAM DESACTIVE] Alerte v2 : '{item.get('title')}' ({decision_res.price}€ -> Marge +{decision_res.margin}€)")
            return None

        item_id = str(item.get("id") or item.get("item_id") or "")
        title = html.escape(str(item.get("title", "Sans titre")))
        flag = COUNTRY_FLAGS.get(country.lower(), "🌍")

        tier_icon = "🟢 À ACHETER"
        header = f"{tier_icon} VINTED {flag}"

        # URLs d'accès direct
        raw_item_url = str(item.get("url") or "")
        direct_url = raw_item_url if raw_item_url.startswith("http") else f"https://www.{domain}/items/{item_id}"

        # 3 Comparables vendus boutique
        comp_lines = []
        for c in comparables[:3]:
            c_title = html.escape(str(c.get("title", ""))[:28])
            c_price = float(c.get("sold_price", 0.0))
            c_sim = float(c.get("similarity", 0.0)) * 100.0
            comp_lines.append(f"• {c_title} — <b>{c_price:.0f} €</b> <i>({c_sim:.0f}%)</i>")
        comp_block = "\n".join(comp_lines) if comp_lines else "• Historique boutique en cours"

        # 2 Raisons principales
        reasons_list = [r for r in decision_res.reasons if not r.startswith("🟢") and not r.startswith("🟡")]
        if not reasons_list:
            reasons_list = [f"Marge nette de +{decision_res.margin:.2f} €", f"Multiple de rentabilité {decision_res.multiple:.1f}x"]
        reason_lines = [f"• {html.escape(r)}" for r in reasons_list[:2]]
        reasons_block = "\n".join(reason_lines)

        cat_str = html.escape(str(decision_res.details.get("category") or item.get("category_normalized") or "Vêtement"))

        # Affichage Goût Rita (uniquement si activé dans la configuration)
        taste_active = bool(self.config.get("taste_filter_enabled", False))
        taste_val = taste_score if taste_score is not None else decision_res.details.get("taste_score")
        taste_block = ""
        if taste_active and taste_val is not None:
            taste_block = f"👗 <b>Goût Rita :</b> <b>{taste_val * 100:.0f} %</b>\n"
            if favourite_matches:
                fav_lines = []
                for fm in favourite_matches[:2]:
                    f_title = html.escape(str(fm.get("title", ""))[:25])
                    f_price = float(fm.get("price", 0.0))
                    f_sim = float(fm.get("similarity", 0.0)) * 100.0
                    fav_lines.append(f"  • {f_title} ({f_price:.0f} €) <i>({f_sim:.0f}%)</i>")
                if fav_lines:
                    taste_block += f"❤️ <b>Favoris proches :</b>\n" + "\n".join(fav_lines) + "\n"

        scenarios = decision_res.details.get("scenarios") or {}
        ai_prod_name = decision_res.details.get("ai_product_name")
        if ai_prod_name and decision_res.details.get("ai_resale_min"):
            revente_cible = float(decision_res.revente_retenue / 0.90)
        else:
            revente_cible = float(scenarios.get("revente_cible") or decision_res.revente_retenue)
        m_flash = float(scenarios.get("margin_flash") or (decision_res.margin * 0.7))
        m_opt = float(scenarios.get("margin_opt") or (decision_res.margin * 1.3))

        # 1. Marque (renseignée ou détectée par l'IA)
        raw_brand = str(item.get("brand_title") or item.get("brand") or "").strip()
        resale_data = decision_res.details.get("resale") or {}
        detected_brand = str(resale_data.get("brand_canonical") or "").strip()

        if raw_brand and detected_brand and raw_brand.lower() == detected_brand.lower():
            brand_display = f"<b>{html.escape(raw_brand)}</b>"
        elif raw_brand and detected_brand and detected_brand != "Sans marque":
            brand_display = f"<b>{html.escape(raw_brand)}</b> <i>(détectée IA : {html.escape(detected_brand)})</i>"
        elif raw_brand:
            brand_display = f"<b>{html.escape(raw_brand)}</b>"
        elif detected_brand and detected_brand != "Sans marque":
            brand_display = f"<b>{html.escape(detected_brand)}</b> <i>(détectée par l'IA 🤖)</i>"
        else:
            brand_display = "<i>Sans marque spécifique</i>"

        # 2. Prix avec frais + prix normal
        price_line = f"💰 <b>Prix article :</b> {decision_res.price:.2f} € | <b>Total avec frais :</b> <b>{decision_res.total_cost:.2f} €</b>"

        # 3. État (renseigné vendeur et diagnostic critique IA)
        clean_status = _clean_status(str(item.get("status") or "").strip())
        clip_data = decision_res.details.get("clip") or decision_res.details.get("resale", {}).get("clip") or {}
        ai_desc = clip_data.get("condition_desc") or ""
        damage_score = decision_res.details.get("damage_score")

        if final_check_notes:
            ai_status = f"contrôle expert : {final_check_notes}"
        elif ai_desc:
            ai_status = ai_desc
        elif damage_score is not None:
            if damage_score < 0.20:
                ai_status = "Tissu net, couleur intense, fibres intactes (aucun accroc)"
            elif damage_score < 0.40:
                ai_status = "Très bon état général, fibres propres"
            elif damage_score < 0.55:
                ai_status = f"Signes d'usage et patine visible (usure {damage_score*100:.0f}%)"
            else:
                ai_status = f"⚠️ Vigilance : défaut/usure suspectée ({damage_score*100:.0f}%)"
        else:
            ai_status = "Aspect ordinaire (contrôle attentif)"

        is_flawed = "⚠️" in ai_status or (damage_score is not None and damage_score >= 0.45)
        ai_icon = "⚠️" if is_flawed else "🔍"

        if clean_status:
            etat_display = (
                f"📝 <b>État vendeur :</b> {html.escape(clean_status)}\n"
                f"{ai_icon} <b>Vision IA :</b> <i>{html.escape(ai_status)}</i>"
            )
        else:
            etat_display = f"{ai_icon} <b>Vision IA :</b> <i>{html.escape(ai_status)}</i>"

        ai_prod_name = decision_res.details.get("ai_product_name")
        ai_prod_line = f"👗 <b>Pièce identifiée IA :</b> <b>{html.escape(ai_prod_name)}</b>\n" if ai_prod_name else ""
        ai_resale_reason = decision_res.details.get("ai_resale_reason")
        ai_resale_block = f"💡 <b>Valorisation IA :</b> <i>\"{html.escape(ai_resale_reason)}\"</i>\n" if ai_resale_reason else ""

        # Bloc Marché réel Vinted (LiveMarket Check ou AI Valuation)
        resale_data = decision_res.details.get("resale") or {}
        lm = resale_data.get("live_market")
        ai_min = decision_res.details.get("ai_resale_min")
        ai_max = decision_res.details.get("ai_resale_max")

        if ai_prod_name and ai_min and ai_max:
            target_gross = decision_res.revente_retenue / 0.90
            market_line = (
                f"📈 <b>Revente réelle estimée IA :</b> <b>~{target_gross:.0f} €</b> <i>(Fourchette : {ai_min:.0f} € à {ai_max:.0f} €)</i>\n"
                f"🎯 <b>Revente nette négociée :</b> <b>~{decision_res.revente_retenue:.0f} €</b> (après négo)\n"
            )
        elif lm and lm.get("sample_count"):
            cnt = lm.get("sample_count", 0)
            med = float(lm.get("median_price", 0.0))
            p25 = float(lm.get("p25_price", 0.0))
            p75 = float(lm.get("p75_price", 0.0))
            market_line = (
                f"📈 <b>Marché réel Vinted :</b> <b>{med:.0f} €</b> <i>(sur {cnt} annonces en vente)</i>\n"
                f"📊 <b>Fourchette observée :</b> {p25:.0f} € (liquidation) ➔ {p75:.0f} €\n"
                f"🎯 <b>Revente nette négociée :</b> <b>~{decision_res.revente_retenue:.0f} €</b> (après négo -12%)\n"
            )
        else:
            market_line = f"📈 <b>Revente :</b> ~{revente_cible:.0f} € <i>(Nette négociée : <b>{decision_res.revente_retenue:.0f} €</b>)</i>\n"

        caption = (
            f"⚡ <b>{header}</b>\n\n"
            f"🏷️ <b>Titre :</b> {title}\n"
            f"💎 <b>Marque :</b> {brand_display}\n"
            f"{ai_prod_line}"
            f"{price_line}\n"
            f"{etat_display}\n\n"
            f"{market_line}"
            f"💵 <b>Marge nette :</b> <b>+{decision_res.margin:.2f} €</b> (<b>{decision_res.multiple:.1f}x</b>)\n"
            f"📊 <b>Scénarios :</b> ⚡ Flash: {m_flash:+.0f}€ | 🎯 Cible: {decision_res.margin:+.0f}€ | 💎 Max: {m_opt:+.0f}€\n"
            f"🎯 <b>Score :</b> {decision_res.score_final:.1f}/100 ({tier_icon})\n"
            f"📁 <b>Catégorie :</b> {cat_str}\n"
            f"{taste_block}\n"
            f"{ai_resale_block}"
            f"🛍️ <b>Comparables vendus :</b>\n{comp_block}\n\n"
            f"💡 <b>Points forts :</b>\n{reasons_block}\n"
        )

        if final_check_notes:
            caption += f"\n🔍 <b>Contrôle :</b> <i>{html.escape(final_check_notes[:80])}</i>\n"

        caption += f"\n🔗 <a href='{direct_url}'>👉 ⚡ Cliquer ici pour ouvrir l'article</a>"

        # Sécurité longueur Telegram
        if len(caption) > 1000:
            caption = (
                f"⚡ <b>{header}</b>\n\n"
                f"🏷️ <b>Titre :</b> {title[:45]}\n"
                f"💎 <b>Marque :</b> {brand_display}\n"
                f"{price_line}\n"
                f"{etat_display}\n\n"
                f"📈 <b>Revente :</b> ~{revente_cible:.0f} € | <b>Marge :</b> <b>+{decision_res.margin:.2f} €</b> ({decision_res.multiple:.1f}x)\n"
                f"🎯 <b>Score :</b> {decision_res.score_final:.1f}/100 ({tier_icon})\n"
                f"📁 <b>Catégorie :</b> {cat_str}\n\n"
                f"🔗 <a href='{direct_url}'>👉 Ouvrir l'article</a>"
            )

        # Photos
        photos = item.get("photos") or []
        photo_url = None
        if photos and len(photos) > 0:
            photo_url = photos[0].get("url") or photos[0].get("full_size_url")

        reply_markup = json.dumps({
            "inline_keyboard": [
                [{"text": "⚡ OUVRIR DANS L'APPLI VINTED 🛍️", "url": direct_url}],
                [
                    {"text": "🎯 🟢 MUST BUY", "callback_data": f"fb:must_buy:{item_id}"},
                    {"text": "🤔 🟡 AVIS MAMA", "callback_data": f"fb:wife_opinion:{item_id}"},
                    {"text": "❌ 🔴 REJET", "callback_data": f"fb:reject:{item_id}"}
                ],
                [
                    {"text": "🛡️ Vérifier Authenticité (Legit Check) 🔍", "callback_data": f"fb:check_auth:{item_id}"}
                ]
            ]
        })

        try:
            if photo_url and photo_url.startswith("http"):
                response = requests.post(
                    f"{self.base_url}/sendPhoto",
                    data={
                        "chat_id": self.chat_id,
                        "photo": photo_url,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup
                    },
                    timeout=10
                )
            else:
                response = requests.post(
                    f"{self.base_url}/sendMessage",
                    data={
                        "chat_id": self.chat_id,
                        "text": caption,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                        "reply_markup": reply_markup
                    },
                    timeout=10
                )

            if response.status_code == 200:
                logger.debug(f"Notification v2 Telegram envoyée pour {item_id} ({country.upper()})")
                return response.json().get("result", {}).get("message_id")
            else:
                logger.error(f"Erreur Telegram send_v2_deal_alert ({response.status_code}): {response.text}")
                return None
        except Exception as e:
            logger.error(f"Erreur envoi notification v2 Telegram: {e}")
            return None

    def edit_deal_alert_result(
        self,
        message_id: int,
        item: Dict[str, Any],
        search_name: str,
        domain: str = "vinted.fr",
        vision_result: Optional[Dict[str, Any]] = None,
        country: str = "fr",
        shipping_cost: float = 0.0,
        margin: Optional[float] = None,
        resale_estimate: Optional[float] = None,
        min_margin_eur: float = 15.0
    ) -> bool:
        """
        Édite l'alerte Telegram envoyée en phase 1 pour afficher les conclusions de l'analyse IA.
        Si la marge est sous min_margin_eur ou verdict REJECT, affiche "IA : à éviter".
        """
        if not self.is_configured() or not message_id:
            return False

        item_id = item.get("id")
        title = html.escape(str(item.get("title", "Sans titre")))
        search_name_esc = html.escape(str(search_name))

        raw_price_str = self._extract_price(item)
        try:
            p_val = float(raw_price_str)
        except ValueError:
            p_val = 0.0

        flag = COUNTRY_FLAGS.get(country.lower(), "🌍")
        if shipping_cost > 0:
            total_cost = p_val + shipping_cost
            price_formatted = f"<b>{p_val:.2f} €</b> <i>(Total port inclus : <b>{total_cost:.2f} €</b> {flag})</i>"
        else:
            price_formatted = f"<b>{p_val:.2f} €</b> {flag}"

        brand = html.escape(str(item.get("brand_title") or "Non spécifié"))
        size = html.escape(str(item.get("size_title") or "Non spécifié"))
        status = html.escape(str(item.get("status") or "Non spécifié"))

        user_info = item.get("user") or {}
        seller_login = html.escape(str(user_info.get("login", "Inconnu")))
        feedback_rep = user_info.get("feedback_reputation")
        if feedback_rep is not None:
            rating_stars = f"⭐ {float(feedback_rep) * 5.0:.1f}/5"
        else:
            rating_stars = "Pas d'évaluations"

        raw_item_url = str(item.get("url") or "")
        direct_url = raw_item_url if raw_item_url.startswith("http") else f"https://www.{domain}/items/{item_id}"

        score = vision_result.get("score", 0) if vision_result else 0
        verdict = str(vision_result.get("verdict", "ERROR")) if vision_result else "ERROR"
        summary = html.escape(str(vision_result.get("summary", ""))[:180]) if vision_result else ""
        condition = html.escape(str(vision_result.get("condition_assessment", ""))[:110]) if vision_result else ""
        defects = vision_result.get("defects_detected", []) if vision_result else []

        resale_val = resale_estimate
        if resale_val is None and vision_result:
            try:
                resale_val = float(vision_result.get("resale_estimate_eur", 0.0))
            except (ValueError, TypeError):
                resale_val = 0.0

        margin_val = margin
        if margin_val is None:
            vinted_fee = 0.70 + (0.05 * p_val)
            margin_val = (resale_val or 0.0) - (p_val + shipping_cost + vinted_fee)

        # Déterminer si l'article est validé ou à éviter
        is_deal_validated = (score >= 75) and (verdict not in ("REJECT", "ERROR")) and (margin_val >= min_margin_eur)

        if is_deal_validated:
            status_banner = "⚡ <b>PÉPITE VALIDÉE PAR L'IA !</b>"
            financial_line = (
                f"📈 <b>Revente estimée :</b> ~{resale_val:.2f} €\n"
                f"💵 <b>Marge estimée :</b> <b>+{margin_val:.2f} €</b> 🟢\n"
            )
            badge_icon = "🟢 PÉPITE VALIDÉE"
        else:
            status_banner = "⛔ <b>IA : À ÉVITER</b>"
            reason_bad = []
            if verdict in ("REJECT", "ERROR") or score < 75:
                reason_bad.append(f"Score faible ({score}/100, {verdict})")
            if margin_val < min_margin_eur:
                reason_bad.append(f"Marge insuffisante (+{margin_val:.2f}€ < {min_margin_eur}€)")
            reasons_str = " | ".join(reason_bad)
            financial_line = (
                f"⚠️ <b>Verdict IA :</b> <b>À ÉVITER</b> <i>({reasons_str})</i>\n"
                f"📈 <b>Revente est. :</b> ~{resale_val:.2f} € | <b>Marge :</b> {margin_val:+.2f} €\n"
            )
            badge_icon = "🔴 À ÉVITER"

        vision_text = (
            f"\n🤖 <b>IA VISION SCORE :</b> {score}/100 ({badge_icon})\n"
            f"🔍 <b>Analyse IA :</b> <i>{summary}</i>\n"
        )
        if condition:
            vision_text += f"🧵 <b>État :</b> <i>{condition}</i>\n"
        if defects and len(defects) > 0:
            defects_esc = html.escape(", ".join(defects)[:100])
            vision_text += f"⚠️ <b>Anomalies :</b> <i>{defects_esc}</i>\n"

        desc_snippet = ""
        raw_desc = item.get("description", "").strip()
        if raw_desc:
            clean_desc = html.escape(raw_desc[:90] + ("..." if len(raw_desc) > 90 else ""))
            desc_snippet = f"📝 <b>Description :</b> <i>\"{clean_desc}\"</i>\n"

        caption = (
            f"{status_banner} {flag}\n\n"
            f"📌 <b>Recherche :</b> {search_name_esc}\n"
            f"🏷️ <b>Titre :</b> {title}\n"
            f"💰 <b>Prix :</b> {price_formatted}\n"
            f"{financial_line}"
            f"🌐 <b>Domaine :</b> <code>{domain}</code>\n"
            f"📏 <b>Taille :</b> {size} | 🏢 <b>Marque :</b> {brand}\n"
            f"✨ <b>État Vinted :</b> {status}\n"
            f"👤 <b>Vendeur :</b> {seller_login} ({rating_stars})\n"
            f"{desc_snippet}"
            f"{vision_text}\n"
            f"🔗 <a href='{direct_url}'>👉 ⚡ Cliquer ici pour voir l'article</a>"
        )

        if len(caption) > 1000:
            caption = (
                f"{status_banner} {flag}\n\n"
                f"📌 <b>Recherche :</b> {search_name_esc}\n"
                f"🏷️ <b>Titre :</b> {title}\n"
                f"💰 <b>Prix :</b> {price_formatted} | 🏢 {brand}\n"
                f"{financial_line}"
                f"🤖 Score: {score}/100 | {summary[:200]}\n"
                f"🔗 <a href='{direct_url}'>👉 ⚡ Cliquer ici pour voir l'article</a>"
            )

        reply_markup = json.dumps({
            "inline_keyboard": [
                [
                    {"text": "⚡ OUVRIR DANS L'APPLI VINTED 🛍️", "url": direct_url}
                ],
                [
                    {"text": "🎯 🟢 MUST BUY", "callback_data": f"fb:must_buy:{item_id}"},
                    {"text": "🤔 🟡 AVIS MAMA", "callback_data": f"fb:wife_opinion:{item_id}"},
                    {"text": "❌ 🔴 REJET", "callback_data": f"fb:reject:{item_id}"}
                ],
                [
                    {"text": "🛡️ Vérifier Authenticité (Legit Check) 🔍", "callback_data": f"fb:check_auth:{item_id}"}
                ]
            ]
        })

        try:
            # Essayer d'éditer la légende de la photo
            res = requests.post(
                f"{self.base_url}/editMessageCaption",
                data={
                    "chat_id": self.chat_id,
                    "message_id": message_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup
                },
                timeout=8
            )
            if res.status_code == 200:
                logger.info(f"✏️ Alerte Telegram #{message_id} éditée avec succès pour item #{item_id} (Verdict: {badge_icon})")
                return True
            else:
                # Si le message d'origine était un message texte simple
                res_txt = requests.post(
                    f"{self.base_url}/editMessageText",
                    data={
                        "chat_id": self.chat_id,
                        "message_id": message_id,
                        "text": caption,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup
                    },
                    timeout=8
                )
                if res_txt.status_code == 200:
                    logger.info(f"✏️ Alerte texte Telegram #{message_id} éditée avec succès pour item #{item_id}")
                    return True
                else:
                    logger.warning(f"Échec édition alerte Telegram #{message_id}: {res.text}")
                    return False
        except Exception as e:
            logger.error(f"Erreur lors de l'édition de l'alerte Telegram #{message_id}: {e}")
            return False

    @staticmethod
    def _extract_price(item: Dict[str, Any]) -> str:
        """Extrait et formate proprement le prix de l'article."""
        price_obj = item.get("price")
        if isinstance(price_obj, dict):
            return str(price_obj.get("amount", "N/A"))
        elif isinstance(price_obj, (int, float, str)):
            return str(price_obj)
        return "N/A"
