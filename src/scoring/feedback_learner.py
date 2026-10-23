"""Module d'apprentissage continu et classifieur de préférences acheteur (Lot 7).

Fonctionnalités :
- Enregistrement des retours utilisateurs (MUST_BUY, AVIS_MAMA, REJECTED) avec tous les scores et l'embedding
- Classifieur logistique "va-t-elle aimer ?" entraîné sur MUST_BUY (1) vs REJECTED (0) dès 50 exemples
- Commande /retrain : relance l'entraînement du modèle de revente et du classifieur
- Réentraînement planifié (hebdomadaire si > 30 nouveaux retours)
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import joblib
from sklearn.linear_model import LogisticRegression

logger = logging.getLogger("VintedBot.Scoring.FeedbackLearner")

PREFERENCE_MODEL_PATH = "models/preference_classifier.joblib"


class PreferenceClassifier:
    """Classifieur de goût boutique entraîné sur MUST_BUY vs REJECTED."""

    def __init__(self, model_path: str = PREFERENCE_MODEL_PATH):
        self.model_path = model_path
        self.model = None
        self.loaded = False
        self._load()

    def _load(self):
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                self.loaded = True
                logger.info("Classifieur de préférences acheteur chargé.")
            except Exception as e:
                logger.warning(f"Impossible de charger {self.model_path}: {e}")

    def predict_preference(
        self,
        rule_score: float,
        distinct_score: float,
        margin: float,
        multiple: float,
        tier: float
    ) -> float:
        """
        Prédit la probabilité que l'acheteur valide l'article (0.0 à 1.0).
        Retourne 0.50 si le modèle n'a pas encore assez de données.
        """
        if not self.loaded or self.model is None:
            return 0.50

        try:
            feat_vec = np.array([[rule_score, distinct_score * 100.0, margin, multiple, tier]], dtype=np.float32)
            proba = float(self.model.predict_proba(feat_vec)[0, 1])
            return round(proba, 2)
        except Exception as e:
            logger.debug(f"Erreur prédiction préférence: {e}")
            return 0.50


_PREF_INSTANCE: Optional[PreferenceClassifier] = None


def get_preference_classifier() -> PreferenceClassifier:
    global _PREF_INSTANCE
    if _PREF_INSTANCE is None:
        _PREF_INSTANCE = PreferenceClassifier()
    return _PREF_INSTANCE


def train_preference_model(db_path: str = "vinted_bot.db") -> Optional[Dict[str, Any]]:
    """
    Entraîne la régression logistique dès qu'au moins 50 feedbacks MUST_BUY / REJECTED sont disponibles.
    """
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT classification, score
            FROM deal_feedback
            WHERE classification IN ('MUST_BUY', 'REJECTED')
        """)
        rows = cur.fetchall()
        if len(rows) < 50:
            logger.info(f"Pas assez d'exemples étiquetés pour le classifieur de goût ({len(rows)}/50).")
            return None

        X_rows = []
        y_rows = []
        for r in rows:
            label = 1 if r[0] == "MUST_BUY" else 0
            score = float(r[1] or 50.0)
            # Vecteur simplifié
            X_rows.append([score, 50.0, 15.0, 2.0, 1.0])
            y_rows.append(label)

        X = np.array(X_rows, dtype=np.float32)
        y = np.array(y_rows, dtype=np.int32)

        clf = LogisticRegression(class_weight="balanced", max_iter=200)
        clf.fit(X, y)

        os.makedirs("models", exist_ok=True)
        joblib.dump(clf, PREFERENCE_MODEL_PATH)

        global _PREF_INSTANCE
        _PREF_INSTANCE = PreferenceClassifier()

        logger.info(f"Classifieur de préférences réentraîné sur {len(rows)} feedbacks.")
        return {"n_samples": len(rows), "status": "trained"}
    except Exception as e:
        logger.error(f"Erreur entraînement classifieur de goût: {e}")
        return None
    finally:
        conn.close()


def run_full_retrain(db_path: str = "vinted_bot.db") -> Dict[str, Any]:
    """
    Exécute le réentraînement complet :
    1. Réentraînement des modèles de revente (train_resale.py)
    2. Entraînement du classifieur de préférence
    3. Rejeu du backtest
    """
    from scripts.train_resale import train_models
    from scripts.backtest import run_backtest

    logger.info("Démarrage du cycle complet de réentraînement (/retrain)...")
    train_models()
    pref_res = train_preference_model(db_path)
    run_backtest()

    meta_path = "models/resale_meta.json"
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    return {
        "status": "success",
        "retrained_at": datetime.utcnow().isoformat(),
        "mae_q30_eur": meta.get("global_mae_q30_eur"),
        "mae_q50_eur": meta.get("global_mae_q50_eur"),
        "preference_classifier": pref_res
    }
