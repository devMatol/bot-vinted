import sqlite3
import os
import logging
import json
from typing import Set, Optional, Dict, Any, List, Tuple

logger = logging.getLogger("VintedBot.Database")

class DatabaseManager:
    """Gère le stockage SQLite des articles vus, notifiés et des évaluations pour l'apprentissage Auto-Buy."""

    def __init__(self, db_path: str = "vinted_bot.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        return conn

    def _init_db(self):
        """Initialise les tables si elles n'existent pas et effectue les migrations nécessaires."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Table des articles vus (seen_items) avec support multi-pays (domain, item_id)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_items (
                    domain TEXT DEFAULT 'vinted.fr',
                    item_id INTEGER,
                    title TEXT,
                    price REAL,
                    search_id TEXT,
                    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (domain, item_id)
                )
            """)

            # Migration douce si vu_items existait avec item_id seul en PRIMARY KEY sans domain
            cursor.execute("PRAGMA table_info(seen_items)")
            columns = [col[1] for col in cursor.fetchall()]
            if "domain" not in columns:
                try:
                    cursor.execute("ALTER TABLE seen_items ADD COLUMN domain TEXT DEFAULT 'vinted.fr'")
                except Exception as e:
                    logger.debug(f"Erreur ajout colonne domain dans seen_items: {e}")

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_seen_items_seen_at ON seen_items(seen_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_seen_items_domain_item ON seen_items(domain, item_id)
            """)

            # 2. Table des articles notifiés (notified_items) distincte de seen_items (Phase 2.1)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notified_items (
                    item_id INTEGER PRIMARY KEY,
                    domain TEXT DEFAULT 'vinted.fr',
                    search_id TEXT,
                    title TEXT,
                    price REAL,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_notified_items_at ON notified_items(notified_at)
            """)

            # Migration si notified_items avait PRIMARY KEY (domain, item_id)
            cursor.execute("PRAGMA table_info(notified_items)")
            notified_cols = cursor.fetchall()
            # Si la table a été créée avec l'ancien schéma composite, on s'assure qu'un index unique sur item_id existe
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_notified_items_item_id ON notified_items(item_id)
            """)

            # 3. Table d'apprentissage et de feedback pour l'Auto-Buy
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deal_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT DEFAULT 'vinted.fr',
                    item_id INTEGER,
                    search_name TEXT,
                    title TEXT,
                    price REAL,
                    brand TEXT,
                    condition TEXT,
                    seller_rating REAL,
                    description TEXT,
                    photo_urls TEXT,
                    score REAL DEFAULT 0.0,
                    verdict TEXT DEFAULT '',
                    classification TEXT DEFAULT 'ALERT_SENT',
                    evaluated_by TEXT DEFAULT 'System',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(domain, item_id)
                )
            """)

            # Migration douce des colonnes deal_feedback si déjà existante
            cursor.execute("PRAGMA table_info(deal_feedback)")
            feedback_cols = [col[1] for col in cursor.fetchall()]
            for col_name, col_def in [
                ("domain", "TEXT DEFAULT 'vinted.fr'"),
                ("score", "REAL DEFAULT 0.0"),
                ("verdict", "TEXT DEFAULT ''"),
            ]:
                if col_name not in feedback_cols:
                    try:
                        cursor.execute(f"ALTER TABLE deal_feedback ADD COLUMN {col_name} {col_def}")
                    except Exception as e:
                        logger.debug(f"Erreur migration colonne {col_name} dans deal_feedback: {e}")

            # Index unique requis par les clauses ON CONFLICT(domain, item_id) (ancienne table : item_id UNIQUE seul)
            try:
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_deal_feedback_domain_item ON deal_feedback(domain, item_id)")
            except Exception as e:
                logger.warning(f"Impossible de créer l'index unique deal_feedback(domain, item_id): {e}")

            # 4. Table de suivi de la consommation de tokens Gemini et des coûts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date_str TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    candidates_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    model TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_date ON token_usage(date_str)
            """)

            conn.commit()
        logger.info(f"Database initialisée sur '{self.db_path}' (tables seen_items, notified_items, deal_feedback, token_usage)")

    # --- SEEN ITEMS ---

    def is_item_seen(self, item_id: int, domain: Optional[str] = None) -> bool:
        """Vérifie si un article a déjà été découvert (l'item_id Vinted est global multi-pays)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM seen_items WHERE item_id = ?", (item_id,))
            return cursor.fetchone() is not None

    def mark_item_seen(self, item_id: int, domain: str = "vinted.fr", title: str = "", price: float = 0.0, search_id: str = ""):
        """Enregistre un article comme vu (item_id unique global, domain à titre indicatif)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO seen_items (item_id, domain, title, price, search_id)
                VALUES (?, ?, ?, ?, ?)
            """, (item_id, domain, title, price, search_id))
            conn.commit()

    def get_seen_items(self, limit: int = 50000) -> Set[int]:
        """Récupère l'ensemble des item_id récents pour filtrage ultra-rapide O(1) en mémoire."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT item_id FROM seen_items ORDER BY seen_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return {row[0] for row in rows}

    def get_seen_item_ids(self, limit: int = 50000) -> Set[int]:
        """Alias rétro-compatible : retourne les item_id récents."""
        return self.get_seen_items(limit)

    # --- NOTIFIED ITEMS (Phase 2.1 & Correction 1) ---

    def is_item_notified(self, item_id: int, domain: Optional[str] = None) -> bool:
        """Vérifie si une alerte a déjà été envoyée pour cet item_id (clé unique globale tous domaines confondus)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM notified_items WHERE item_id = ?", (item_id,))
            return cursor.fetchone() is not None

    def mark_item_notified(self, item_id: int, domain: str = "vinted.fr", search_id: str = "", title: str = "", price: float = 0.0):
        """Enregistre un article comme ayant fait l'objet d'une alerte Telegram (item_id unique)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notified_items (item_id, domain, search_id, title, price)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO NOTHING
            """, (item_id, domain, search_id, title, price))
            conn.commit()
            logger.debug(f"Article marqué notifié : #{item_id} (sur {domain})")

    # --- DEAL FEEDBACK & APPRENTISSAGE (Phase 2.5 & 2.6) ---

    def save_deal_alert(
        self,
        item: Dict[str, Any],
        search_name: str,
        domain: str = "vinted.fr",
        vision_result: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Sauvegarde l'annonce complète lors de l'envoi de l'alerte Telegram (Phase 2.5).
        Contient titre, prix, marque, état, note vendeur, description, photos, score et verdict IA.
        """
        item_id = item.get("id")
        if not item_id:
            return False

        title = item.get("title", "")
        price_obj = item.get("price")
        price = 0.0
        if isinstance(price_obj, dict):
            price = float(price_obj.get("amount", 0.0))
        elif isinstance(price_obj, (int, float, str)):
            try:
                price = float(price_obj)
            except ValueError:
                price = 0.0

        brand = item.get("brand_title", "")
        condition = item.get("status", "")
        description = item.get("description", "")
        user_info = item.get("user") or {}
        seller_rating = 0.0
        feedback_rep = user_info.get("feedback_reputation")
        if feedback_rep is not None:
            try:
                seller_rating = float(feedback_rep) * 5.0
            except ValueError:
                pass

        photos = item.get("photos") or []
        photo_urls = [p.get("url") for p in photos if isinstance(p, dict) and p.get("url")]
        photo_urls_json = json.dumps(photo_urls, ensure_ascii=False)

        score = 0.0
        verdict = ""
        if vision_result:
            score = float(vision_result.get("score", 0.0))
            verdict = str(vision_result.get("verdict", ""))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO deal_feedback 
                (domain, item_id, search_name, title, price, brand, condition, seller_rating, description, photo_urls, score, verdict, classification, evaluated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ALERT_SENT', 'System')
                ON CONFLICT(domain, item_id) DO UPDATE SET
                    search_name=excluded.search_name,
                    title=excluded.title,
                    price=excluded.price,
                    brand=excluded.brand,
                    condition=excluded.condition,
                    seller_rating=excluded.seller_rating,
                    description=excluded.description,
                    photo_urls=excluded.photo_urls,
                    score=excluded.score,
                    verdict=excluded.verdict
            """, (domain, item_id, search_name, title, price, brand, condition, seller_rating, description, photo_urls_json, score, verdict))
            conn.commit()
            logger.debug(f"💾 Annonce complète sauvegardée pour feedback #{item_id} ({brand} - {price}€)")
            return True

    def update_deal_feedback_classification(
        self,
        item_id: int,
        classification: str,
        evaluated_by: str = "User",
        domain: Optional[str] = None
    ) -> bool:
        """Met à jour la classification suite à un clic bouton Telegram (Phase 2.5)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if domain:
                cursor.execute("""
                    UPDATE deal_feedback
                    SET classification = ?, evaluated_by = ?, source = 'telegram_click', created_at = CURRENT_TIMESTAMP
                    WHERE item_id = ? AND domain = ?
                """, (classification, evaluated_by, item_id, domain))
            else:
                cursor.execute("""
                    UPDATE deal_feedback
                    SET classification = ?, evaluated_by = ?, source = 'telegram_click', created_at = CURRENT_TIMESTAMP
                    WHERE item_id = ?
                """, (classification, evaluated_by, item_id))

            if cursor.rowcount == 0:
                # Si la ligne n'existait pas encore, l'insérer au minimum
                target_domain = domain or "vinted.fr"
                cursor.execute("""
                    INSERT INTO deal_feedback (domain, item_id, classification, evaluated_by, source)
                    VALUES (?, ?, ?, ?, 'telegram_click')
                    ON CONFLICT(domain, item_id) DO UPDATE SET
                        classification=excluded.classification,
                        evaluated_by=excluded.evaluated_by,
                        source='telegram_click',
                        created_at=CURRENT_TIMESTAMP
                """, (target_domain, item_id, classification, evaluated_by))

            conn.commit()
            logger.info(f"Feedback #{item_id} mis à jour : {classification} par {evaluated_by}")
            return True

    def save_deal_feedback(
        self, 
        item_id: int, 
        classification: str, 
        search_name: str = "", 
        title: str = "", 
        price: float = 0.0, 
        brand: str = "", 
        condition: str = "", 
        seller_rating: float = 0.0, 
        description: str = "", 
        photo_urls: List[str] = None,
        evaluated_by: str = "User",
        domain: str = "vinted.fr",
        score: float = 0.0,
        verdict: str = ""
    ) -> bool:
        """Enregistre ou met à jour une évaluation d'annonce pour l'apprentissage Auto-Buy."""
        photo_urls_json = json.dumps(photo_urls or [], ensure_ascii=False)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO deal_feedback 
                (domain, item_id, search_name, title, price, brand, condition, seller_rating, description, photo_urls, score, verdict, classification, evaluated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain, item_id) DO UPDATE SET
                    classification=excluded.classification,
                    evaluated_by=excluded.evaluated_by,
                    created_at=CURRENT_TIMESTAMP
            """, (domain, item_id, search_name, title, price, brand, condition, seller_rating, description, photo_urls_json, score, verdict, classification, evaluated_by))
            conn.commit()
            logger.info(f"Feedback enregistré pour item #{item_id}: {classification}")
            return True

    def get_recent_feedback_examples(
        self, 
        search_name: str = "", 
        limit_each: int = 10
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Récupère jusqu'aux 10 derniers MUST_BUY et 10 derniers REJECTED
        de la même recherche ou catégorie pour guider l'IA (Phase 2.6).
        """
        examples: Dict[str, List[Dict[str, Any]]] = {"MUST_BUY": [], "REJECTED": []}

        with self._get_connection() as conn:
            cursor = conn.cursor()

            for target_class in ["MUST_BUY", "REJECTED"]:
                rows = []
                if search_name:
                    cursor.execute("""
                        SELECT title, price, brand, condition, description, score, verdict, classification
                        FROM deal_feedback
                        WHERE classification = ? AND search_name = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                    """, (target_class, search_name, limit_each))
                    rows = cursor.fetchall()

                # Si pas assez d'exemples spécifiques à cette recherche, compléter avec d'autres
                if len(rows) < limit_each:
                    remaining = limit_each - len(rows)
                    cursor.execute("""
                        SELECT title, price, brand, condition, description, score, verdict, classification
                        FROM deal_feedback
                        WHERE classification = ? AND (search_name != ? OR search_name IS NULL)
                        ORDER BY created_at DESC
                        LIMIT ?
                    """, (target_class, search_name or "", remaining))
                    rows.extend(cursor.fetchall())

                for r in rows:
                    examples[target_class].append({
                        "title": r[0] or "",
                        "price": r[1] or 0.0,
                        "brand": r[2] or "",
                        "condition": r[3] or "",
                        "description": (r[4] or "")[:120],
                        "score": r[5] or 0.0,
                        "verdict": r[6] or ""
                    })

        return examples

    def get_feedback_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques d'apprentissage du dataset."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT classification, COUNT(*) FROM deal_feedback WHERE classification != 'ALERT_SENT' GROUP BY classification")
            rows = cursor.fetchall()
            stats = {row[0]: row[1] for row in rows}
            cursor.execute("SELECT COUNT(*) FROM deal_feedback WHERE classification != 'ALERT_SENT'")
            stats["TOTAL"] = cursor.fetchone()[0]
            return stats

    # --- TOKEN USAGE & COÛTS GEMINI ---

    def record_token_usage(
        self,
        prompt_tokens: int,
        candidates_tokens: int,
        total_tokens: int,
        model: str = "",
        date_str: Optional[str] = None
    ):
        """Enregistre une consommation de tokens pour le suivi journalier des coûts."""
        import datetime
        target_date = date_str or datetime.date.today().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO token_usage (date_str, prompt_tokens, candidates_tokens, total_tokens, model)
                VALUES (?, ?, ?, ?, ?)
            """, (target_date, prompt_tokens, candidates_tokens, total_tokens, model))
            conn.commit()

    def get_token_usage_for_day(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Calcule les tokens consommés et le coût estimé pour une journée donnée.
        Tarifs : 0,30 $ par M en entrée, 2,50 $ par M en sortie.
        """
        import datetime
        target_date = date_str or datetime.date.today().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(candidates_tokens), 0),
                    COALESCE(SUM(total_tokens), 0),
                    COUNT(*)
                FROM token_usage
                WHERE date_str = ?
            """, (target_date,))
            row = cursor.fetchone()
            prompt_tokens = row[0]
            candidates_tokens = row[1]
            total_tokens = row[2]
            calls_count = row[3]

            # Calcul des coûts : 0.30$ / 1M prompt, 2.50$ / 1M candidates
            cost_input = (prompt_tokens / 1_000_000.0) * 0.30
            cost_output = (candidates_tokens / 1_000_000.0) * 2.50
            total_cost_usd = cost_input + cost_output

            return {
                "date": target_date,
                "calls_count": calls_count,
                "prompt_tokens": prompt_tokens,
                "candidates_tokens": candidates_tokens,
                "total_tokens": total_tokens,
                "cost_input_usd": cost_input,
                "cost_output_usd": cost_output,
                "total_cost_usd": total_cost_usd
            }
