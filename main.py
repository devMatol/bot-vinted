import json
import time
import os
import sys
import argparse
import logging
import threading
import queue
import itertools
from collections import deque
import io
from typing import Dict, Any, List, Set, Tuple, Optional
import requests
from PIL import Image

from src.auth import VintedSessionManager
from src.rate_limiter import VintedRateLimiter
from src.scraper import VintedScraper
from src.filters import DealEvaluator, is_clothing_shoes_or_bag, get_category_cap_and_multiplier
from src.database import DatabaseManager
from src.notifier import TelegramNotifier
from src.telegram_bot import TelegramCommandHandler
from src.in_demand import InDemandTracker
from src.vision_evaluator import VisionEvaluator
from src.translator import translate_query

# Imports Moteur de décision V2 (Lots 1 à 8)
from src.scoring.rules import evaluate_rules, RuleResult, DIFFUSION_BASIC_CATEGORIES, is_diffusion_target_brand
from src.scoring.clip_scorer import get_clip_scorer, select_up_to_3_photos
from src.scoring.market import record_market_listing, market_median, get_comparables_matcher
from src.scoring.resale_model import estimate_resale_price
from src.scoring.listing_signals import evaluate_listing_signals
from src.scoring.decision import make_decision, record_decision, calculate_total_cost, DecisionResult
from src.scoring.final_check import perform_final_check
from src.scoring.taste import get_taste_score, find_top_matching_favourites
from src.scoring.taxonomy import detect_category, normalize_brand
from src.lock import ProcessLock

# Force UTF-8 pour la console Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Masquer le bruit des bibliothèques externes
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("VintedBot.Auth").setLevel(logging.WARNING)

# Format console épuré
_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_file = logging.FileHandler("bot.log", encoding="utf-8")
_file.setLevel(logging.DEBUG)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[_console, _file]
)
# Console : uniquement les verdicts OUI/NON et les problèmes. bot.log : tout le détail.
logging.getLogger("VintedBot").setLevel(logging.DEBUG)
logger = logging.getLogger("VintedBot.Main")


def log_verdict(ok: bool, item: Dict[str, Any], price, detail: str) -> None:
    """Une seule ligne lisible par annonce analysée : ✅ OUI (alerte envoyée) ou ❌ NON + raison courte."""
    brand = str(item.get("brand_title") or item.get("brand") or "?")[:20]
    title = str(item.get("title") or "")[:40]
    try:
        p = f"{float(price):g}€"
    except (TypeError, ValueError):
        p = "?€"
    tag = "✅ OUI" if ok else "❌ non"
    logger.info(f"{tag} | {brand} · {p} · {title} — {detail}")


CONFIG_PATH = "config.json"
seen_items_lock = threading.Lock()

COUNTRY_DOMAINS = {
    "fr": "vinted.fr",
    "it": "vinted.it",
    "de": "vinted.de",
    "es": "vinted.es",
    "be": "vinted.be",
    "nl": "vinted.nl",
    "pt": "vinted.pt",
    "at": "vinted.at"
}


def load_config(path: str = CONFIG_PATH) -> Dict[str, Any]:
    """Charge la configuration depuis le fichier JSON."""
    if not os.path.exists(path):
        logger.error(f"Fichier de configuration '{path}' introuvable !")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =====================================================================
# GESTION DES FILES ET STATISTIQUES DE PERFORMANCE (Section 1 & 6)
# =====================================================================

def put_queue_drop_oldest(q: queue.Queue, item: Any, name: str = "file"):
    """Insère dans la file ; si elle est pleine, retire l'élément le plus ancien."""
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
            q.task_done()
        except (queue.Empty, ValueError):
            pass
        logger.debug(f"{name} pleine (taille {q.maxsize}) : ancien élément écarté.")
        try:
            q.put_nowait(item)
        except queue.Full:
            pass


def put_priority_queue_drop_lowest(q: queue.PriorityQueue, priority: float, counter_val: int, payload: Any):
    """Insère dans la priority queue ; si pleine, déloge l'élément de plus faible priorité."""
    try:
        q.put_nowait((priority, counter_val, payload))
    except queue.Full:
        try:
            q.get_nowait()
            q.task_done()
        except (queue.Empty, ValueError):
            pass
        logger.debug(f"q_ouvrir pleine (taille {q.maxsize}) : élément délogé.")
        try:
            q.put_nowait((priority, counter_val, payload))
        except queue.Full:
            pass


class PipelineStats:
    """Suivi thread-safe des métriques de rapidité et des files."""

    def __init__(self, q_tri: queue.Queue, q_ouvrir: queue.PriorityQueue, q_juge: queue.Queue):
        self.lock = threading.Lock()
        self.q_tri = q_tri
        self.q_ouvrir = q_ouvrir
        self.q_juge = q_juge
        self.total_handled = 0
        self.opened_count = 0
        self.rejected_thumb_count = 0
        self.delays = deque(maxlen=50)
        self.last_radar_cycle_s = 0.0

    def record_thumb_reject(self, delay: float):
        with self.lock:
            self.total_handled += 1
            self.rejected_thumb_count += 1
            if delay > 0:
                self.delays.append(delay)
            self._check_log_50()

    def record_opened(self):
        with self.lock:
            self.opened_count += 1

    def record_verdict(self, delay: float):
        with self.lock:
            self.total_handled += 1
            if delay > 0:
                self.delays.append(delay)
            self._check_log_50()

    def set_radar_cycle_time(self, cycle_s: float):
        with self.lock:
            self.last_radar_cycle_s = cycle_s

    def _check_log_50(self):
        if self.total_handled > 0 and self.total_handled % 10 == 0:
            avg_w = (sum(self.delays) / len(self.delays)) if self.delays else 0.0
            logger.info(
                f"⏱️ Tour radar {self.last_radar_cycle_s:.1f}s | "
                f"Files tri/ouvrir/juge : {self.q_tri.qsize()}/{self.q_ouvrir.qsize()}/{self.q_juge.qsize()} | "
                f"{self.opened_count} ouvertes, {self.rejected_thumb_count} rejetées sur vignette | "
                f"Total jugées : {self.total_handled} (délai moyen {avg_w:.1f}s)"
            )


# =====================================================================
# REGROUPEMENT INTELLIGENT DES RECHERCHES DE MARQUES (Section 2)
# =====================================================================

def build_search_groups(searches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Regroupe les recherches 'b_*' par prix max identique (10 marques max par groupe).
    Les recherches matière ('m_*') et les marques sans brand_ids restent séparées.
    """
    grouped_jobs = []
    brand_searches_by_price: Dict[float, List[Dict[str, Any]]] = {}

    for s in searches:
        if not s.get("enabled", True):
            continue
        sid = str(s.get("id") or "")
        bids = s.get("brand_ids") or []
        p_max = float(s.get("max_price") or 0.0)

        # Seules les recherches b_* avec des brand_ids sont regroupables
        if sid.startswith("b_") and bids and p_max > 0:
            brand_searches_by_price.setdefault(p_max, []).append(s)
        else:
            grouped_jobs.append({
                "grouped": False,
                "search": s,
                "brand_ids": bids,
                "max_price": p_max,
                "name": s.get("name")
            })

    # Regrouper par paquets de 10 marques max pour chaque prix max identique
    for p_max, s_list in brand_searches_by_price.items():
        chunk_size = 10
        for i in range(0, len(s_list), chunk_size):
            chunk = s_list[i:i + chunk_size]
            all_bids = []
            for item_s in chunk:
                all_bids.extend(item_s.get("brand_ids") or [])
            all_bids = list(dict.fromkeys(all_bids))

            brand_names = [cs.get("name", "").replace("🐆 ", "").replace("💎 ", "").replace("✨ ", "").replace("🖤 ", "").replace("🦅 ", "").replace("🐯 ", "").replace("🦋 ", "").replace("🔺 ", "").replace("🔥 ", "").replace("🧥 ", "") for cs in chunk]
            job_name = f"Groupe b_ ({p_max:g}€) [{' / '.join(brand_names[:4])}{'...' if len(brand_names) > 4 else ''}]"
            grouped_jobs.append({
                "grouped": True,
                "searches": chunk,
                "brand_ids": all_bids,
                "max_price": p_max,
                "name": job_name
            })

    return grouped_jobs


def resolve_item_search(item: Dict[str, Any], job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Rattache chaque annonce issue d'un groupe à sa recherche d'origine pour préserver ses filtres."""
    if not job.get("grouped", False):
        return job.get("search")

    item_brand = (item.get("brand_title") or "").strip().lower()
    item_title = (item.get("title") or "").strip().lower()
    item_brand_id = item.get("brand_id")

    for s in job.get("searches", []):
        # Vérification par brand_id
        if item_brand_id and item_brand_id in (s.get("brand_ids") or []):
            return s

        # Vérification par variantes de marque
        variants = [v.lower() for v in (s.get("brand_variants") or [])]
        brand = (s.get("brand") or "").lower()
        if brand and brand not in variants:
            variants.append(brand)
        s_text = (s.get("search_text") or "").strip().lower()
        if s_text and s_text not in variants:
            variants.append(s_text)

        if any(v in item_brand or item_brand in v or v in item_title for v in variants):
            return s

        b_canon, _, _ = normalize_brand(item_brand, item_title)
        if b_canon and any(v in b_canon.lower() for v in variants):
            return s

    searches = job.get("searches", [])
    return searches[0] if searches else None


# =====================================================================
# ÉTAGE 1 : RADAR (1 thread) (Section 1)
# =====================================================================

def radar_worker(
    stop_event: threading.Event,
    scrapers_by_domain: Dict[str, List[VintedScraper]],
    scraper_index_by_domain: Dict[str, int],
    db: DatabaseManager,
    seen_items: Set[int],
    in_demand_tracker: InDemandTracker,
    first_run_countries: Set[str],
    q_tri: queue.Queue,
    q_ouvrir: queue.PriorityQueue,
    q_juge: queue.Queue,
    stats: PipelineStats
):
    """
    Enchaîne les requêtes catalogue en boucle sans attendre la fin des analyses.
    Pour chaque annonce jamais vue : prefilter, puis l'envoie dans q_tri.
    """
    logger.info("📡 Étage RADAR démarré (1 thread catalogue continu).")
    radar_cycle = 0

    while not stop_event.is_set():
        try:
            config = load_config()
            if not config.get("bot_enabled", False):
                time.sleep(5)
                continue

            searches = [s for s in config.get("searches", []) if s.get("enabled", True)]
            active_countries = [c.lower() for c in config.get("countries", ["fr"])]
            polling_interval = float(config.get("polling_interval_seconds", 5.0))

            grouped_jobs = build_search_groups(searches)
            t_cycle_start = time.time()
            new_items_in_cycle = 0

            for c in active_countries:
                if stop_event.is_set():
                    break
                domain = COUNTRY_DOMAINS.get(c, f"vinted.{c}")
                scraper_list = scrapers_by_domain.get(domain, [])
                if not scraper_list:
                    continue

                for job in grouped_jobs:
                    if stop_event.is_set():
                        break

                    # Round-robin parmi les scrapers/proxies de ce domaine
                    s_idx = scraper_index_by_domain[domain] % len(scraper_list)
                    scraper_index_by_domain[domain] += 1
                    scraper = scraper_list[s_idx]

                    # Paramètres de recherche pour le scraper
                    search_cfg = {
                        "name": job.get("name", "Recherche"),
                        "max_price": job.get("max_price"),
                        "order": "newest_first",
                        "brand_ids": job.get("brand_ids", [])
                    }
                    if not job.get("grouped", False):
                        single_s = job.get("search", {})
                        search_cfg["search_text"] = translate_query(single_s, c)
                    else:
                        search_cfg["search_text"] = ""

                    items = scraper.search_items(search_cfg, priority="low")

                    for it in items:
                        item_id = it.get("id")
                        if not item_id:
                            continue

                        with seen_items_lock:
                            if item_id in seen_items:
                                continue
                            seen_items.add(item_id)

                        it["_discovered_at"] = time.time()

                        # Rattachement à la recherche d'origine pour filtres et max_price exacts
                        search_def = resolve_item_search(it, job)
                        if not search_def:
                            continue

                        price_obj = it.get("price") or {}
                        price = float(price_obj.get("amount", 0.0)) if isinstance(price_obj, dict) else float(price_obj or 0.0)

                        if job.get("grouped", False):
                            spec_max = float(search_def.get("max_price") or 0.0)
                            if spec_max > 0 and price > spec_max:
                                continue

                        title = it.get("title", "")
                        db.mark_item_seen(item_id, domain=domain, title=title, price=price, search_id=search_def.get("id", ""))
                        in_demand_tracker.add_to_tracker(it, search_def.get("name", "Recherche"))

                        # Au premier scan d'un pays, warmup silencieux
                        if c in first_run_countries:
                            continue

                        if db.is_item_notified(item_id):
                            continue

                        # PASSE 1 : PREFILTER (titre, prix, mots exclus)
                        is_match, reason = DealEvaluator.prefilter(it, search_def)
                        if not is_match:
                            logger.debug(f"🚫 [Rejet Prefilter] [{c.upper()}] {title} ({price}€) | {reason}")
                            continue

                        # Transmission immédiate à l'étage de TRI
                        new_items_in_cycle += 1
                        put_queue_drop_oldest(q_tri, (it, search_def, domain, c), "q_tri")

                if c in first_run_countries:
                    first_run_countries.remove(c)
                    logger.info(f"⚡ Mode sniper actif : Cache initial prêt pour {c.upper()}.")

            cycle_duration = time.time() - t_cycle_start
            stats.set_radar_cycle_time(cycle_duration)
            radar_cycle += 1

            if new_items_in_cycle > 0 or radar_cycle % 3 == 0:
                logger.info(
                    f"📡 Tour radar #{radar_cycle} ({cycle_duration:.1f}s) : "
                    f"{new_items_in_cycle} nouvelle(s) annonce(s) transmise(s) au TRI | "
                    f"Files: tri={q_tri.qsize()} | ouvrir={q_ouvrir.qsize()} | juge={q_juge.qsize()}"
                )

            # Pause intelligente entre tours de radar
            time.sleep(max(1.0, polling_interval))

        except Exception:
            logger.exception("Erreur dans l'étage RADAR")
            time.sleep(3)


# =====================================================================
# ÉTAGE 2 : TRI LOCAL (Pool de 4 threads, 0 requête Vinted) (Section 1)
# =====================================================================

def tri_worker(
    worker_id: int,
    stop_event: threading.Event,
    q_tri: queue.Queue,
    q_ouvrir: queue.PriorityQueue,
    priority_counter: itertools.count,
    db: DatabaseManager,
    stats: PipelineStats
):
    """
    Télécharge la vignette directement depuis le CDN images*.vinted.net (hors rate limiter),
    calcule l'embedding et le goût Rita. Filtre immédiatement les goûts < 0.40 et les règles.
    Puis envoie dans q_ouvrir trié par goût Rita décroissant.
    """
    logger.debug(f"⚡ TRI worker #{worker_id} démarré.")

    while not stop_event.is_set():
        try:
            try:
                task_data = q_tri.get(timeout=0.5)
            except queue.Empty:
                continue

            item, search_def, domain, country = task_data
            discovered_at = item.get("_discovered_at", time.time())
            price = float(item.get("price", {}).get("amount", 0.0))
            config = load_config()

            # Étage A préliminaire : Règles heuristiques (rejet ultra-rapide avant téléchargement)
            rule_res = evaluate_rules(item, config=config, allow_bags=bool(search_def.get("allow_bags", True)))
            if rule_res.hard_reject or rule_res.score < float(config.get("rules_min_score", 35.0)):
                stop_reason = rule_res.reasons[0] if rule_res.reasons else "Score règles insuffisant"
                log_verdict(False, item, price, stop_reason)
                record_decision(DecisionResult(
                    item_id=str(item.get("id")),
                    decision="REJECTED",
                    alert_tier="NONE",
                    score_final=rule_res.score,
                    price=price,
                    total_cost=price,
                    revente_retenue=0.0,
                    margin=0.0,
                    multiple=0.0,
                    stage_reached="A",
                    stop_reason=stop_reason
                ))
                stats.record_verdict(time.time() - discovered_at)
                q_tri.task_done()
                continue

            item["_rule_res"] = rule_res

            thumb_url = item.get("photo", {}).get("url") or (item.get("photos", [{}])[0].get("url") if item.get("photos") else "")
            taste_score = None
            emb = None

            if thumb_url and thumb_url.startswith("http"):
                try:
                    resp = requests.get(thumb_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.status_code == 200 and len(resp.content) > 500:
                        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                        scorer = get_clip_scorer(config)
                        emb = scorer.encode_pil_image(img)
                        if emb is not None:
                            cat = item.get("category") or detect_category(item.get("title", ""))
                            taste_score = get_taste_score(emb, cat)
                            item["_clip_embedding"] = emb
                            item["_taste_score"] = taste_score
                except Exception as e:
                    logger.debug(f"Erreur téléchargement/encodage vignette #{item.get('id')}: {e}")

            # Filtrage précoce sur le goût de la vignette (si actif)
            # Tolérance accrue pour les grandes marques (Tier 3 et 1.5)
            taste_filter_enabled = bool(config.get("taste_filter_enabled", True))
            base_thumb_min = float(config.get("thumb_taste_min", 0.40))
            brand_tolerance = 0.08 if rule_res.tier >= 1.5 else 0.0
            effective_thumb_min = max(0.25, base_thumb_min - brand_tolerance)

            if taste_filter_enabled and taste_score is not None and taste_score < effective_thumb_min:
                stats.record_thumb_reject(time.time() - discovered_at)
                log_verdict(False, item, price, f"goût Rita {taste_score * 100:.0f}% sur la vignette")
                record_decision(DecisionResult(
                    item_id=str(item.get("id")),
                    decision="REJECTED",
                    alert_tier="NONE",
                    score_final=0.0,
                    price=price,
                    total_cost=price,
                    revente_retenue=0.0,
                    margin=0.0,
                    multiple=0.0,
                    stage_reached="B0",
                    stop_reason=f"goût Rita {taste_score * 100:.0f}% sur la vignette"
                ))
                q_tri.task_done()
                continue

            # Priorité dans q_ouvrir : prestige de marque et distinctivité (goût Rita si actif)
            tier_boost = 0.30 if rule_res.tier >= 3.0 else (0.15 if rule_res.tier >= 1.5 else 0.0)
            priority_taste = (taste_score if (taste_score is not None and taste_filter_enabled) else 0.50)
            priority_val = -(priority_taste + tier_boost)
            cnt = next(priority_counter)
            put_priority_queue_drop_lowest(q_ouvrir, priority_val, cnt, (item, search_def, domain, country))
            q_tri.task_done()

        except Exception:
            logger.exception("Erreur dans TRI worker")
            try:
                q_tri.task_done()
            except Exception:
                pass


# =====================================================================
# ÉTAGE 3 : OUVREUR (1 thread réseau ciblé haute priorité) (Section 1, 3 & 4)
# =====================================================================

def ouvreur_worker(
    stop_event: threading.Event,
    q_ouvrir: queue.PriorityQueue,
    q_juge: queue.Queue,
    scrapers_by_domain: Dict[str, List[VintedScraper]],
    db: DatabaseManager,
    stats: PipelineStats
):
    """
    Prend les annonces dans q_ouvrir par ordre de goût Rita décroissant.
    Appelle fetch_item_details en haute priorité UNIQUEMENT si nécessaire,
    puis exécute le full_filter et passe à q_juge.
    """
    logger.info("🔍 Étage OUVREUR démarré (1 thread haute priorité).")

    while not stop_event.is_set():
        try:
            try:
                p_val, cnt, payload = q_ouvrir.get(timeout=0.5)
            except queue.Empty:
                continue

            item, search_def, domain, country = payload
            item_id = item.get("id")

            if db.is_item_notified(item_id):
                q_ouvrir.task_done()
                continue

            # N'appelle fetch_item_details que si le pays du vendeur ou la description manque
            need_fetch = (not item.get("seller_country")) or (not item.get("description"))

            if need_fetch:
                scraper_list = scrapers_by_domain.get(domain, [])
                if scraper_list:
                    scraper = scraper_list[0]
                    item = scraper.fetch_item_details(item, priority="high")

            # PASSE 2 : FULL_FILTER
            price = float(item.get("price", {}).get("amount", 0.0))
            is_match_full, reason_full = DealEvaluator.full_filter(item, search_def)
            if not is_match_full:
                log_verdict(False, item, price, reason_full)
                stats.record_verdict(time.time() - item.get("_discovered_at", time.time()))
                q_ouvrir.task_done()
                continue

            stats.record_opened()

            config = load_config()
            shipping_costs = config.get("shipping_costs", {"fr": 3.0, "default_foreign": 8.0})
            seller_c = (item.get("seller_country") or "").lower().strip()
            if seller_c and seller_c in shipping_costs:
                shipping_cost = float(shipping_costs[seller_c])
                display_country = seller_c
            else:
                shipping_cost = float(shipping_costs.get("default_foreign", 8.0))
                display_country = country

            item["_shipping_cost"] = shipping_cost
            item["_display_country"] = display_country

            put_queue_drop_oldest(q_juge, (item, search_def, domain, country), "q_juge")
            q_ouvrir.task_done()

        except Exception:
            logger.exception("Erreur dans OUVREUR worker")
            try:
                q_ouvrir.task_done()
            except Exception:
                pass


# =====================================================================
# ÉTAGE 4 : JUGE (Pool de 4 workers) (Section 1)
# =====================================================================

def juge_worker(
    worker_id: int,
    stop_event: threading.Event,
    q_juge: queue.Queue,
    notifier: TelegramNotifier,
    db: DatabaseManager,
    stats: PipelineStats,
    scrapers_by_domain: Optional[Dict[str, List[VintedScraper]]] = None
):
    """
    Exécute le pipeline décisionnel v2 complet et l'envoi d'alerte Telegram,
    en réutilisant l'embedding et les calculs déjà faits.
    """
    logger.debug(f"⚖️ JUGE worker #{worker_id} démarré.")

    while not stop_event.is_set():
        try:
            try:
                task_data = q_juge.get(timeout=0.5)
            except queue.Empty:
                continue

            item, search_def, domain, country = task_data
            item_id = item.get("id")

            with seen_items_lock:
                if db.is_item_notified(item_id):
                    q_juge.task_done()
                    continue
                price = float(item.get("price", {}).get("amount", 0.0))
                title = item.get("title", "")
                db.mark_item_notified(item_id, domain=domain, search_id=search_def.get("id", ""), title=title, price=price)

            rule_res = item.get("_rule_res")
            search_name = search_def.get("name", "Recherche")
            display_country = item.get("_display_country", country)
            shipping_cost = float(item.get("_shipping_cost", 3.0))

            evaluate_and_notify_v2_worker(
                item=item,
                rule_res=rule_res,
                search_name=search_name,
                domain=domain,
                display_country=display_country,
                price=price,
                shipping_cost=shipping_cost,
                notifier=notifier,
                db=db,
                search_id=search_def.get("id", ""),
                scrapers_by_domain=scrapers_by_domain
            )

            discovered_at = item.get("_discovered_at", time.time())
            stats.record_verdict(time.time() - discovered_at)
            q_juge.task_done()

        except Exception:
            logger.exception("Erreur dans JUGE worker")
            try:
                q_juge.task_done()
            except Exception:
                pass


# =====================================================================
# ANALYSE DÉCISIONNELLE V2 & NOTIFICATION (Lots 1 à 8)
# =====================================================================

def evaluate_and_notify_v2_worker(
    item: Dict[str, Any],
    rule_res: RuleResult,
    search_name: str,
    domain: str,
    display_country: str,
    price: float,
    shipping_cost: float,
    notifier: TelegramNotifier,
    db: DatabaseManager,
    search_id: str,
    scrapers_by_domain: Optional[Dict[str, List[VintedScraper]]] = None
):
    """
    Pipeline décisionnel v2 réutilisant l'embedding précalculé pour un temps record :
    - Étage B : Vision locale FashionCLIP (réutilisation embedding)
    - Étage C : Marché & Revente quantile + Comparables
    - Étage D : Signaux annonce
    - Décision : Score final pondéré
    - Étage E : Contrôle final optionnel
    - Alerte Telegram
    """
    config = load_config()
    item_id = str(item.get("id") or item.get("item_id") or "")
    title = str(item.get("title") or "")

    t0_clip = time.perf_counter()
    clip_scorer = get_clip_scorer(config)
    clip_res = clip_scorer.evaluate_item(item, rules_category=rule_res.category)
    clip_ms = (time.perf_counter() - t0_clip) * 1000

    if clip_res.hard_reject:
        stop_reason = clip_res.reasons[0] if clip_res.reasons else "Rejet visuel CLIP"
        log_verdict(False, item, price, stop_reason)
        tc = calculate_total_cost(price, display_country, shipping_cost)
        record_decision(DecisionResult(
            item_id=item_id, decision="REJECTED", alert_tier="NONE",
            score_final=rule_res.score, price=price, total_cost=tc,
            revente_retenue=0.0, margin=0.0, multiple=0.0,
            stage_reached="B", stop_reason=stop_reason
        ))
        return

    # Goût Rita & Comparables
    taste_score = item.get("_taste_score")
    if taste_score is None:
        taste_score = get_taste_score(clip_res.embedding, clip_res.clip_category or rule_res.category)

    favourite_matches = find_top_matching_favourites(clip_res.embedding, top_k=2) if clip_res.embedding is not None else []

    # Contrôle basiques des lignes diffusion : taste_score < 0.5 -> rejet
    if (
        rule_res.category in DIFFUSION_BASIC_CATEGORIES
        and is_diffusion_target_brand(rule_res.brand_canonical, rule_res.brand_line, str(item.get("brand_title") or item.get("brand") or ""))
    ):
        diff_reject = False
        stop_reason = ""
        if taste_score is not None:
            if taste_score < 0.5:
                diff_reject = True
                stop_reason = f"Basique ligne diffusion rejeté : Goût Rita insuffisant ({taste_score * 100:.0f}% < 50%)"
        else:
            if clip_res.distinct_pct < 0.8:
                diff_reject = True
                stop_reason = f"Basique ligne diffusion rejeté : distinct_pct ({clip_res.distinct_pct:.2f} < 0.80)"

        if diff_reject:
            log_verdict(False, item, price, f"basique, goût Rita {taste_score * 100:.0f}%" if taste_score is not None else "basique sans originalité")
            tc = calculate_total_cost(price, display_country, shipping_cost)
            record_decision(DecisionResult(
                item_id=item_id, decision="REJECTED", alert_tier="NONE",
                score_final=0.0, price=price, total_cost=tc,
                revente_retenue=0.0, margin=0.0, multiple=0.0,
                stage_reached="A", stop_reason=stop_reason
            ))
            return

    # Étage C : Marché & Revente en direct (LiveMarket Check)
    t0_market = time.perf_counter()
    record_market_listing(
        item,
        category=clip_res.clip_category,
        brand_canonical=rule_res.brand_canonical,
        brand_line=rule_res.brand_line,
        size_norm=rule_res.size_normalized,
        distinct_score=clip_res.distinct_score
    )

    # Confrontation réelle au marché Vinted en direct (LiveMarket Check sans plafond)
    live_market_data = None
    if scrapers_by_domain:
        scraper_list = scrapers_by_domain.get(domain) or scrapers_by_domain.get("vinted.fr") or []
        if scraper_list:
            try:
                from src.scoring.live_market import get_live_market_service
                live_service = get_live_market_service()
                live_market_data = live_service.get_live_market_data(
                    brand=rule_res.brand_canonical,
                    category=clip_res.clip_category,
                    scraper=scraper_list[0],
                    domain=domain
                )
            except Exception as e:
                logger.debug(f"Erreur LiveMarket: {e}")

    mkt_med = market_median(rule_res.brand_canonical, rule_res.brand_line, clip_res.clip_category)
    if live_market_data and live_market_data.get("median_price"):
        mkt_med = float(live_market_data["median_price"])

    comp_matcher = get_comparables_matcher()
    comp_price = 0.0
    comparables = []
    if clip_res.embedding is not None:
        comp_price, comparables = comp_matcher.find_comparables(clip_res.embedding, category=clip_res.clip_category)

    resale_res = estimate_resale_price(
        item=item,
        rules_category=rule_res.category,
        brand_canonical=rule_res.brand_canonical,
        brand_line=rule_res.brand_line,
        tier=rule_res.tier,
        size_norm=rule_res.size_normalized,
        bonus_score=sum(rule_res.bonus_hits.values()),
        malus_score=sum(rule_res.malus_hits.values()),
        clip_category=clip_res.clip_category,
        material_top=clip_res.material_top,
        distinct_score=clip_res.distinct_score,
        distinct_pct=clip_res.distinct_pct,
        taste_score=taste_score,
        embedding=clip_res.embedding,
        comp_price=comp_price,
        config=config,
        live_market=live_market_data
    )
    market_ms = (time.perf_counter() - t0_market) * 1000

    # Étage D : Signaux annonce
    t0_sig = time.perf_counter()
    signals_res = evaluate_listing_signals(
        item=item,
        tier=rule_res.tier,
        label_detected=clip_res.label_detected,
        config=config
    )
    signals_ms = (time.perf_counter() - t0_sig) * 1000

    # Décision centrale
    dec_res = make_decision(
        item_id=item_id,
        price=price,
        rule_score=rule_res.score,
        distinct_score=clip_res.distinct_score,
        revente_retenue=resale_res.revente_retenue,
        market_median_price=mkt_med,
        listing_signal_score=signals_res.score,
        country=display_country,
        shipping_cost=shipping_cost,
        stock_photo_score=clip_res.stock_photo_score,
        damage_score=clip_res.damage_score,
        distinct_pct=clip_res.distinct_pct,
        taste_score=taste_score,
        config=config,
        execution_times={
            "rules_ms": 0.3,
            "clip_ms": clip_ms,
            "market_ms": market_ms,
            "signals_ms": signals_ms,
            "decision_ms": 0.5
        },
        resale_details={
            **resale_res.details,
            "clip": {
                "condition_desc": clip_res.condition_desc,
                "condition_level": clip_res.condition_level,
                "damage_score": clip_res.damage_score
            }
        }
    )

    taste_str = f"{taste_score * 100:.0f}%" if taste_score is not None else "N/A"
    logger.debug(
        f"📊 [Décision v2] [{display_country.upper()}] '{title[:35]}' : "
        f"Décision={dec_res.decision} ({dec_res.alert_tier}) | "
        f"Score={dec_res.score_final:.1f}/100 | "
        f"Goût Rita={taste_str} | "
        f"Revente={dec_res.revente_retenue:.2f}€ | "
        f"Coût={dec_res.total_cost:.2f}€ -> MARGE={dec_res.margin:+.2f}€ ({dec_res.multiple:.1f}x) | "
        f"Motif={dec_res.stop_reason or 'Validé'}"
    )

    if dec_res.decision != "VALIDATED":
        log_verdict(False, item, price,
            f"{dec_res.stop_reason or 'refusé'} | goût Rita {taste_str}, score {dec_res.score_final:.0f}/100, "
            f"revente ~{dec_res.revente_retenue:.0f}€ pour {dec_res.total_cost:.0f}€ payés port compris")
        return

    # Si config "alert_only_pepites" actif
    if config.get("alert_only_pepites", False) and dec_res.alert_tier != "PEPITE":
        log_verdict(False, item, price, "pas assez fort (mode pépites seules)")
        return

    # Étage E optionnel : Contrôle final (si activé)
    final_notes = None
    if config.get("final_check", "off") != "off":
        photo_urls = select_up_to_3_photos(item)
        final_res = perform_final_check(item, photo_urls, config)
        if final_res.enabled:
            if not final_res.verified:
                final_notes = "Non vérifié"
            elif final_res.defects_detected or not final_res.authentic:
                log_verdict(False, item, price, f"contrôle final : {final_res.notes}")
                return
            else:
                final_notes = f"Vérifié ({final_res.confidence:.0f}%) : {final_res.notes}"

    # Alerte Telegram
    notifier.send_v2_deal_alert(
        item=item,
        decision_res=dec_res,
        comparables=comparables,
        search_name=search_name,
        domain=domain,
        country=display_country,
        shipping_cost=shipping_cost,
        final_check_notes=final_notes,
        taste_score=taste_score,
        favourite_matches=favourite_matches
    )

    # Sauvegarde de l'annonce et photos pour feedback et vérification d'authenticité (Legit Check)
    try:
        db.save_deal_alert(
            item=item,
            search_name=search_name,
            domain=domain,
            vision_result={"score": dec_res.score_final, "verdict": dec_res.decision}
        )
    except Exception as e:
        logger.debug(f"Erreur sauvegarde deal_alert #{item_id}: {e}")

    direct_url = item.get("url") or f"https://www.{domain}/items/{item_id}"
    log_verdict(True, item, price,
        f"goût Rita {taste_str}, revente ~{dec_res.revente_retenue:.0f}€, marge +{dec_res.margin:.0f}€ → Telegram | {direct_url}")


def evaluate_and_notify_ai_worker(
    item: Dict[str, Any],
    search_name: str,
    domain: str,
    display_country: str,
    price: float,
    shipping_cost: float,
    min_margin_eur: float,
    message_id: Optional[int],
    vision_evaluator: Any,
    notifier: Any,
    db: Any,
    search_id: str
):
    """Fonction conservée pour la rétrocompatibilité des tests."""
    if vision_evaluator and hasattr(vision_evaluator, "evaluate_deal"):
        res = vision_evaluator.evaluate_deal(item, price, min_margin_eur=min_margin_eur)
        resale = float(res.get("resale_estimate_eur") or 0.0)
        total_cost = price + shipping_cost
        margin = resale - total_cost
        if message_id and notifier and hasattr(notifier, "edit_deal_alert_result"):
            notifier.edit_deal_alert_result(message_id=message_id, vision_result=res, item=item, resale_estimate=resale, margin=margin)
        elif notifier and hasattr(notifier, "send_deal_alert"):
            if res.get("verdict") not in ("REJECT", "REJECTED") and res.get("score", 0) >= 70:
                notifier.send_deal_alert(item, res, search_name=search_name, domain=domain)
        if db and hasattr(db, "save_deal_alert"):
            db.save_deal_alert(item, search_name=search_name, domain=domain, vision_result=res)


# =====================================================================
# BOUCLE PRINCIPALE ET ORCHESTRATION DU BOT
# =====================================================================

def run_bot(single_pass: bool = False):
    """Boucle principale multithreadée du bot multi-pays avec architecture en chaîne."""
    process_lock = ProcessLock("bot.lock")
    if not process_lock.acquire():
        logger.error("❌ ERREUR : Une instance du bot Vinted est DÉJÀ en cours d'exécution (bot.lock actif) !")
        logger.error("Veuillez arrêter l'autre instance avant d'en relancer une nouvelle.")
        sys.exit(1)

    config = load_config()
    db = DatabaseManager()
    seen_items = db.get_seen_items()
    logger.info(f"🟢 Database chargée : {len(seen_items)} articles uniques enregistrés en cache.")

    session_cookie = config.get("vinted_session", {}).get("session_cookie")
    proxies_list = config.get("proxies", [])

    # Initialisation des SessionManagers, RateLimiters (>= 3s) et Scrapers (Section 4 & 5)
    scrapers_by_domain: Dict[str, List[VintedScraper]] = {}
    scraper_index_by_domain: Dict[str, int] = {}

    for c, domain in COUNTRY_DOMAINS.items():
        scraper_index_by_domain[domain] = 0
        if not proxies_list:
            s_mgr = VintedSessionManager(domain=domain, session_cookie=session_cookie, country=c)
            r_lim = VintedRateLimiter(min_interval_seconds=3.0)
            scrapers_by_domain[domain] = [VintedScraper(s_mgr, rate_limiter=r_lim)]
        else:
            scrapers_by_domain[domain] = []
            for p in proxies_list:
                s_mgr = VintedSessionManager(domain=domain, session_cookie=session_cookie, country=c, proxy=p)
                r_lim = VintedRateLimiter(min_interval_seconds=3.0)
                scrapers_by_domain[domain].append(VintedScraper(s_mgr, rate_limiter=r_lim))
            logger.info(f"🌐 Domaine {domain} : {len(proxies_list)} proxies configurés avec rate limiters dédiés.")

    notifier = TelegramNotifier(config.get("telegram", {}), session_config=config.get("vinted_session", {}))
    in_demand_tracker = InDemandTracker(check_delay_seconds=1200, min_favourites=7)

    # Préchargement du modèle de vision et des comparables
    logger.info("🧠 Initialisation du modèle de vision et de l'index boutique...")
    get_clip_scorer(config)
    get_comparables_matcher()

    # Démarrage de l'écouteur interactif Telegram
    cmd_handler = TelegramCommandHandler(config.get("telegram", {}), db_manager=db)
    if cmd_handler.is_valid():
        cmd_handler.start()
        logger.info("🤖 Écouteur Telegram interactif actif.")

    # Files inter-étages (Section 1)
    q_tri = queue.Queue(maxsize=500)
    q_ouvrir = queue.PriorityQueue(maxsize=200)
    q_juge = queue.Queue(maxsize=200)
    priority_counter = itertools.count()

    stats = PipelineStats(q_tri, q_ouvrir, q_juge)
    stop_event = threading.Event()

    global_countries = [c.lower() for c in config.get("countries", ["fr"])]
    first_run_countries: Set[str] = set(global_countries)

    # 1. Démarrage du pool JUGE (4 workers)
    juge_threads = []
    for i in range(4):
        t = threading.Thread(
            target=juge_worker,
            args=(i + 1, stop_event, q_juge, notifier, db, stats, scrapers_by_domain),
            name=f"JUGE-{i+1}",
            daemon=True
        )
        t.start()
        juge_threads.append(t)
    logger.info("⚖️ Pool JUGE actif : 4 workers.")

    # 2. Démarrage de l'OUVREUR (1 thread haute priorité)
    ouvreur_thread = threading.Thread(
        target=ouvreur_worker,
        args=(stop_event, q_ouvrir, q_juge, scrapers_by_domain, db, stats),
        name="OUVREUR",
        daemon=True
    )
    ouvreur_thread.start()

    # 3. Démarrage du pool de TRI (4 threads)
    tri_threads = []
    for i in range(4):
        t = threading.Thread(
            target=tri_worker,
            args=(i + 1, stop_event, q_tri, q_ouvrir, priority_counter, db, stats),
            name=f"TRI-{i+1}",
            daemon=True
        )
        t.start()
        tri_threads.append(t)
    logger.info("⚡ Pool TRI actif : 4 workers (0 requête Vinted).")

    # 4. Démarrage du RADAR (1 thread producteur)
    radar_thread = threading.Thread(
        target=radar_worker,
        args=(stop_event, scrapers_by_domain, scraper_index_by_domain, db, seen_items, in_demand_tracker, first_run_countries, q_tri, q_ouvrir, q_juge, stats),
        name="RADAR",
        daemon=True
    )
    radar_thread.start()

    logger.info(f"🚀 Bot Vinted Haute Performance démarré sur : {', '.join(c.upper() for c in global_countries)}")

    try:
        while not stop_event.is_set():
            # Traitement des favoris du Radar In-Demand à 20 minutes
            domain_fr = COUNTRY_DOMAINS.get("fr", "vinted.fr")
            active_scrapers = {domain_fr: scrapers_by_domain[domain_fr][0]}
            in_demand_tracker.process_due_items(active_scrapers, notifier, db)

            if single_pass:
                time.sleep(15)
                break

            time.sleep(10)

    except KeyboardInterrupt:
        logger.info("Arrêt du bot par l'utilisateur (Ctrl+C). Arrêt propre de tous les étages...")
    finally:
        stop_event.set()
        cmd_handler.stop()
        time.sleep(1)
        process_lock.release()
        logger.info("Tous les étages arrêtés proprement. Au revoir !")


def main():
    parser = argparse.ArgumentParser(description="Bot Vinted Sniper Multi-Pays & Multi-Thread avec Telegram Alerts")
    parser.add_argument("--test-telegram", action="store_true", help="Envoie un message de test sur Telegram")
    parser.add_argument("--once", action="store_true", help="Exécute une seule boucle de vérification et s'arrête")
    args = parser.parse_args()

    if args.test_telegram:
        config = load_config()
        notifier = TelegramNotifier(config.get("telegram", {}))
        if notifier.send_test_message():
            logger.info("✅ Message de test envoyé avec succès !")
        else:
            logger.error("❌ Échec envoi message test Telegram.")
        return

    run_bot(single_pass=args.once)


if __name__ == "__main__":
    main()
