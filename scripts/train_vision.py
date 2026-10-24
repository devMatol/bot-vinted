#!/usr/bin/env python3
"""
scripts/train_vision.py
-----------------------
Phase 3 : Script d'entraînement, d'étalonnage et d'indexation de l'IA Vision.
Exploite les annotations Telegram et les motifs de rejet précis (commentaires textuels) :
1. Indexe la banque de mémoire d'exemplaires de défauts (Few-shot / k-NN).
2. Génère dynamiquement des sondes textuelles SigLIP sur mesure à partir des raisons écrites par l'utilisateur.
3. Étalonne les seuils de veto et exporte le rapport d'apprentissage.
"""

import os
import sys

# Ajouter la racine du projet dans le PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, List

import numpy as np
import torch
from PIL import Image

# Configurer le logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("TrainVision")

DB_PATH = "vinted_bot.db"
DATASET_DIR = "data/vision_dataset"
IMAGES_DIR = os.path.join(DATASET_DIR, "images")
EMBEDDINGS_DIR = os.path.join(DATASET_DIR, "embeddings")
EXEMPLARS_NPY = os.path.join(DATASET_DIR, "defect_exemplars.npy")
EXEMPLARS_JSON = os.path.join(DATASET_DIR, "defect_exemplars.json")
PROBES_NPY = os.path.join(DATASET_DIR, "custom_defect_probes.npy")
PROBES_JSON = os.path.join(DATASET_DIR, "custom_defect_probes.json")
REPORT_JSON = os.path.join(DATASET_DIR, "vision_train_report.json")


def load_annotations(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Charge toutes les annotations enregistrées depuis SQLite."""
    if not os.path.exists(db_path):
        logger.warning(f"Base SQLite introuvable : {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, item_id, domain, flaw_type, user_comment, photo_url, local_image_path, embedding_path, annotated_by, created_at
        FROM vision_annotations
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    conn.close()

    annotations = []
    for r in rows:
        annotations.append({
            "id": r[0],
            "item_id": r[1],
            "domain": r[2],
            "flaw_type": r[3],
            "user_comment": (r[4] or "").strip(),
            "photo_url": r[5] or "",
            "local_image_path": r[6] or "",
            "embedding_path": r[7] or "",
            "annotated_by": r[8] or "User",
            "created_at": r[9] or ""
        })
    return annotations


def main():
    logger.info("🚀 Démarrage de l'entraînement et étalonnage de l'IA Vision (Phase 3)...")

    os.makedirs(DATASET_DIR, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(EMBEDDINGS_DIR, exist_ok=True)

    annotations = load_annotations(DB_PATH)
    total_annots = len(annotations)
    logger.info(f"📊 {total_annots} annotations trouvées en base.")

    if total_annots == 0:
        logger.warning("Aucune annotation trouvée. Rien à entraîner.")
        empty_report = {
            "total_annotations": 0,
            "defect_exemplars": 0,
            "custom_probes_count": 0,
            "top_reasons": [],
            "trained_at": datetime.now().isoformat()
        }
        with open(REPORT_JSON, "w", encoding="utf-8") as f:
            json.dump(empty_report, f, indent=2, ensure_ascii=False)
        return

    # 1. Initialiser le modèle OpenCLIP / SigLIP pour encoder les images et probes manquantes
    from src.scoring.clip_scorer import get_clip_scorer
    scorer = get_clip_scorer()
    model = scorer.model
    tokenizer = scorer.tokenizer

    # 2. Vérification et calcul des embeddings images manquants
    updated_embeddings = 0
    defect_exemplars = []
    all_comments = []

    for ann in annotations:
        item_id = ann["item_id"]
        flaw_type = ann["flaw_type"]
        comment = ann["user_comment"]

        if comment:
            all_comments.append(comment)

        emb_path = ann["embedding_path"]
        img_path = ann["local_image_path"]

        # Si l'image locale existe et l'embedding est manquant sur disque
        if not emb_path or not os.path.exists(emb_path):
            target_emb = os.path.join(EMBEDDINGS_DIR, f"{item_id}.npy")
            if os.path.exists(target_emb):
                emb_path = target_emb
            elif img_path and os.path.exists(img_path):
                try:
                    with Image.open(img_path) as pil_img:
                        emb = scorer.encode_pil_image(pil_img)
                        if emb is not None:
                            np.save(target_emb, emb)
                            emb_path = target_emb
                            updated_embeddings += 1
                except Exception as e:
                    logger.debug(f"Impossible d'encoder {img_path}: {e}")

        # Si l'embedding existe sur disque, l'enregistrer dans les exemplaires
        if emb_path and os.path.exists(emb_path):
            try:
                emb = np.load(emb_path).astype(np.float32)
                norm = np.linalg.norm(emb)
                if norm > 1e-6:
                    emb = emb / norm

                # Considérer comme exemplaire de défaut si flaw_type == DEFECT ou commentaire spécifique
                is_defect = (flaw_type == "DEFECT") or (len(comment) > 2 and flaw_type not in ["STYLE", "PRICE", "CHILD"])
                if is_defect:
                    defect_exemplars.append({
                        "item_id": item_id,
                        "flaw_type": flaw_type,
                        "user_comment": comment,
                        "annotated_by": ann["annotated_by"],
                        "created_at": ann["created_at"],
                        "embedding": emb
                    })
            except Exception as e:
                logger.debug(f"Erreur chargement embedding {emb_path}: {e}")

    logger.info(f"💾 {len(defect_exemplars)} exemplaires de défauts récupérés ({updated_embeddings} embeddings calculés).")

    # 3. Sauvegarder la banque d'exemplaires de défauts (k-NN)
    if defect_exemplars:
        emb_matrix = np.vstack([ex["embedding"] for ex in defect_exemplars])
        np.save(EXEMPLARS_NPY, emb_matrix)

        meta_list = [
            {
                "item_id": ex["item_id"],
                "flaw_type": ex["flaw_type"],
                "user_comment": ex["user_comment"],
                "annotated_by": ex["annotated_by"],
                "created_at": ex["created_at"]
            }
            for ex in defect_exemplars
        ]
        with open(EXEMPLARS_JSON, "w", encoding="utf-8") as f:
            json.dump(meta_list, f, indent=2, ensure_ascii=False)
        logger.info(f"✅ Banque d'exemplaires sauvegardée : {EXEMPLARS_NPY} ({emb_matrix.shape})")
    else:
        if os.path.exists(EXEMPLARS_NPY):
            os.remove(EXEMPLARS_NPY)
        if os.path.exists(EXEMPLARS_JSON):
            os.remove(EXEMPLARS_JSON)

    # 4. Génération dynamique de sondes SigLIP sur mesure à partir des commentaires rédigés
    unique_comments = list({c.strip().lower() for c in all_comments if len(c.strip()) > 2})
    logger.info(f"✍️ {len(unique_comments)} motifs écrits distincts identifiés : {unique_comments}")

    custom_probes_data = []
    custom_probes_vectors = []

    if unique_comments:
        with torch.no_grad():
            for comm in unique_comments:
                prompts = [
                    f"a photo showing a flaw or defect: {comm}",
                    f"a damaged clothing or shoe item with {comm}",
                    f"noticeable wear, tear or stain: {comm}"
                ]
                tokens = tokenizer(prompts)
                text_embs = model.encode_text(tokens)
                text_embs = text_embs / text_embs.norm(dim=-1, keepdim=True)
                mean_emb = text_embs.mean(dim=0)
                mean_emb = mean_emb / mean_emb.norm(dim=-1, keepdim=True)
                vec = mean_emb.cpu().numpy().astype(np.float32)

                custom_probes_vectors.append(vec)
                custom_probes_data.append({
                    "name": comm,
                    "prompts": prompts
                })

        if custom_probes_vectors:
            probes_matrix = np.vstack(custom_probes_vectors)
            np.save(PROBES_NPY, probes_matrix)
            with open(PROBES_JSON, "w", encoding="utf-8") as f:
                json.dump(custom_probes_data, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ Sondes personnalisées sauvegardées : {PROBES_NPY} ({probes_matrix.shape})")

    # 5. Rapport final
    report = {
        "total_annotations": total_annots,
        "defect_exemplars": len(defect_exemplars),
        "custom_probes_count": len(custom_probes_data),
        "top_reasons": unique_comments[:10],
        "trained_at": datetime.now().isoformat()
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info("🎉 Entraînement et indexation de la vision terminés avec succès !")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
