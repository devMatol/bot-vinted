import logging
import json
import time
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
import requests
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger("VintedBot.VisionEvaluator")

DEFAULT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-flash-lite-latest",
    "gemini-flash-latest"
]

class VisionEvaluator:
    """Module d'analyse visuelle par IA Multimodale avec exécution parallèle thread-safe,
    rotation multi-clés et multi-modèles, sélection intelligente de 3 photos max,
    résolution média basse, suivi des tokens réels et gestion des quotas quotidiens (pause 9h05 Paris)."""

    def __init__(
        self,
        api_key: Union[str, List[str]] = "",
        models: Optional[List[str]] = None,
        telegram_notifier = None,
        db_manager = None
    ):
        self._state_lock = threading.Lock()
        if isinstance(api_key, list):
            self.api_keys = [k.strip() for k in api_key if k and isinstance(k, str) and k.strip()]
        elif isinstance(api_key, str) and api_key.strip():
            self.api_keys = [api_key.strip()]
        else:
            self.api_keys = []

        self.models = [m.strip() for m in models if m and isinstance(m, str) and m.strip()] if models else list(DEFAULT_MODELS)
        self.telegram_notifier = telegram_notifier
        self.db_manager = db_manager

        self.active_key_index = 0
        self.active_model_index = 0
        self.clients_cache: Dict[str, Any] = {}

        # Gestion de la suspension globale jusqu'à 9h05 heure de Paris
        self.suspended_until: Optional[float] = None
        self._quota_alert_sent = False

        # Session requests partagée pour le téléchargement d'images
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        })

    def set_notifier(self, notifier):
        self.telegram_notifier = notifier

    def set_db_manager(self, db_manager):
        self.db_manager = db_manager

    def set_keys(self, api_keys: Union[str, List[str]], models: Optional[List[str]] = None):
        """Met à jour dynamiquement la liste des clés API Gemini et des modèles."""
        with self._state_lock:
            if isinstance(api_keys, list):
                new_keys = [k.strip() for k in api_keys if k and isinstance(k, str) and k.strip()]
            elif isinstance(api_keys, str) and api_keys.strip():
                new_keys = [api_keys.strip()]
            else:
                new_keys = []

            if models:
                new_models = [m.strip() for m in models if m and isinstance(m, str) and m.strip()]
            else:
                new_models = self.models

            if new_keys != self.api_keys or new_models != self.models:
                self.api_keys = new_keys
                self.models = new_models
                self.active_key_index = 0
                self.active_model_index = 0
                self.clients_cache.clear()

    def get_current_model(self) -> str:
        with self._state_lock:
            if not self.models:
                return "gemini-3.5-flash-lite"
            return self.models[self.active_model_index % len(self.models)]

    def _get_client_for_key(self, api_key: str):
        """Récupère ou crée un client genai pour la clé donnée."""
        with self._state_lock:
            if api_key in self.clients_cache:
                return self.clients_cache[api_key]
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                self.clients_cache[api_key] = client
                return client
            except Exception as e:
                logger.error(f"Erreur initialisation Client Gemini Vision ({api_key[:10]}...): {e}")
                return None

    def _rotate_key_and_model(self) -> bool:
        """
        Bascule sur la clé suivante sous verrou d'état. Si toutes les clés ont été testées pour le modèle en cours,
        on bascule sur le modèle suivant de la liste (config.json).
        """
        with self._state_lock:
            total_keys = len(self.api_keys)
            total_models = len(self.models)
            if total_keys == 0 or total_models == 0:
                return False

            old_key_idx = self.active_key_index
            old_model = self.models[self.active_model_index % total_models]

            # Passer à la clé suivante
            self.active_key_index = (self.active_key_index + 1) % total_keys

            # Si on est revenu à la première clé, on avance d'un modèle
            if self.active_key_index == 0:
                self.active_model_index = (self.active_model_index + 1) % total_models
                if self.active_model_index == 0:
                    logger.warning(
                        f"⚠️ Quota épuisé sur la clé #{old_key_idx + 1} (modèle '{old_model}'). "
                        f"TOUTES les combinaisons clé/modèle sont épuisées !"
                    )
                    return False

            new_model = self.models[self.active_model_index % total_models]
            logger.warning(
                f"⚠️ Quota épuisé sur la clé #{old_key_idx + 1} ('{old_model}'). "
                f"Basculement sur Clé #{self.active_key_index + 1}/{total_keys} avec modèle '{new_model}' !"
            )
            return True

    def _calculate_next_9h05_paris(self) -> float:
        """Calcule le timestamp UNIX de la prochaine occurrence de 9h05 heure de Paris."""
        now_ts = time.time()
        local_st = time.localtime(now_ts)
        target_today = datetime.datetime(
            local_st.tm_year, local_st.tm_mon, local_st.tm_mday, 9, 5, 0
        )
        now_dt = datetime.datetime.fromtimestamp(now_ts)
        if now_dt >= target_today:
            target_dt = target_today + datetime.timedelta(days=1)
        else:
            target_dt = target_today

        return target_dt.timestamp()

    def _trigger_global_suspension(self):
        """Active la suspension globale des appels Gemini jusqu'à 9h05 heure de Paris et envoie un seul message Telegram."""
        with self._state_lock:
            resume_ts = self._calculate_next_9h05_paris()
            self.suspended_until = resume_ts
            resume_dt = datetime.datetime.fromtimestamp(resume_ts)
            wait_seconds = max(0.0, resume_ts - time.time())
            hours = int(wait_seconds // 3600)
            minutes = int((wait_seconds % 3600) // 60)

            logger.warning(
                f"🛑 TOUS LES QUOTAS GEMINI SONT ÉPUISÉS sur l'ensemble des clés et modèles. "
                f"Suspension des appels IA jusqu'à {resume_dt.strftime('%d/%m/%Y %H:%M:%S')} (dans {hours}h{minutes:02d}m)."
            )

            # Envoi d'un message unique sur Telegram
            if not self._quota_alert_sent and self.telegram_notifier and getattr(self.telegram_notifier, "is_configured", lambda: False)():
                msg = (
                    f"⚠️ <b>QUOTAS GEMINI ÉPUISÉS</b> ⚠️\n\n"
                    f"Toutes les combinaisons clés/modèles ont atteint leur quota.\n"
                    f"⏸️ Les analyses IA sont suspendues jusqu'à <b>9h05 (heure de Paris)</b> le {resume_dt.strftime('%d/%m/%Y')}.\n"
                    f"Le bot continue de surveiller le catalogue en mode silencieux."
                )
                try:
                    requests.post(
                        f"{self.telegram_notifier.base_url}/sendMessage",
                        data={
                            "chat_id": self.telegram_notifier.chat_id,
                            "text": msg,
                            "parse_mode": "HTML"
                        },
                        timeout=10
                    )
                    self._quota_alert_sent = True
                except Exception as e:
                    logger.error(f"Erreur envoi notification suspension Telegram: {e}")

    @staticmethod
    def _select_up_to_3_photos(photo_urls: List[str]) -> List[str]:
        """
        Sélectionne au maximum 3 photos pour minimiser le coût et le temps de latence (Point 3) :
        1. La 1re photo (vue d'ensemble principale).
        2. Une vue étiquette/composition si détectable dans l'URL ou par position.
        3. Une vue détail/texture ou dos.
        """
        if not photo_urls:
            return []
        if len(photo_urls) <= 3:
            return list(photo_urls)

        first_photo = photo_urls[0]
        remaining = photo_urls[1:]

        # Chercher une étiquette parmi les photos restantes
        label_keywords = ["label", "tag", "etiquette", "composition", "care", "brand_tag"]
        label_photo = None
        for p in remaining:
            p_lower = p.lower()
            if any(k in p_lower for k in label_keywords):
                label_photo = p
                break

        # Si pas d'indice d'étiquette explicite dans le nom, la photo 2 ou 3 montre souvent l'étiquette ou le dos
        if not label_photo and len(remaining) >= 2:
            label_photo = remaining[1]  # Index 2 dans la liste complète
        elif not label_photo and remaining:
            label_photo = remaining[0]

        # Choisir une vue détail (différente de la première et de l'étiquette)
        detail_photo = None
        for p in remaining:
            if p != label_photo:
                detail_photo = p
                break

        selected = [first_photo]
        if label_photo and label_photo not in selected:
            selected.append(label_photo)
        if detail_photo and detail_photo not in selected and len(selected) < 3:
            selected.append(detail_photo)

        return selected[:3]

    def _download_single_image(self, p_url: str, domain: str):
        """Télécharge une photo de manière sécurisée."""
        from google.genai import types
        headers = {
            "Referer": f"https://www.{domain}/"
        }
        try:
            resp = self.session.get(p_url, headers=headers, timeout=8)
            if resp.status_code == 200 and len(resp.content) > 1000:
                content_type = resp.headers.get("Content-Type", "")
                mime = "image/webp"
                if "jpeg" in content_type or "jpg" in content_type or ".jpg" in p_url or ".jpeg" in p_url:
                    mime = "image/jpeg"
                elif "png" in content_type or ".png" in p_url:
                    mime = "image/png"
                return types.Part.from_bytes(data=resp.content, mime_type=mime)
        except Exception as dl_err:
            logger.debug(f"Échec téléchargement photo {p_url[:60]}: {dl_err}")
        return None

    def evaluate_deal(
        self,
        item: Dict[str, Any],
        search_name: str,
        feedback_examples: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        shipping_cost: float = 0.0,
        country: str = "fr"
    ) -> Dict[str, Any]:
        """
        Inspecte jusqu'à 3 photos sélectionnées et la description complète d'une annonce.
        Le verrou n'est plus maintenu pendant le téléchargement des photos ni pendant l'appel réseau Gemini.
        """
        now_ts = time.time()
        with self._state_lock:
            if self.suspended_until is not None:
                if now_ts < self.suspended_until:
                    return {
                        "score": 0,
                        "verdict": "ERROR",
                        "summary": "Suspension des quotas Gemini active jusqu'à 9h05 Paris.",
                        "resale_estimate_eur": 0.0,
                        "resale_reasoning": "Quotas suspendus."
                    }
                else:
                    logger.info("🌅 9h05 passées : Reprise automatique des analyses Gemini Vision !")
                    self.suspended_until = None
                    self._quota_alert_sent = False
                    self.active_key_index = 0
                    self.active_model_index = 0

        title = item.get("title", "")
        price = item.get("price")
        price_val = 0.0
        if isinstance(price, dict):
            price_val = float(price.get("amount", 0.0))
        elif isinstance(price, (int, float, str)):
            try:
                price_val = float(price)
            except ValueError:
                price_val = 0.0

        brand = item.get("brand_title", "Non spécifié")
        description = item.get("description", "").strip()
        domain = item.get("domain", "vinted.fr")
        total_price = price_val + float(shipping_cost)

        photos = item.get("photos") or []
        photo_urls = [p.get("url") for p in photos if isinstance(p, dict) and p.get("url")]

        # 3 photos maximum au lieu de 5 (Point 3 : Coût Gemini)
        selected_photo_urls = self._select_up_to_3_photos(photo_urls)

        with self._state_lock:
            if not self.api_keys or not selected_photo_urls:
                return {
                    "score": 0,
                    "verdict": "ERROR",
                    "summary": "Aucune photo ou clé API configurée.",
                    "resale_estimate_eur": 0.0,
                    "resale_reasoning": ""
                }

        from google.genai import types

        # Téléchargement des photos en parallèle via Session partagée (Point 1)
        image_parts = []
        with ThreadPoolExecutor(max_workers=min(3, len(selected_photo_urls))) as dl_executor:
            futures = [dl_executor.submit(self._download_single_image, p_url, domain) for p_url in selected_photo_urls]
            for f in futures:
                res_part = f.result()
                if res_part:
                    image_parts.append(res_part)

        if not image_parts:
            logger.warning(f"Aucune photo valide n'a pu être téléchargée pour '{title}'.")
            return {
                "score": 0,
                "verdict": "REJECT",
                "summary": "Impossible de charger les photos de l'annonce.",
                "resale_estimate_eur": 0.0,
                "resale_reasoning": ""
            }

        desc_text = description if description else "(Aucune description fournie par le vendeur)"

        feedback_section = ""
        if feedback_examples:
            must_buys = feedback_examples.get("MUST_BUY", [])
            rejects = feedback_examples.get("REJECTED", [])
            if must_buys or rejects:
                fb_lines = ["\n--- EXEMPLES DE MES GOÛTS PERSONNELS (HISTORIQUE FEEDBACK) ---"]
                if must_buys:
                    fb_lines.append("Annonces récemment validées (MUST_BUY) :")
                    for mb in must_buys[:10]:
                        t_mb = mb.get("title", "")
                        p_mb = mb.get("price", 0.0)
                        b_mb = mb.get("brand", "")
                        r_mb = mb.get("description", "") or mb.get("verdict", "")
                        fb_lines.append(f"  • '{t_mb}' ({p_mb}€, {b_mb}) - {r_mb}")
                if rejects:
                    fb_lines.append("Annonces récemment rejetées (REJECTED) :")
                    for rj in rejects[:10]:
                        t_rj = rj.get("title", "")
                        p_rj = rj.get("price", 0.0)
                        b_rj = rj.get("brand", "")
                        r_rj = rj.get("description", "") or rj.get("verdict", "")
                        fb_lines.append(f"  • '{t_rj}' ({p_rj}€, {b_rj}) - {r_rj}")
                fb_lines.append("Inspire-toi de ces exemples réels pour calibrer tes décisions et affiner ton jugement.\n")
                feedback_section = "\n".join(fb_lines)

        prompt = (
            f"Tu es un acheteur-revendeur prudent qui paie de sa poche sur Vinted France.\n"
            f"Par défaut, une annonce n'est PAS une bonne affaire. Tu dois trouver une raison concrète de dire oui.\n"
            f"Inspecte méticuleusement les {len(image_parts)} photos fournies ainsi que la description et les données de cette annonce Vinted :\n"
            f"- Titre: {title}\n"
            f"- Marque déclarée: {brand}\n"
            f"- Pays de provenance: {country.upper()} ({domain})\n"
            f"- Prix de l'article: {price_val}€\n"
            f"- Frais de port estimés vers la France: {shipping_cost}€\n"
            f"- Coût total d'achat (port compris): {total_price:.2f}€\n"
            f"- Description vendeur: {desc_text}\n"
            f"{feedback_section}\n"
            f"--- GRILLE DE NOTATION STRICTE (SCORE 0-100) ---\n"
            f"• 90-100 : Pièce exceptionnelle et recherchée (modèle iconique, imprimé signature, ligne principale de la marque, époque recherchée) ET revente estimée au moins 4 fois le coût total ({total_price:.2f}€).\n"
            f"• 75-89 : Pièce distinctive (coupe forte, imprimé singulier, matière noble, détail logo fort) ET revente estimée au moins 2,5 fois le coût total ({total_price:.2f}€).\n"
            f"• 50-74 : Pièce correcte mais banale / basique.\n"
            f"• 0-49 : Basique ordinaire, ligne secondaire sans signe distinctif, défaut/usure, doute d'authenticité, ou objet non vêtement.\n\n"
            f"--- RÈGLES CRITIQUES D'INSPECTION & REVENTE ---\n"
            f"1. RÈGLE DES BASIQUES ET LIGNES DIFFUSION :\n"
            f"   - Un basique uni (sweat, pull, t-shirt, chemise, jean bleu, pantalon uni) d'une ligne diffusion (Armani Jeans, Emporio Armani, Versace Jeans, Love Moschino, Diesel, Guess, Liu Jo, Patrizia Pepe, Weekend Max Mara, Just Cavalli) vaut 12 à 20 € sur Vinted, quel que soit son état : score max 55.\n"
            f"   - Les accessoires, pochettes promotionnelles, objets beauté, cintres, boîtes, vaisselle, chaussettes et pyjamas se revendent très mal : score max 40.\n\n"
            f"2. ÉLÉMENTS DISTINCTIFS OBLIGATOIRES (distinctive_features) :\n"
            f"   - Énumère dans 'distinctive_features' les caractéristiques uniques et concrètes justifiant un intérêt pour un revendeur (ex: 'motif ananas signature', 'coupe corset asymétrique', 'poche cargo zippée Mugler').\n"
            f"   - Si la liste 'distinctive_features' est vide ou ne contient que des banalités : score max 60 et resale_estimate_eur max 20.\n\n"
            f"3. ESTIMATION DU PRIX COMPARABLE (comparable) :\n"
            f"   - 'comparable' : prix en euros auquel une pièce équivalente se vend réellement sur Vinted France (pas le prix affiché gonflé par les vendeurs, mais le prix effectif de vente sous 2 à 4 semaines).\n"
            f"   - 'resale_estimate_eur' est l'estimation basse et prudente de ces ventes réelles.\n\n"
            f"4. ANALYSE DES DÉFAUTS, RÉTRÉCISSEMENT ET ÉTAT :\n"
            f"   - Mots d'alerte dans la description : 'rétréci', 'feutré', 'accident de lavage', 'trou', 'mite', 'tache', 'usé', 'décoloré'.\n"
            f"   - Tout vêtement rétréci ou feutré au lavage perd toute valeur commerciale -> REJET IMPÉRATIF (Score < 30, verdict REJECT).\n\n"
            f"Réponds STRICTEMENT sous la forme d'un objet JSON valide sans texte avant ni après, en respectant ce format :\n"
            f"{{\n"
            f'  "score": <entier 0-100>,\n'
            f'  "verdict": "<MUST_BUY, NEEDS_REVIEW ou REJECT>",\n'
            f'  "distinctive_features": ["<caractéristique 1>", "<caractéristique 2>"],\n'
            f'  "comparable": "<prix auquel une pièce équivalente se vend réellement sur Vinted France>",\n'
            f'  "resale_estimate_eur": <prix en euros>,\n'
            f'  "resale_reasoning": "<justification concise en une phrase>",\n'
            f'  "summary": "<explication claire de la décision>",\n'
            f'  "condition_assessment": "<bilan d état matière et finitions>",\n'
            f'  "defects_detected": []\n'
            f"}}\n"
            f"Les seules valeurs acceptées pour 'verdict' sont : 'MUST_BUY', 'NEEDS_REVIEW', 'REJECT'."
        )

        # Configuration de génération avec résolution média basse pour réduire les coûts (Point 3)
        gen_config = None
        try:
            gen_config = types.GenerateContentConfig(
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW
            )
        except Exception as cfg_err:
            logger.debug(f"MediaResolution.MEDIA_RESOLUTION_LOW non supporté : {cfg_err}")

        contents_payload = image_parts + [prompt]

        total_combinations = len(self.api_keys) * len(self.models)
        for attempt in range(total_combinations):
            # Récupérer la clé et le modèle actifs sous un verrou très bref (Point 1 : IA en parallèle)
            with self._state_lock:
                current_key = self.api_keys[self.active_key_index % len(self.api_keys)]
                current_model = self.models[self.active_model_index % len(self.models)]

            client = self._get_client_for_key(current_key)
            if not client:
                self._rotate_key_and_model()
                continue

            try:
                # Appel Gemini sans maintenir le verrou
                if gen_config:
                    response = client.models.generate_content(
                        model=current_model,
                        contents=contents_payload,
                        config=gen_config
                    )
                else:
                    response = client.models.generate_content(
                        model=current_model,
                        contents=contents_payload
                    )

                raw_text = response.text.strip()
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                data = json.loads(raw_text)
                score = data.get("score", 0)
                verdict = data.get("verdict", "REJECT")
                condition = data.get("condition_assessment", "")
                defects = data.get("defects_detected", [])
                resale = data.get("resale_estimate_eur", 0.0)

                try:
                    data["resale_estimate_eur"] = float(resale)
                except (ValueError, TypeError):
                    data["resale_estimate_eur"] = 0.0

                data.setdefault("resale_reasoning", "")

                # Enregistrement des tokens réels consommés en base de données (Point 3)
                usage_meta = getattr(response, "usage_metadata", None)
                if usage_meta and self.db_manager:
                    try:
                        p_tok = getattr(usage_meta, "prompt_token_count", 0) or 0
                        c_tok = getattr(usage_meta, "candidates_token_count", 0) or 0
                        t_tok = getattr(usage_meta, "total_token_count", 0) or (p_tok + c_tok)
                        self.db_manager.record_token_usage(
                            prompt_tokens=p_tok,
                            candidates_tokens=c_tok,
                            total_tokens=t_tok,
                            model=current_model
                        )
                        logger.debug(f"📊 Tokens consommés : {p_tok} prompt, {c_tok} candidates ({t_tok} total)")
                    except Exception as db_err:
                        logger.debug(f"Erreur enregistrement usage tokens: {db_err}")

                logger.info(
                    f"🎯 Vision IA réussie ({current_model}) pour '{title}' : "
                    f"Score {score}/100 ({verdict}) | Revente est.: {data['resale_estimate_eur']}€ | État: {condition[:50]}... | Défauts: {defects}"
                )
                return data

            except Exception as e:
                err_msg = str(e).lower()
                if ("resource_exhausted" in err_msg or "429" in err_msg or "quota" in err_msg or "too many requests" in err_msg):
                    can_rotate = self._rotate_key_and_model()
                    if can_rotate:
                        time.sleep(0.3)
                        continue
                    else:
                        self._trigger_global_suspension()
                        return {
                            "score": 0,
                            "verdict": "ERROR",
                            "summary": "Toutes les combinaisons clés/modèles Gemini sont épuisées. Suspension jusqu'à 9h05.",
                            "resale_estimate_eur": 0.0,
                            "resale_reasoning": ""
                        }

                logger.error(f"Erreur lors de l'analyse Vision IA ({current_model}): {e}")
                return {
                    "score": 0,
                    "verdict": "ERROR",
                    "summary": f"Erreur analyse IA: {str(e)[:60]}",
                    "resale_estimate_eur": 0.0,
                    "resale_reasoning": ""
                }

        self._trigger_global_suspension()
        return {
            "score": 0,
            "verdict": "ERROR",
            "summary": "Quotas épuisés sur toutes les clés et modèles Gemini disponibles. Suspension jusqu'à 9h05.",
            "resale_estimate_eur": 0.0,
            "resale_reasoning": ""
        }
