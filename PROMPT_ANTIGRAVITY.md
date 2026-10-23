Tu travailles sur mon bot Python `bot-vinted` (dossier courant). Il surveille Vinted, filtre les annonces, les fait noter par Gemini Vision et envoie les pépites sur Telegram avec des boutons de feedback. Lis tout le code avant de modifier quoi que ce soit.

Travaille en 3 phases, dans l'ordre. À la fin de chaque phase, fais un récap des fichiers modifiés et attends ma validation avant de passer à la suivante.

## Phase 1 : nettoyage et sécurité

1. Sors tous les secrets de `config.json` vers un fichier `.env` chargé avec `python-dotenv` : token et chat_id Telegram, clés Gemini (`gemini_api_key` et `gemini_api_keys`), cookie de session Vinted. `config.json` ne doit plus contenir que les réglages et les recherches. Crée un `.env.example` avec des valeurs factices.
2. Dans `src/playwright_worker.py`, supprime les valeurs par défaut écrites en dur (`v_uid`, `v_sid`, `anon_id`). Elles doivent venir du `.env`.
3. Crée un `.gitignore` : `.env`, `vinted_cookies.json`, `*.db`, `backups/`, `bot.log`, `venv/`, `__pycache__/`, `*.png`.
4. `requirements.txt` : retire ce qui n'est pas importé (`aiohttp`, `python-telegram-bot` : le code utilise `requests` directement), ajoute `python-dotenv` et `pytest`. Vérifie chaque import avant de retirer.
5. Supprime le code mort et les doublons sans changer le comportement : parsing du prix dupliqué dans plusieurs fichiers (crée un helper unique `extract_price(item)`), `import json` dans une boucle de `scraper.py`, numérotation des étapes en double dans `filters.py`.
6. Mets le README à jour : il dit que le bot interroge `/api/v2/catalog/items`, alors que `scraper.py` parse le HTML de `/catalog`. Décris ce que fait vraiment le code.

## Phase 2 : bugs qui font rater des affaires

1. **Radar In-Demand mort.** `main.py` appelle `db.mark_item_seen()` sur chaque annonce dès sa découverte, puis `InDemandTracker.process_due_items()` saute toute annonce déjà en base (`if db.is_item_seen(item_id): continue`). Il saute donc tout. Ajoute une table ou une colonne `notified` distincte de `seen`, et ne saute que les annonces déjà notifiées.
2. **Filtres sans données.** `search_items()` ne renvoie que id, titre, prix et photo. Les filtres sur `brand_title`, `status`, `user.feedback_reputation`, `favourite_count` et la liste fast-fashion ne voient que des valeurs vides. Dans `fetch_item_details()`, extrais ces champs depuis le JSON-LD Product de la page (et les données embarquées de la page si besoin). Ensuite, sépare `DealEvaluator` en deux passes : `prefilter()` (titre, prix, mots exclus) avant l'enrichissement, et `full_filter()` (marque, état, note vendeur, favoris, fast-fashion) après l'enrichissement et avant l'appel Gemini.
3. **Mots exclus en sous-chaîne.** `kw in full_text` fait que "cap" rejette "cape" et "capuche", "box" rejette "boxy", "cover" rejette "discover". La recherche "cape laine vintage" est rejetée à 100 %. Passe à une correspondance par mot entier (regex `\b`, insensible à la casse et aux accents).
4. **Prix faux possible.** La regex prend le premier montant en € dans un bloc de 1500 caractères autour du lien. Lis le prix depuis les données structurées. Garde la regex seulement en secours et logge quand elle est utilisée.
5. **Feedback vide.** Les boutons MUST BUY / AVIS MAMA / REJET enregistrent seulement `item_id` et la classification. Au moment d'envoyer l'alerte, sauvegarde l'annonce complète (titre, prix, marque, état, note vendeur, description, URLs photos, score et verdict IA, recherche). Au clic, mets à jour la classification de cette ligne.
6. **Boucle d'apprentissage.** Dans `vision_evaluator.py`, ajoute au prompt les 10 derniers MUST_BUY et les 10 derniers REJECTED de la même recherche ou catégorie (titre, prix, marque, raison si dispo), comme exemples de mon goût. Pas de photos dans ces exemples, juste du texte, pour garder le coût bas.
7. Écris des tests `pytest` pour `filters.py` : cas "cape laine" accepté, "casquette" rejeté, marque fast-fashion rejetée quand `brand_title` est rempli, état "Satisfaisant" rejeté.

## Phase 3 : multi-pays Vinted

Objectif : chercher aussi sur Vinted Italie, Allemagne, Espagne, Belgique, Pays-Bas, Portugal, Autriche (pays en euros uniquement, pour éviter les conversions).

1. Ajoute dans `config.json` un réglage global `"countries": ["fr", "it", "de", "es", "be", "nl", "pt", "at"]`, surchargeable par recherche. Mapping pays vers domaine (`vinted.fr`, `vinted.it`, `vinted.de`, `vinted.es`, `vinted.be`, `vinted.nl`, `vinted.pt`, `vinted.at`).
2. Un `VintedSessionManager` par domaine (le paramètre `domain` existe déjà). Fichier cookies par domaine (`cookies/vinted_<pays>.json`), en-tête `Accept-Language` adapté au pays, `locale` Playwright adaptée.
3. Un `VintedRateLimiter` par domaine, minimum 3 secondes entre deux requêtes sur un même domaine. Ne descends jamais sous ce seuil. En cas de 429 sur un pays, mets uniquement ce pays en pause, pas tout le bot.
4. Remplace toutes les URLs `vinted.fr` écrites en dur (`main.py`, `notifier.py`, `in_demand.py`, `vision_evaluator.py` pour le Referer) par le domaine de l'annonce. Stocke `domain` sur chaque item et dans la base. La clé anti-doublon devient `(domain, item_id)`.
5. **Mots-clés traduits.** Les noms de marques marchent partout, mais "manteau laine" ne trouve rien sur vinted.it. Ajoute un champ optionnel `search_text_i18n` : `{"it": "cappotto lana", "de": "wollmantel"}`. S'il manque une traduction, génère-la une seule fois avec Gemini, mets-la en cache dans `config.json` et logge-la pour que je puisse la corriger. Si la recherche n'est composée que d'une marque et d'un modèle, ne traduis pas.
6. **Filtres multilingues.** Les mots exclus (enfant, boîte vide, etc.), les marqueurs de faux ("style", "façon", "inspiré"), les mots de genre (homme, femme) et l'état "Satisfaisant" sont en français. Ajoute leurs équivalents it/de/es/nl/pt dans un fichier `src/i18n_keywords.py`.
7. **Marge réaliste.** Ajoute dans la config un coût de port estimé par pays vers la France (valeur par défaut : 8 € pour l'étranger, 3 € pour la France), et retire-le du profit estimé. Passe le pays et le prix port compris à Gemini dans le prompt.
8. **Alerte Telegram.** Affiche le drapeau du pays, le prix, le prix port compris et le domaine. Ajoute la commande `/countries` pour voir ou modifier les pays actifs.
9. Au premier lancement d'un nouveau pays, garde le comportement actuel : premier scan en cache silencieux, sans alerte.

## Contraintes

- Ne touche pas à la logique d'achat automatique ni au checkout Playwright, à part retirer les identifiants en dur.
- Garde le format des messages Telegram et les boutons actuels.
- Ne change pas les seuils (score >= 75, verdicts) sans me le demander.
- Pas de nouvelle dépendance lourde sans me demander.
- Après chaque phase, `python main.py --once` doit tourner sans erreur et `pytest` doit passer. Donne-moi les commandes PowerShell exactes pour vérifier (je suis sous Windows, venv dans `.\venv`).
