# 🚀 Bot Vinted v2 — Moteur de Décision Local & Sniper Multi-Pays

Bot de surveillance et d'achat-revente en temps réel sur Vinted, doté d'un **moteur de décision local, gratuit, rapide (< 1.5 s sur CPU) et calibré sur l'historique des ventes réelles de la boutique**, éliminant la dépendance et les coûts de l'API Gemini Vision.

---

## 🏗️ Architecture du Pipeline Décisionnel

Chaque annonce interceptée traverse un entonnoir ordonné du moins cher au plus cher, s'arrêtant dès le premier motif de rejet :

```
Recherche Catalogue Vinted
  │
  ├── 1. Prefilter (titre, prix catalogue, mots exclus) [ < 0.1 ms ]
  │
  ├── 2. Scraping approfondi (JSON-LD, marque, taille, état, vendeur)
  │
  ├── 3. Full Filter (re-check prix, statut, note vendeur) [ < 0.5 ms ]
  │
  ├── 4. Étage A : Règles Heuristiques (src/scoring/rules.py) [ ~0.3 ms ]
  │      ├── Rejet dur : objets non-vêtements, accessoires hors sac, contrefaçons, enfants
  │      ├── Bonus pondérés : imprimés, matières nobles, coupes, époques (Y2K/vintage), état
  │      ├── Malus pondérés : basiques, défauts, usure
  │      ├── Plafonnement basiques diffusion (<= 35) & bas unis (<= 40)
  │      └── Arrêt si score < rules_min_score (35)
  │
  └── (Tâche de fond asynchrone non-bloquante pour le scraper)
         │
         ├── 5. Étage B : Vision locale FashionCLIP (src/scoring/clip_scorer.py) [ ~550 ms / < 9 ms cache ]
         │      ├── 3 photos max (1re, 2e, dernière) téléchargées en parallèle
         │      ├── Cache disque des embeddings dans data/embeddings/{id}.npy
         │      ├── Zero-shot : catégorie, imprimé (distinct_score), matière, style, défauts
         │      ├── Rejet dur si non-vêtement/cosmétique/enfant proba > 0.5 ou usé > 0.6
         │      └── Malus suspicion photo catalogue/stock
         │
         ├── 6. Étage C : Marché & Revente (src/scoring/market.py + resale_model.py) [ ~2 ms ]
         │      ├── market_listings : médiane glissante sur 30 jours (repli marque -> catégorie)
         │      ├── Comparables visuels : recherche cosinus des 10 ventes boutique les plus proches
         │      ├── comp_price : médiane pondérée des comparables
         │      ├── Prédiction quantile HistGradientBoosting (q30 prudent & q50 médiane)
         │      └── revente_retenue = min(pred_q30, comp_price x 1.1, plafond_catégorie x palier_marque)
         │
         ├── 7. Étage D : Signaux Annonce & Vendeur (src/scoring/listing_signals.py) [ < 1 ms ]
         │      ├── Fraîcheur (< 10 min bonus fort) & Vélocité favoris (radar In-Demand)
         │      ├── Vendeur pressé (urgence, déménagement, vide-dressing)
         │      ├── Vendeur sous-informé (titre générique sur marque premium)
         │      └── Détection de lots / bundles & qualité d'annonce
         │
         ├── 8. Décision Finale (src/scoring/decision.py) [ < 0.5 ms ]
         │      ├── coût_total = prix + port (selon pays) + 0.70 + 5 % du prix
         │      ├── marge = revente_retenue - coût_total
         │      ├── multiple = revente_retenue / coût_total
         │      ├── score_final (0-100) : combinaison pondérée (règles, distinctivité, marge, marché, signaux)
         │      ├── Validation si : score_final >= 70 ET marge >= 15€ ET multiple >= 2.0x
         │      ├── Niveaux : 🟢 PÉPITE (score >= 85 & mult >= 3.0x) ou 🟡 À REGARDER (70-84)
         │      └── Audit enregistré dans la table SQLite decisions
         │
         ├── 9. Étage E (Optionnel) : Contrôle Final IA (src/scoring/final_check.py)
         │      └── "off" (par défaut), "ollama" (local) ou "gemini" (prompt court authenticité/défauts)
         │
         └── 10. Alerte Telegram enrichie (src/notifier.py)
                ├── Photo, titre, prix + coût total, revente et marge nette
                ├── Score final, niveau (🟢 / 🟡), catégorie
                ├── 3 ventes comparables de la boutique (titre court + prix)
                ├── 2 points forts explicatifs
                ├── Lien direct 1-clic pour ouvrir l'article sur Vinted
                └── Boutons interactifs : MUST BUY, AVIS MAMA, REJET
```

---

## ⚙️ Configuration (`config.json`)

Toutes les règles, seuils et listes de mots sont configurables dynamiquement sans modifier le code :

| Clé | Défaut | Description |
|---|---|---|
| `bot_enabled` | `true` | Interrupteur général du bot (ON/OFF). |
| `final_min_score` | `70.0` | Score minimal global requis pour valider une alerte. |
| `min_margin_eur` | `15.0` | Marge nette minimale requise en euros (après port et frais Vinted). |
| `min_multiple` | `2.0` | Multiple minimal de revente requis (`revente / coût_total`). |
| `alert_only_pepites` | `false` | Si `true`, n'envoie que les alertes de niveau 🟢 PÉPITE. |
| `rules_min_score` | `35.0` | Seuil d'arrêt immédiat à l'Étage A (règles heuristiques). |
| `decision_weights` | `{ "rules": 0.25, "distinct": 0.25, "margin": 0.30, "market": 0.10, "signals": 0.10 }` | Pondération des composantes du score final. |
| `clip_model_name` | `"hf-hub:Marqo/marqo-fashionCLIP"` | Modèle CLIP utilisé pour la vision locale. |
| `clip_num_threads` | `4` | Nombre de threads CPU dédiés à l'inférence FashionCLIP. |
| `clip_max_photos` | `3` | Nombre maximal de photos analysées par article (1re, 2e, dernière). |
| `clip_embeddings_dir` | `"data/embeddings"` | Répertoire de cache disque des embeddings (512-d `.npy`). |
| `clip_damage_threshold` | `0.6` | Seuil de rejet immédiat pour vêtement usé ou endommagé. |
| `clip_stock_photo_threshold`| `0.5` | Seuil d'application du malus suspicion de photo de stock/catalogue. |
| `clip_reject_proba_threshold`| `0.5` | Seuil de rejet pour les objets non-vêtements, cosmétiques et enfants. |
| `final_check` | `"off"` | Contrôle final optionnel : `"off"`, `"gemini"` ou `"ollama"`. |
| `final_check_max_per_hour` | `20` | Plafond de requêtes horaires si le contrôle final est activé. |
| `resale_caps_eur` | `{ "tshirt": 18, "blazer": 40, ... }` | Plafonds de revente réalistes par catégorie. |
| `brand_tiers` | `{ "Gucci": 3.0, "Kenzo": 1.5, ... }` | Multiplicateurs de palier par marque. |

---

## 📱 Commandes Telegram Interactives

Le bot écoute en direct les commandes sur le chat administrateur configuré :

- **`/stats`** : Bilan du jour (annonces vues, alertes validées, pépites, taux de passage, temps moyen CPU par annonce, coût Gemini).
- **`/seuils`** : Affiche les seuils actuels.
- **`/seuils score 75`** : Modifie le score minimal requis à la volée.
- **`/seuils marge 20`** : Modifie la marge minimale requise à la volée.
- **`/seuils multiple 2.5`** : Modifie le multiple minimal de revente.
- **`/seuils pepites on`** : Active le mode pépites exclusives 🟢.
- **`/why <item_id>`** : Audit détaillé expliquant pourquoi une annonce a été validée ou rejetée (sous-scores, marge, motif d'arrêt).
- **`/retrain`** : Déclenche le réentraînement complet des modèles de revente et du backtest en tâche de fond.
- **`/on` / `/off`** : Active ou met en pause la surveillance Vinted.
- **`/status`** : Vérifie l'état opérationnel du bot.
- **`/list`** : Liste les recherches actives configurées.
- **`/countries fr,it,es`** : Configure les pays surveillés en direct.

---

## 💻 Commandes PowerShell

Toutes les commandes s'exécutent depuis le dossier racine du projet avec l'environnement virtuel `.\venv` :

### 1. Lancer la suite de tests
```powershell
.\venv\Scripts\python -m pytest
```

### 2. Réentraîner les modèles de revente (Quantile q30 & q50)
```powershell
.\venv\Scripts\python scripts/train_resale.py
```

### 3. Exécuter le backtest sur données réelles (Génère le rapport HTML)
```powershell
.\venv\Scripts\python scripts/backtest.py
# Consulter le rapport : start data/backtest_report.html
```

### 4. Lancer le bot pour une seule passe de contrôle
```powershell
.\venv\Scripts\python main.py --once
```

### 5. Démarrer le bot en continu
```powershell
.\venv\Scripts\python main.py
```
