import logging
import json
from typing import Dict, Any

logger = logging.getLogger("VintedBot.DatasetAnalyzer")

class DatasetAnalyzer:
    """Analyse les données d'évaluation (feedback) pour extraire les règles gagnantes pour l'Auto-Buy."""

    def __init__(self, db_manager):
        self.db = db_manager

    def generate_report(self) -> str:
        """Génère un rapport texte clair des évaluations enregistrées."""
        if not self.db:
            return "❌ Base de données non connectée."

        stats = self.db.get_feedback_stats()
        total = stats.get("TOTAL", 0)

        if total == 0:
            return (
                "📊 <b>DATASET D'APPRENTISSAGE AUTO-BUY</b>\n\n"
                "Aucune évaluation enregistrée pour le moment.\n"
                "👉 Cliquez sur <b>🎯 🟢 MUST BUY</b>, <b>🤔 🟡 AVIS MAMA</b> ou <b>❌ 🔴 REJET</b> "
                "sous les alertes Telegram pour entraîner le bot !"
            )

        must_buy = stats.get("MUST_BUY", 0)
        wife_opinion = stats.get("NEED_WIFE_OPINION", 0)
        rejected = stats.get("REJECTED", 0)

        must_buy_pct = (must_buy / total * 100) if total > 0 else 0
        wife_pct = (wife_opinion / total * 100) if total > 0 else 0
        reject_pct = (rejected / total * 100) if total > 0 else 0

        report = (
            f"📊 <b>RAPPORT DU DATASET D'APPRENTISSAGE AUTO-BUY</b>\n\n"
            f"• <b>Total des annonces évaluées :</b> {total}\n\n"
            f"🎯 <b>🟢 MUST BUY (Pépites à acheter direct) :</b> {must_buy} ({must_buy_pct:.1f}%)\n"
            f"🤔 <b>🟡 AVIS MAMA (Appréciation requise) :</b> {wife_opinion} ({wife_pct:.1f}%)\n"
            f"❌ <b>🔴 REJET (Faux bons plans) :</b> {rejected} ({reject_pct:.1f}%)\n\n"
            f"<i>💡 Plus vous évaluez les alertes reçues sur Telegram, plus le bot affine la détection automatique des pépites !</i>"
        )
        return report
