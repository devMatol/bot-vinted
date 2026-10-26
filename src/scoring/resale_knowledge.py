"""
src/scoring/resale_knowledge.py
--------------------------------
Base de connaissances locale et persistante des prix de revente réels du marché de la seconde main.

Rôle :
1. Stocker en base locale SQLite (resale_knowledge_base) et maintenir en mémoire RAM l'ensemble des
   prix de référence (Revente Flash / Revente Cible / Revente Coup de Cœur) par couple (Marque x Catégorie).
2. Éliminer 100% de la latence réseau et 100% des blocages de quotas API Gemini en temps réel.
3. Fournir une fonction d'enrichissement à la demande (on-demand) appelée UNIQUEMENT lorsqu'une marque
   ou une catégorie nouvelle/manquante se présente, pour l'enregistrer définitivement en base.
"""

import os
import json
import sqlite3
import time
import logging
import threading
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("VintedBot.Scoring.ResaleKnowledge")

DEFAULT_DB_PATH = "vinted_bot.db"


@dataclass
class ResaleKnowledgeEntry:
    brand: str
    category: str
    resale_min_flash: float
    resale_target: float
    resale_max_high: float
    description: str = ""
    source: str = "curated_precomputed"
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Référence experte du marché de la seconde main (prix de revente réalistes constatés sur Vinted/Vestiaire)
CURATED_RESALE_BENCHMARKS = {
    # ==========================================
    # TIER 3 : HAUTE COUTURE & LUXE MAJEUR
    # ==========================================
    "Yves Saint Laurent": {
        "veste": (65.0, 100.0, 160.0, "Veste blazer ou tailleur YSL Rive Gauche vintage"),
        "blazer": (65.0, 100.0, 160.0, "Tailleur blazer Yves Saint Laurent vintage"),
        "manteau": (85.0, 150.0, 260.0, "Manteau laine ou trench Saint Laurent"),
        "manteau_fourrure": (100.0, 180.0, 300.0, "Manteau fourrure ou peau lainée YSL"),
        "robe": (55.0, 90.0, 150.0, "Robe en soie ou cocktail Yves Saint Laurent"),
        "jupe": (30.0, 50.0, 85.0, "Jupe tailleur ou plissée YSL"),
        "jean": (25.0, 42.0, 70.0, "Jean Saint Laurent coupe slim ou droit"),
        "pantalon": (30.0, 52.0, 85.0, "Pantalon tailleur laine YSL"),
        "pull_maille": (35.0, 60.0, 95.0, "Pull ou cardigan maille YSL"),
        "sweat": (40.0, 68.0, 110.0, "Sweat logo Saint Laurent"),
        "chemise_blouse": (32.0, 55.0, 90.0, "Chemisier soie ou coton YSL"),
        "top": (22.0, 38.0, 60.0, "Top habillé Saint Laurent"),
        "tshirt": (22.0, 38.0, 65.0, "T-shirt logo Saint Laurent"),
        "sac": (85.0, 170.0, 320.0, "Sac cuir ou toile Saint Laurent"),
        "chaussures": (45.0, 75.0, 130.0, "Chaussures cuir Saint Laurent"),
        "bottes": (55.0, 95.0, 160.0, "Bottes cuir Saint Laurent"),
        "escarpins": (40.0, 70.0, 115.0, "Escarpins Tribute ou classiques YSL"),
        "accessoire": (25.0, 45.0, 75.0, "Ceinture cuir ou foulard soie YSL")
    },
    "Thierry Mugler": {
        "veste": (75.0, 130.0, 230.0, "Veste structurée vintage Mugler épaulettes iconiques"),
        "blazer": (75.0, 130.0, 230.0, "Tailleur blazer Thierry Mugler vintage"),
        "manteau": (90.0, 160.0, 290.0, "Manteau long structuré Thierry Mugler"),
        "manteau_fourrure": (110.0, 190.0, 340.0, "Manteau spectaculaire Thierry Mugler"),
        "robe": (65.0, 110.0, 200.0, "Robe fourreau ou sculpturale Mugler"),
        "jupe": (35.0, 58.0, 95.0, "Jupe crayon Mugler"),
        "jean": (30.0, 50.0, 85.0, "Jean Mugler spiral ou vintage"),
        "pantalon": (35.0, 60.0, 95.0, "Pantalon taille haute Mugler"),
        "pull_maille": (38.0, 65.0, 105.0, "Pull ou cardigan Mugler"),
        "sweat": (45.0, 75.0, 120.0, "Sweat logo Mugler"),
        "chemise_blouse": (35.0, 58.0, 95.0, "Chemisier Mugler cintré"),
        "top": (25.0, 45.0, 75.0, "Top Mugler découpe ou bustier"),
        "tshirt": (25.0, 42.0, 70.0, "T-shirt Mugler"),
        "sac": (70.0, 130.0, 230.0, "Sac cuir Mugler"),
        "chaussures": (45.0, 80.0, 135.0, "Chaussures ou talons Mugler"),
        "bottes": (60.0, 105.0, 175.0, "Bottes cuir Mugler"),
        "escarpins": (45.0, 75.0, 125.0, "Escarpins Mugler"),
        "accessoire": (25.0, 45.0, 75.0, "Accessoire Mugler vintage")
    },
    "Gucci": {
        "veste": (75.0, 135.0, 250.0, "Veste cuir, toile GG ou blazer Gucci"),
        "blazer": (70.0, 120.0, 210.0, "Blazer laine Gucci monogramme ou classique"),
        "manteau": (110.0, 200.0, 380.0, "Manteau laine ou trench Gucci"),
        "manteau_fourrure": (130.0, 240.0, 450.0, "Manteau fourrure ou shearling Gucci"),
        "robe": (70.0, 120.0, 220.0, "Robe en soie ou cocktail Gucci"),
        "jupe": (40.0, 68.0, 115.0, "Jupe plissée ou cuir Gucci"),
        "jean": (32.0, 55.0, 90.0, "Jean brodé ou coupe droite Gucci"),
        "pantalon": (38.0, 65.0, 110.0, "Pantalon tailleur Gucci"),
        "pull_maille": (48.0, 85.0, 140.0, "Pull laine ou cachemire Gucci brodé"),
        "sweat": (55.0, 95.0, 160.0, "Sweat oversize logo Gucci"),
        "chemise_blouse": (38.0, 68.0, 110.0, "Chemisier soie ou imprimé Gucci"),
        "top": (28.0, 48.0, 80.0, "Top GG ou lingerie Gucci"),
        "tshirt": (32.0, 55.0, 90.0, "T-shirt logo vintage Gucci"),
        "sac": (100.0, 195.0, 390.0, "Sac cuir ou toile monogramme Gucci"),
        "chaussures": (50.0, 95.0, 160.0, "Baskets Ace ou mocassins Jordaan Gucci"),
        "bottes": (70.0, 125.0, 215.0, "Bottes cuir mors Gucci"),
        "escarpins": (45.0, 75.0, 125.0, "Escarpins mors Gucci"),
        "accessoire": (30.0, 55.0, 95.0, "Ceinture double G cuir ou foulard Gucci")
    },
    "Prada": {
        "veste": (70.0, 120.0, 210.0, "Veste nylon ou blazer laine Prada"),
        "blazer": (65.0, 110.0, 185.0, "Blazer noir ou tailleur Prada"),
        "manteau": (100.0, 180.0, 320.0, "Manteau laine vierge ou doudoune Prada"),
        "manteau_fourrure": (120.0, 210.0, 380.0, "Manteau précieux Prada"),
        "robe": (60.0, 100.0, 170.0, "Robe en soie ou popeline Prada"),
        "jupe": (35.0, 60.0, 105.0, "Jupe plissée ou nylon Prada"),
        "jean": (30.0, 50.0, 80.0, "Jean droit Prada"),
        "pantalon": (35.0, 60.0, 100.0, "Pantalon nylon ou tailleur Prada"),
        "pull_maille": (42.0, 75.0, 125.0, "Pull cachemire ou maille Prada"),
        "sweat": (48.0, 85.0, 135.0, "Sweat logo triangle Prada"),
        "chemise_blouse": (35.0, 58.0, 95.0, "Chemise coton popeline ou bowling Prada"),
        "top": (25.0, 42.0, 70.0, "Top débardeur triangle Prada"),
        "tshirt": (28.0, 48.0, 80.0, "T-shirt logo patch Prada"),
        "sac": (85.0, 170.0, 340.0, "Sac nylon Re-Edition ou cuir Saffiano Prada"),
        "chaussures": (50.0, 85.0, 145.0, "Loafers Monolith ou sneakers Prada"),
        "bottes": (65.0, 115.0, 195.0, "Bottes Monolith ou cuir Prada"),
        "escarpins": (40.0, 70.0, 115.0, "Escarpins Prada logo"),
        "accessoire": (25.0, 48.0, 80.0, "Portefeuille Saffiano ou pochette Prada")
    },
    "Miu Miu": {
        "veste": (60.0, 105.0, 175.0, "Veste cuir, tweed ou blouson Miu Miu"),
        "blazer": (55.0, 90.0, 155.0, "Blazer court ou tailleur Miu Miu"),
        "manteau": (85.0, 155.0, 265.0, "Manteau laine ou trench Miu Miu"),
        "manteau_fourrure": (100.0, 180.0, 310.0, "Manteau shearling Miu Miu"),
        "robe": (55.0, 95.0, 165.0, "Mini-robe ou robe cocktail Miu Miu"),
        "jupe": (38.0, 68.0, 120.0, "Mini-jupe plissée Miu Miu"),
        "jean": (28.0, 48.0, 80.0, "Jean taille basse Miu Miu"),
        "pantalon": (30.0, 52.0, 85.0, "Pantalon tailleur Miu Miu"),
        "pull_maille": (40.0, 72.0, 120.0, "Cardigan cachemire cropped Miu Miu"),
        "sweat": (42.0, 75.0, 125.0, "Sweat logo brodé Miu Miu"),
        "chemise_blouse": (30.0, 52.0, 85.0, "Chemise col claudine Miu Miu"),
        "top": (22.0, 38.0, 65.0, "Top crop ou maille Miu Miu"),
        "tshirt": (25.0, 42.0, 70.0, "T-shirt logo Miu Miu"),
        "sac": (75.0, 145.0, 280.0, "Sac cuir matelassé Matelassé Miu Miu"),
        "chaussures": (45.0, 80.0, 135.0, "Ballerines à brides satin ou cuir Miu Miu"),
        "bottes": (58.0, 105.0, 175.0, "Bottes motardes ou cuir Miu Miu"),
        "escarpins": (38.0, 68.0, 110.0, "Escarpins babies Miu Miu"),
        "accessoire": (22.0, 38.0, 65.0, "Bandeau cheveux, pochette ou lunettes Miu Miu")
    },
    "Burberry": {
        "veste": (48.0, 82.0, 140.0, "Veste matelassée ou blouson Burberry"),
        "blazer": (45.0, 75.0, 125.0, "Blazer laine tartan Burberry"),
        "manteau": (95.0, 170.0, 300.0, "Trench-coat classique gabardine Burberry"),
        "manteau_fourrure": (100.0, 175.0, 300.0, "Manteau shearling ou caban Burberry"),
        "robe": (38.0, 65.0, 110.0, "Robe tartan ou chemisier Burberry"),
        "jupe": (30.0, 52.0, 85.0, "Jupe kilt ou plissée tartan Nova Check"),
        "jean": (22.0, 38.0, 60.0, "Jean Burberry"),
        "pantalon": (25.0, 42.0, 70.0, "Pantalon chino ou tailleur Burberry"),
        "pull_maille": (35.0, 60.0, 100.0, "Pull cachemire ou col rond Burberry"),
        "sweat": (38.0, 65.0, 105.0, "Sweat logo Burberry TB"),
        "chemise_blouse": (30.0, 52.0, 85.0, "Chemise emblématique tartan Burberry"),
        "top": (18.0, 30.0, 48.0, "Top Burberry"),
        "tshirt": (22.0, 35.0, 58.0, "T-shirt logo Burberry"),
        "sac": (70.0, 130.0, 235.0, "Sac toile tartan ou cuir Burberry"),
        "chaussures": (35.0, 60.0, 100.0, "Sneakers ou espadrilles Burberry"),
        "bottes": (48.0, 82.0, 135.0, "Bottes de pluie ou cuir tartan"),
        "escarpins": (30.0, 52.0, 82.0, "Escarpins Burberry"),
        "accessoire": (30.0, 55.0, 95.0, "Écharpe 100% cachemire tartan classique")
    },

    # ==========================================
    # TIER 2 / 1.5 : CRÉATEURS ITALIENS & COUTURE
    # ==========================================
    "Versace": {
        "veste": (48.0, 82.0, 140.0, "Veste blazer baroque, cuir ou tailleur Versace"),
        "blazer": (45.0, 75.0, 125.0, "Blazer tailleur Versace boutons Méduse"),
        "manteau": (68.0, 118.0, 195.0, "Manteau laine ou doudoune baroque Versace"),
        "manteau_fourrure": (80.0, 140.0, 240.0, "Manteau fourrure Versace"),
        "robe": (42.0, 75.0, 128.0, "Robe moulante, imprimée ou de soirée Versace"),
        "jupe": (25.0, 42.0, 70.0, "Jupe imprimé baroque ou fente Versace"),
        "jean": (24.0, 38.0, 65.0, "Jean Versace Jeans Couture logo ou baroque"),
        "pantalon": (25.0, 45.0, 75.0, "Pantalon tailleur Versace"),
        "pull_maille": (30.0, 52.0, 85.0, "Pull maille Méduse ou baroque Versace"),
        "sweat": (35.0, 60.0, 98.0, "Sweat baroque ou logo doré Versace"),
        "chemise_blouse": (38.0, 68.0, 120.0, "Chemise en soie imprimé baroque iconique Versace"),
        "top": (20.0, 35.0, 58.0, "Top crop ou débardeur Versace"),
        "tshirt": (20.0, 32.0, 55.0, "T-shirt Méduse ou logo doré Versace"),
        "sac": (55.0, 105.0, 190.0, "Sac cuir Méduse ou cabas baroque Versace"),
        "chaussures": (38.0, 65.0, 110.0, "Baskets Chain Reaction ou talons Versace"),
        "bottes": (48.0, 82.0, 138.0, "Bottes cuir boucles Versace"),
        "escarpins": (35.0, 60.0, 98.0, "Escarpins plateformes ou pin Versace"),
        "accessoire": (25.0, 42.0, 72.0, "Ceinture boucle Méduse dorée Versace")
    },
    "Roberto Cavalli": {
        "veste": (45.0, 78.0, 130.0, "Veste cuir, brodée ou blazer imprimé animal"),
        "blazer": (40.0, 68.0, 115.0, "Blazer Roberto Cavalli imprimé reptile"),
        "manteau": (62.0, 108.0, 185.0, "Manteau long ou fausse fourrure léopard"),
        "manteau_fourrure": (75.0, 130.0, 220.0, "Manteau fourrure animal print Cavalli"),
        "robe": (42.0, 75.0, 130.0, "Robe longue en soie, imprimé léopard/zèbre Cavalli"),
        "jupe": (25.0, 42.0, 70.0, "Jupe imprimée ou cuir Cavalli"),
        "jean": (24.0, 40.0, 68.0, "Jean Cavalli brodé, clouté ou flare"),
        "pantalon": (25.0, 44.0, 72.0, "Pantalon taille basse ou cuir Cavalli"),
        "pull_maille": (28.0, 48.0, 78.0, "Pull maille léopard ou strass Cavalli"),
        "sweat": (30.0, 52.0, 85.0, "Sweat logo Cavalli"),
        "chemise_blouse": (32.0, 58.0, 98.0, "Blouse en soie imprimé animal Cavalli"),
        "top": (20.0, 35.0, 58.0, "Top bustier ou débardeur imprimé Cavalli"),
        "tshirt": (18.0, 30.0, 48.0, "T-shirt Cavalli logo"),
        "sac": (45.0, 85.0, 150.0, "Sac cuir serpent ou imprimé Cavalli"),
        "chaussures": (32.0, 58.0, 98.0, "Sandales à brides ou talons Cavalli"),
        "bottes": (44.0, 78.0, 130.0, "Bottes cuir python ou franges Cavalli"),
        "escarpins": (30.0, 52.0, 88.0, "Escarpins imprimé léopard Cavalli"),
        "accessoire": (20.0, 35.0, 60.0, "Ceinture boucle serpent ou foulard soie Cavalli")
    },
    "Just Cavalli": {
        "veste": (28.0, 48.0, 80.0, "Veste blouson ou blazer Just Cavalli"),
        "blazer": (24.0, 40.0, 68.0, "Blazer Just Cavalli"),
        "manteau": (38.0, 68.0, 115.0, "Manteau ou doudoune Just Cavalli"),
        "manteau_fourrure": (45.0, 78.0, 130.0, "Veste fausse fourrure Just Cavalli"),
        "robe": (25.0, 45.0, 75.0, "Robe Just Cavalli imprimée"),
        "jupe": (16.0, 28.0, 45.0, "Jupe Just Cavalli"),
        "jean": (18.0, 30.0, 48.0, "Jean Just Cavalli délavé ou imprimé"),
        "pantalon": (16.0, 28.0, 45.0, "Pantalon Just Cavalli"),
        "pull_maille": (18.0, 30.0, 50.0, "Pull ou cardigan Just Cavalli"),
        "sweat": (22.0, 38.0, 60.0, "Sweat Just Cavalli logo"),
        "chemise_blouse": (20.0, 35.0, 58.0, "Chemise ou blouse Just Cavalli"),
        "top": (14.0, 22.0, 35.0, "Top imprimé Just Cavalli"),
        "tshirt": (14.0, 22.0, 35.0, "T-shirt Just Cavalli"),
        "sac": (30.0, 55.0, 95.0, "Sac Just Cavalli"),
        "chaussures": (22.0, 38.0, 65.0, "Sneakers ou sandales Just Cavalli"),
        "bottes": (30.0, 52.0, 85.0, "Bottines Just Cavalli"),
        "escarpins": (20.0, 35.0, 58.0, "Escarpins Just Cavalli"),
        "accessoire": (14.0, 24.0, 40.0, "Ceinture Just Cavalli")
    },
    "Dolce & Gabbana": {
        "veste": (48.0, 82.0, 140.0, "Veste smoking, blazer cintrée ou cuir D&G"),
        "blazer": (45.0, 75.0, 125.0, "Blazer noir cintré ou jacquard Dolce & Gabbana"),
        "manteau": (68.0, 118.0, 200.0, "Manteau laine ou caban léopard D&G"),
        "manteau_fourrure": (80.0, 140.0, 240.0, "Manteau fourrure ou léopard D&G"),
        "robe": (44.0, 78.0, 135.0, "Robe fourreau dentelle sicilienne ou fleurie"),
        "jupe": (26.0, 45.0, 75.0, "Jupe crayon dentelle ou fleurie D&G"),
        "jean": (25.0, 40.0, 68.0, "Jean D&G plaque métallique arrière iconique"),
        "pantalon": (26.0, 45.0, 75.0, "Pantalon tailleur noir D&G"),
        "pull_maille": (30.0, 52.0, 85.0, "Pull maille fine ou cachemire D&G"),
        "sweat": (35.0, 60.0, 98.0, "Sweat logo couronne ou monogramme D&G"),
        "chemise_blouse": (30.0, 55.0, 95.0, "Chemisier soie à pois ou fleurs D&G"),
        "top": (20.0, 35.0, 60.0, "Top corset ou bustier dentelle D&G"),
        "tshirt": (20.0, 32.0, 55.0, "T-shirt logo ou plaque métal D&G"),
        "sac": (55.0, 105.0, 195.0, "Sac Sicily ou cuir D&G"),
        "chaussures": (35.0, 65.0, 110.0, "Sneakers Portofino ou talons D&G"),
        "bottes": (48.0, 82.0, 138.0, "Bottes cuir ou dentelle D&G"),
        "escarpins": (35.0, 60.0, 98.0, "Escarpins dentelle Bellucci D&G"),
        "accessoire": (24.0, 40.0, 68.0, "Ceinture boucle logo ou portefeuille D&G")
    },
    "Max Mara": {
        "veste": (40.0, 70.0, 120.0, "Veste blazer tailleur pure laine Max Mara"),
        "blazer": (40.0, 68.0, 115.0, "Blazer laine vierge Max Mara ou Sportmax"),
        "manteau": (85.0, 160.0, 280.0, "Manteau icône 101801, cachemire ou Teddy Max Mara"),
        "manteau_fourrure": (95.0, 175.0, 310.0, "Manteau Teddy Bear ou alpaga Max Mara"),
        "robe": (35.0, 60.0, 105.0, "Robe portefeuille ou en soie Max Mara"),
        "jupe": (22.0, 38.0, 65.0, "Jupe tailleur laine ou plissée"),
        "jean": (18.0, 30.0, 48.0, "Jean Sportmax ou Weekend Max Mara"),
        "pantalon": (25.0, 45.0, 75.0, "Pantalon tailleur large pure laine Max Mara"),
        "pull_maille": (30.0, 55.0, 95.0, "Pull 100% cachemire ou laine Max Mara"),
        "sweat": (25.0, 42.0, 70.0, "Sweat Max Mara Weekend"),
        "chemise_blouse": (25.0, 42.0, 70.0, "Chemisier 100% soie Max Mara"),
        "top": (16.0, 28.0, 45.0, "Top soie ou lin Max Mara"),
        "tshirt": (16.0, 26.0, 42.0, "T-shirt en coton ou logo chien Max Mara"),
        "sac": (48.0, 90.0, 165.0, "Sac cuir Whitney ou cabas Max Mara"),
        "chaussures": (30.0, 55.0, 92.0, "Mocassins ou sandales cuir Max Mara"),
        "bottes": (44.0, 78.0, 130.0, "Bottes cuir lisse Max Mara"),
        "escarpins": (30.0, 52.0, 82.0, "Escarpins cuir Max Mara"),
        "accessoire": (22.0, 38.0, 68.0, "Écharpe cachemire ou ceinture cuir Max Mara")
    },
    "Moschino": {
        "veste": (38.0, 68.0, 115.0, "Veste biker cuir ou blazer décalé Moschino"),
        "blazer": (35.0, 60.0, 100.0, "Blazer Moschino Cheap and Chic vintage"),
        "manteau": (55.0, 95.0, 160.0, "Manteau laine ou doudoune Moschino"),
        "manteau_fourrure": (68.0, 118.0, 200.0, "Manteau fausse fourrure pop Moschino"),
        "robe": (32.0, 58.0, 100.0, "Robe t-shirt ours ou cocktail Moschino"),
        "jupe": (20.0, 35.0, 58.0, "Jupe imprimée ou denim Moschino"),
        "jean": (20.0, 32.0, 55.0, "Jean Moschino Jeans patch ou brodé"),
        "pantalon": (22.0, 38.0, 62.0, "Pantalon imprimé Moschino"),
        "pull_maille": (28.0, 48.0, 80.0, "Pull ours Teddy Bear Moschino"),
        "sweat": (32.0, 55.0, 92.0, "Sweat iconique Teddy Bear Moschino"),
        "chemise_blouse": (22.0, 38.0, 65.0, "Chemisier imprimé Moschino"),
        "top": (16.0, 28.0, 48.0, "Top logo ou crop top Moschino"),
        "tshirt": (18.0, 30.0, 50.0, "T-shirt Teddy Bear iconique Moschino"),
        "sac": (42.0, 80.0, 140.0, "Sac biker jacket ou cabas nylon Moschino"),
        "chaussures": (30.0, 52.0, 88.0, "Sneakers Teddy Shoes Moschino"),
        "bottes": (38.0, 68.0, 110.0, "Bottes de pluie ou motardes Moschino"),
        "escarpins": (25.0, 45.0, 75.0, "Escarpins Moschino"),
        "accessoire": (18.0, 32.0, 55.0, "Ceinture lettres dorées Moschino ou pochette")
    },
    "Kenzo": {
        "veste": (35.0, 60.0, 100.0, "Veste bombardier, denim ou blazer Kenzo"),
        "blazer": (30.0, 52.0, 88.0, "Blazer imprimé fleurs ou tailoring Kenzo"),
        "manteau": (50.0, 90.0, 150.0, "Manteau laine ou parka Kenzo"),
        "manteau_fourrure": (62.0, 108.0, 180.0, "Manteau fausse fourrure Kenzo"),
        "robe": (28.0, 50.0, 85.0, "Robe chemise ou imprimé floral Kenzo"),
        "jupe": (20.0, 35.0, 58.0, "Jupe imprimé tigre ou fleurie Kenzo"),
        "jean": (20.0, 32.0, 55.0, "Jean brodé tigre ou denim Kenzo"),
        "pantalon": (20.0, 35.0, 58.0, "Pantalon imprimé ou jogging Kenzo"),
        "pull_maille": (28.0, 48.0, 80.0, "Pull laine tigre brodé Kenzo"),
        "sweat": (35.0, 60.0, 95.0, "Sweat iconique Tigre brodé Kenzo"),
        "chemise_blouse": (22.0, 38.0, 62.0, "Chemise fleurs ou tigre Kenzo"),
        "top": (15.0, 25.0, 40.0, "Top léger Kenzo"),
        "tshirt": (18.0, 28.0, 48.0, "T-shirt tigre brodé Kenzo"),
        "sac": (38.0, 70.0, 125.0, "Sac bandoulière Kalifornia ou sacoche tigre Kenzo"),
        "chaussures": (25.0, 45.0, 78.0, "Espadrilles tigre ou sneakers Kenzo"),
        "bottes": (34.0, 60.0, 100.0, "Bottines cuir ou pluie Kenzo"),
        "escarpins": (22.0, 38.0, 65.0, "Escarpins Kenzo"),
        "accessoire": (16.0, 28.0, 48.0, "Casquette tigre ou pochette Kenzo")
    },
    "Iceberg": {
        "veste": (32.0, 55.0, 92.0, "Veste blouson ou bombers cartoon Iceberg"),
        "blazer": (28.0, 48.0, 78.0, "Blazer vintage Iceberg"),
        "manteau": (45.0, 80.0, 135.0, "Manteau ou doudoune Iceberg"),
        "manteau_fourrure": (55.0, 95.0, 160.0, "Manteau doudoune col fourrure Iceberg"),
        "robe": (24.0, 42.0, 70.0, "Robe maille Iceberg"),
        "jupe": (18.0, 30.0, 48.0, "Jupe cartoon ou denim Iceberg"),
        "jean": (20.0, 32.0, 55.0, "Jean vintage broderie Snoopy ou Bugs Bunny"),
        "pantalon": (18.0, 30.0, 50.0, "Pantalon vintage Iceberg"),
        "pull_maille": (32.0, 58.0, 98.0, "Pull vintage brodé Snoopy / Mickey / Looney Tunes"),
        "sweat": (28.0, 50.0, 85.0, "Sweat brodé cartoon Iceberg vintage"),
        "chemise_blouse": (20.0, 35.0, 58.0, "Chemise vintage cartoon Iceberg"),
        "top": (14.0, 22.0, 36.0, "Top Iceberg"),
        "tshirt": (15.0, 25.0, 42.0, "T-shirt cartoon Iceberg"),
        "sac": (28.0, 50.0, 85.0, "Sac Iceberg vintage"),
        "chaussures": (24.0, 40.0, 68.0, "Sneakers Iceberg"),
        "bottes": (28.0, 50.0, 85.0, "Bottes Iceberg"),
        "escarpins": (20.0, 35.0, 58.0, "Escarpins Iceberg"),
        "accessoire": (14.0, 24.0, 40.0, "Ceinture ou écharpe Iceberg")
    },
    "Armani": {
        "veste": (30.0, 52.0, 88.0, "Veste blazer Giorgio Armani ou Emporio"),
        "blazer": (30.0, 50.0, 85.0, "Blazer tailleur laine vierge Armani"),
        "manteau": (48.0, 88.0, 145.0, "Manteau laine ou trench Armani"),
        "manteau_fourrure": (58.0, 100.0, 170.0, "Manteau col fourrure Armani"),
        "robe": (25.0, 42.0, 72.0, "Robe élégante ou cocktail Armani"),
        "jupe": (16.0, 28.0, 45.0, "Jupe tailleur Giorgio Armani"),
        "jean": (18.0, 28.0, 45.0, "Jean Armani Jeans ou Emporio aigle arrière"),
        "pantalon": (20.0, 35.0, 58.0, "Pantalon tailleur laine Armani"),
        "pull_maille": (20.0, 35.0, 58.0, "Pull col rond ou V Armani"),
        "sweat": (22.0, 38.0, 62.0, "Sweat aigle logo EA7 ou Emporio"),
        "chemise_blouse": (20.0, 35.0, 55.0, "Chemise coupe cintrée Giorgio Armani"),
        "top": (12.0, 20.0, 32.0, "Top léger Armani"),
        "tshirt": (14.0, 22.0, 35.0, "T-shirt logo EA7 ou Emporio"),
        "sac": (30.0, 55.0, 95.0, "Sac cuir ou vernis Armani"),
        "chaussures": (24.0, 42.0, 70.0, "Sneakers ou mocassins Armani"),
        "bottes": (32.0, 55.0, 92.0, "Bottes cuir Armani"),
        "escarpins": (22.0, 38.0, 62.0, "Escarpins classiques Armani"),
        "accessoire": (16.0, 28.0, 48.0, "Ceinture boucle aigle Armani")
    },

    # ==========================================
    # TIER 1 : DIFFUSION & CONTEMPORARY PREMIUM
    # ==========================================
    "Diesel": {
        "veste": (20.0, 35.0, 60.0, "Veste blouson ou bomber Diesel"),
        "blazer": (16.0, 28.0, 45.0, "Blazer denim Diesel"),
        "manteau": (25.0, 45.0, 75.0, "Manteau parka ou doudoune Diesel"),
        "manteau_fourrure": (30.0, 50.0, 85.0, "Blouson col peau lainée Diesel"),
        "robe": (14.0, 24.0, 38.0, "Robe en jean Diesel"),
        "jupe": (10.0, 18.0, 28.0, "Mini-jupe en jean Diesel"),
        "jean": (12.0, 20.0, 32.0, "Jean Diesel standard seconde main (Larkee, Zatiny, Skinzee...)"),
        "pantalon": (12.0, 20.0, 32.0, "Pantalon cargo Diesel"),
        "pull_maille": (12.0, 20.0, 32.0, "Pull ou cardigan Diesel"),
        "sweat": (16.0, 28.0, 45.0, "Sweat logo Diesel"),
        "chemise_blouse": (12.0, 20.0, 30.0, "Chemise en jean Diesel"),
        "top": (9.0, 15.0, 22.0, "Top ou débardeur Diesel"),
        "tshirt": (10.0, 16.0, 25.0, "T-shirt vintage Diesel"),
        "sac": (20.0, 38.0, 70.0, "Sac Diesel"),
        "chaussures": (15.0, 25.0, 42.0, "Sneakers Diesel"),
        "bottes": (20.0, 35.0, 60.0, "Bottines motardes Diesel"),
        "escarpins": (12.0, 20.0, 32.0, "Escarpins Diesel"),
        "accessoire": (10.0, 18.0, 28.0, "Ceinture ou casquette Diesel")
    },
    "Patrizia Pepe": {
        "veste": (20.0, 35.0, 60.0, "Veste blazer ou simili Patrizia Pepe"),
        "blazer": (18.0, 30.0, 50.0, "Blazer cintré Patrizia Pepe"),
        "manteau": (28.0, 50.0, 85.0, "Manteau laine ou doudoune Patrizia Pepe"),
        "manteau_fourrure": (30.0, 55.0, 90.0, "Manteau fausse fourrure Patrizia Pepe"),
        "robe": (15.0, 25.0, 40.0, "Robe de soirée ou courte Patrizia Pepe"),
        "jupe": (10.0, 18.0, 28.0, "Jupe Patrizia Pepe"),
        "jean": (10.0, 18.0, 28.0, "Jean slim Patrizia Pepe"),
        "pantalon": (12.0, 20.0, 32.0, "Pantalon tailleur Patrizia Pepe"),
        "pull_maille": (12.0, 20.0, 32.0, "Pull ou cardigan fin Patrizia Pepe"),
        "sweat": (14.0, 22.0, 35.0, "Sweat logo Fly Patrizia Pepe"),
        "chemise_blouse": (12.0, 20.0, 32.0, "Blouse fluide Patrizia Pepe"),
        "top": (9.0, 15.0, 22.0, "Top léger Patrizia Pepe"),
        "tshirt": (8.0, 14.0, 22.0, "T-shirt logo Fly Patrizia Pepe"),
        "sac": (18.0, 32.0, 55.0, "Sac cabas ou cuir Patrizia Pepe"),
        "chaussures": (15.0, 25.0, 42.0, "Sneakers ou sandales Patrizia Pepe"),
        "bottes": (20.0, 35.0, 60.0, "Bottes cuir Patrizia Pepe"),
        "escarpins": (14.0, 24.0, 38.0, "Escarpins Patrizia Pepe"),
        "accessoire": (10.0, 16.0, 26.0, "Ceinture ou pochette Patrizia Pepe")
    },
    "Guess": {
        "veste": (18.0, 30.0, 50.0, "Veste simili cuir ou jean Guess"),
        "blazer": (15.0, 25.0, 40.0, "Blazer cintré Guess"),
        "manteau": (25.0, 45.0, 75.0, "Manteau doudoune col fourrure Guess"),
        "manteau_fourrure": (28.0, 50.0, 80.0, "Manteau fausse fourrure Guess"),
        "robe": (12.0, 22.0, 35.0, "Robe moulante bandage Guess"),
        "jupe": (10.0, 16.0, 25.0, "Mini-jupe denim ou simili Guess"),
        "jean": (10.0, 18.0, 28.0, "Jean triangle rouge Guess standard"),
        "pantalon": (10.0, 18.0, 28.0, "Pantalon skinny Guess"),
        "pull_maille": (10.0, 18.0, 28.0, "Pull maille logo Guess"),
        "sweat": (12.0, 20.0, 32.0, "Sweat triangle logo Guess"),
        "chemise_blouse": (10.0, 18.0, 28.0, "Chemise denim ou fluide Guess"),
        "top": (8.0, 14.0, 20.0, "Top bustier ou débardeur Guess"),
        "tshirt": (8.0, 14.0, 22.0, "T-shirt triangle logo Guess"),
        "sac": (18.0, 32.0, 55.0, "Sac à main logo monogramme 4G Guess"),
        "chaussures": (14.0, 24.0, 38.0, "Baskets compensées ou sandales Guess"),
        "bottes": (18.0, 30.0, 50.0, "Bottines à talons Guess"),
        "escarpins": (12.0, 20.0, 32.0, "Escarpins Guess"),
        "accessoire": (10.0, 16.0, 26.0, "Ceinture boucle logo Guess ou portefeuille")
    }
}


class ResaleKnowledgeService:
    """Service central d'accès instantané aux prix de revente réels sans appel Gemini continu."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH, config: Optional[Dict[str, Any]] = None):
        self.db_path = db_path
        self.config = config or {}
        self._cache: Dict[Tuple[str, str], ResaleKnowledgeEntry] = {}
        self._lock = threading.Lock()

        self._init_db()
        self._seed_curated_benchmarks()
        self._load_cache()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resale_knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand TEXT NOT NULL,
                    category TEXT NOT NULL,
                    resale_min_flash REAL NOT NULL,
                    resale_target REAL NOT NULL,
                    resale_max_high REAL NOT NULL,
                    description TEXT,
                    source TEXT DEFAULT 'curated_precomputed',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(brand, category)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rkb_brand_cat ON resale_knowledge_base (brand, category)")
        conn.close()

    def _seed_curated_benchmarks(self) -> None:
        """Injecte les valeurs de référence expertes si absentes de la base."""
        conn = self._get_conn()
        try:
            with conn:
                for brand, cats in CURATED_RESALE_BENCHMARKS.items():
                    for cat, (r_min, r_target, r_max, desc) in cats.items():
                        conn.execute("""
                            INSERT OR REPLACE INTO resale_knowledge_base
                            (brand, category, resale_min_flash, resale_target, resale_max_high, description, source)
                            VALUES (?, ?, ?, ?, ?, ?, 'curated_benchmark')
                        """, (brand, cat, float(r_min), float(r_target), float(r_max), desc))
        except Exception as e:
            logger.debug(f"Erreur injection benchmarks: {e}")
        finally:
            conn.close()

    def _load_cache(self) -> None:
        """Charge en RAM toute la base de connaissances."""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT brand, category, resale_min_flash, resale_target, resale_max_high, description, source FROM resale_knowledge_base")
        rows = cur.fetchall()
        conn.close()

        with self._lock:
            for r in rows:
                key = (r[0].lower().strip(), r[1].lower().strip())
                self._cache[key] = ResaleKnowledgeEntry(
                    brand=r[0],
                    category=r[1],
                    resale_min_flash=float(r[2]),
                    resale_target=float(r[3]),
                    resale_max_high=float(r[4]),
                    description=r[5] or "",
                    source=r[6] or "curated"
                )
        logger.info(f"📚 [Base de Revente Locale] {len(self._cache)} couples (marque x catégorie) chargés en mémoire RAM.")

    def get_resale_entry(
        self,
        brand: str,
        category: str,
        condition: Optional[str] = None,
        materials: Optional[List[str]] = None,
        is_leather_silk: bool = False
    ) -> Optional[ResaleKnowledgeEntry]:
        """
        Récupère instantanément (< 0.001 ms) les données de revente du couple (marque, catégorie).
        Applique si besoin des modificateurs fins (cuir, soie, état).
        """
        b_clean = (brand or "").lower().strip()
        c_clean = (category or "").lower().strip()

        # Recherche directe
        key = (b_clean, c_clean)
        with self._lock:
            entry = self._cache.get(key)

        # Si pas trouvé sous cette clé exacte, chercher des alias courants
        if not entry:
            aliases_brand = {
                "roberto cavalli": ["cavalli", "class roberto cavalli"],
                "just cavalli": ["cavalli", "just cavalli"],
                "dolce & gabbana": ["d&g", "dolce", "dolce&gabbana"],
                "yves saint laurent": ["saint laurent", "ysl", "rive gauche"],
                "thierry mugler": ["mugler"],
                "max mara": ["sportmax", "weekend max mara", "marina rinaldi", "maxmara"],
                "armani": ["emporio armani", "giorgio armani", "armani jeans"]
            }
            with self._lock:
                for main_b, aliases in aliases_brand.items():
                    if b_clean == main_b or b_clean in aliases:
                        candidate_keys = [(main_b, c_clean)] + [(a, c_clean) for a in aliases]
                        for ck in candidate_keys:
                            if ck in self._cache:
                                entry = self._cache[ck]
                                break
                    if entry:
                        break

        if not entry:
            return None

        # Ajustement contextuel précis
        res_min = entry.resale_min_flash
        res_target = entry.resale_target
        res_max = entry.resale_max_high

        # Bonus matière noble (cuir, soie, cachemire)
        mat_mult = 1.0
        if is_leather_silk:
            mat_mult = 1.25
        elif materials:
            for m in materials:
                m_low = m.lower()
                if "cuir" in m_low or "leather" in m_low or "soie" in m_low or "silk" in m_low or "cachemire" in m_low:
                    mat_mult = 1.25
                    break

        # État
        cond_mult = 1.0
        if condition:
            c_low = condition.lower()
            if "neuf" in c_low or "étiquette" in c_low:
                cond_mult = 1.15
            elif "satisfaisant" in c_low or "bon état" == c_low.strip():
                cond_mult = 0.90

        total_mult = mat_mult * cond_mult

        return ResaleKnowledgeEntry(
            brand=entry.brand,
            category=entry.category,
            resale_min_flash=round(res_min * total_mult, 1),
            resale_target=round(res_target * total_mult, 1),
            resale_max_high=round(res_max * total_mult, 1),
            description=entry.description,
            source=entry.source
        )

    def profile_and_save_missing_pair_on_demand(
        self,
        brand: str,
        category: str,
        title: str = "",
        sample_price: float = 0.0
    ) -> Optional[ResaleKnowledgeEntry]:
        """
        Outil appelé SPÉCIFIQUEMENT à la demande lorsqu'une marque ou catégorie manque en base.
        Interroge Gemini UNE SEULE FOIS pour profiler ce couple et l'enregistre en SQLite.
        À partir de ce moment, il ne sera plus jamais recherché à nouveau !
        """
        logger.info(f"🔍 [Recherche à la Demande] Profilage inédit requis pour '{brand}' x '{category}'...")

        from google import genai
        key = self.config.get("gemini_api_key") or (self.config.get("gemini_api_keys", [None])[0])
        if not key:
            return None

        prompt = f"""Tu es le plus grand expert de la revente de mode de seconde main (Vinted, Vestiaire Collective).
Fixe les prix de référence de revente réalistes en euros (€) pour ce couple marque x catégorie :
• Marque : "{brand}"
• Catégorie : "{category}"
• Exemple de pièce observée : "{title}" (Prix proposé: {sample_price:.2f} €)

Donne les 3 montants de revente réalistes constatés sur Vinted :
1. resale_min_flash : prix auquel l'article part en 48h chrono (vente express)
2. resale_target : prix moyen réaliste auquel l'article se vend normalement sous 1-3 semaines
3. resale_max_high : prix plafond pour un acheteur coup de cœur / pièce rare ou parfaite

Réponds STRICTEMENT sous ce format JSON (sans aucun markdown) :
{{
  "resale_min_flash": <nombre>,
  "resale_target": <nombre>,
  "resale_max_high": <nombre>,
  "description": "<courte description experte de ce que vaut cette catégorie pour cette marque>"
}}"""

        try:
            client = genai.Client(api_key=key)
            res = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt
            )
            raw = res.text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)

            r_min = float(data.get("resale_min_flash", 15.0))
            r_target = float(data.get("resale_target", 25.0))
            r_max = float(data.get("resale_max_high", 45.0))
            desc = str(data.get("description", f"Profilé à la demande pour {brand} {category}"))

            entry = ResaleKnowledgeEntry(
                brand=brand,
                category=category,
                resale_min_flash=r_min,
                resale_target=r_target,
                resale_max_high=r_max,
                description=desc,
                source="on_demand_gemini"
            )

            # Enregistrement en SQLite
            conn = self._get_conn()
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO resale_knowledge_base
                    (brand, category, resale_min_flash, resale_target, resale_max_high, description, source)
                    VALUES (?, ?, ?, ?, ?, ?, 'on_demand_gemini')
                """, (brand, category, r_min, r_target, r_max, desc))
            conn.close()

            # Mise à jour du cache RAM
            with self._lock:
                self._cache[(brand.lower().strip(), category.lower().strip())] = entry

            logger.info(f"✅ [Enregistré en Base Définitive] {brand} x {category} -> Flash: {r_min}€, Cible: {r_target}€, Max: {r_max}€")
            return entry

        except Exception as e:
            logger.debug(f"Erreur profilage à la demande pour {brand} {category}: {e}")
            return None


_SERVICE_INSTANCE: Optional[ResaleKnowledgeService] = None

def get_resale_knowledge_service(config: Optional[Dict[str, Any]] = None) -> ResaleKnowledgeService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = ResaleKnowledgeService(config=config)
    return _SERVICE_INSTANCE
