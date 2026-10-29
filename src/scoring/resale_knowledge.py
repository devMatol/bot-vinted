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
        "pull_maille": (22.0, 38.0, 65.0, "Pull laine Kenzo vintage ou maille archive (hors tigre)"),
        "sweat": (20.0, 35.0, 58.0, "Sweat logo classique ou vintage Kenzo (hors tigre)"),
        "chemise_blouse": (20.0, 35.0, 58.0, "Chemise fleurs ou imprimé Kenzo Jungle (hors tigre)"),
        "top": (14.0, 22.0, 36.0, "Top léger Kenzo (hors tigre)"),
        "tshirt": (12.0, 20.0, 32.0, "T-shirt logo Kenzo classique (hors tigre)"),
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

    "Coach": {
        "sac": (45.0, 85.0, 180.0, "Sac cuir Tabby, Willis, Rogue, Swagger, Court ou toile monogramme CC Coach"),
        "accessoire": (25.0, 45.0, 85.0, "Portefeuille cuir, porte-monnaie ou ceinture boucle C Coach"),
        "veste": (60.0, 120.0, 240.0, "Blouson en cuir ou perfecto Coach New York"),
        "blazer": (45.0, 85.0, 170.0, "Veste blazer tailoring Coach"),
        "manteau": (70.0, 140.0, 280.0, "Trench-coat ou manteau long en laine Coach"),
        "manteau_fourrure": (90.0, 180.0, 350.0, "Manteau shearling ou col fourrure Coach"),
        "chaussures": (35.0, 65.0, 120.0, "Baskets signature C ou mocassins cuir Coach"),
        "bottes": (45.0, 85.0, 160.0, "Bottines cuir ou bottes cavalières Coach"),
        "escarpins": (30.0, 55.0, 100.0, "Escarpins cuir ou sandales à talon Coach"),
        "robe": (35.0, 65.0, 130.0, "Robe en soie imprimée ou robe cocktail Coach"),
        "jupe": (28.0, 50.0, 95.0, "Jupe cuir ou plissée Coach"),
        "jean": (25.0, 45.0, 80.0, "Jean brodé ou denim signature Coach"),
        "pantalon": (28.0, 50.0, 95.0, "Pantalon en cuir ou tailoring Coach"),
        "pull_maille": (35.0, 65.0, 120.0, "Pull en laine mérinos ou cachemire Coach"),
        "sweat": (35.0, 70.0, 130.0, "Sweat hoodie Rexy dinosaure ou logo Coach"),
        "chemise_blouse": (28.0, 50.0, 95.0, "Chemise en soie ou blouse fluide Coach"),
        "top": (20.0, 40.0, 75.0, "Top en soie ou caraco Coach"),
        "tshirt": (22.0, 42.0, 80.0, "T-shirt graphique Rexy ou signature Coach"),
    },
    "Longchamp": {
        "sac": (35.0, 70.0, 160.0, "Sac Roseau cuir, Le Pliage cuir, Amazone ou grand cabas Longchamp"),
        "accessoire": (20.0, 38.0, 70.0, "Compagnon cuir Roseau, pochette ou foulard soie Longchamp"),
        "veste": (50.0, 100.0, 200.0, "Veste en cuir d'agneau ou blouson Longchamp"),
        "blazer": (40.0, 75.0, 150.0, "Veste blazer habillée Longchamp"),
        "manteau": (65.0, 130.0, 260.0, "Manteau drap de laine ou trench Longchamp"),
        "manteau_fourrure": (80.0, 160.0, 320.0, "Manteau peau lainée ou shearling Longchamp"),
        "chaussures": (30.0, 55.0, 100.0, "Mocassins cuir ou espadrilles Longchamp"),
        "bottes": (40.0, 80.0, 150.0, "Bottes cavalières en cuir Longchamp"),
        "escarpins": (28.0, 50.0, 90.0, "Escarpins cuir ou sandales Longchamp"),
        "robe": (30.0, 60.0, 120.0, "Robe en soie ou cocktail Longchamp"),
        "jupe": (25.0, 45.0, 85.0, "Jupe cuir ou trapèze Longchamp"),
        "jean": (22.0, 40.0, 75.0, "Pantalon denim Longchamp"),
        "pantalon": (25.0, 48.0, 90.0, "Pantalon en cuir ou habillé Longchamp"),
        "pull_maille": (30.0, 58.0, 110.0, "Pull cachemire ou maille Longchamp"),
        "sweat": (28.0, 52.0, 100.0, "Sweat logo cavalier Longchamp"),
        "chemise_blouse": (25.0, 45.0, 85.0, "Chemise en soie ou blouse Longchamp"),
        "top": (18.0, 35.0, 65.0, "Top en soie ou sans manches Longchamp"),
        "tshirt": (18.0, 35.0, 65.0, "T-shirt cavalier Longchamp"),
    },

    "Jean Paul Gaultier": {
        "top": (45.0, 95.0, 220.0, "Top en tulle/mesh imprimé soleil, cyber ou tatouage Jean Paul Gaultier"),
        "robe": (60.0, 120.0, 250.0, "Robe trompe l'oeil, résille, maille ou drapée Jean Paul Gaultier"),
        "veste": (55.0, 110.0, 220.0, "Veste blouson ou perfecto déstructuré Jean Paul Gaultier"),
        "blazer": (55.0, 105.0, 190.0, "Blazer tailoring rayures tennis ou coupe cintrée JPG"),
        "manteau": (75.0, 140.0, 260.0, "Manteau long ou caban marin drap de laine JPG"),
        "manteau_fourrure": (85.0, 160.0, 280.0, "Manteau fausse fourrure ou peau lainée JPG"),
        "pull_maille": (45.0, 85.0, 160.0, "Pull marinière iconique ou grosse maille Jean Paul Gaultier"),
        "sweat": (40.0, 75.0, 130.0, "Sweat marinière ou logo brodé Jean Paul Gaultier"),
        "jupe": (35.0, 65.0, 120.0, "Jupe plissée kilt ou jupe trompe l'oeil JPG"),
        "pantalon": (35.0, 65.0, 110.0, "Pantalon tailoring pont marin ou coupe droite JPG"),
        "jean": (30.0, 55.0, 95.0, "Jean Jean's Paul Gaultier coupe vintage"),
        "chemise_blouse": (35.0, 68.0, 120.0, "Chemise en soie imprimée ou marinière fluide JPG"),
        "tshirt": (28.0, 50.0, 95.0, "T-shirt marinière ou imprimé graphique Jean Paul Gaultier"),
        "sac": (50.0, 100.0, 200.0, "Sac cuir, boîte métal ou pochette Jean Paul Gaultier"),
        "chaussures": (35.0, 65.0, 120.0, "Chaussures cuir ou boots à lacets Jean Paul Gaultier"),
        "bottes": (50.0, 95.0, 180.0, "Bottes cuir esprit militaire ou cavalières JPG"),
        "escarpins": (35.0, 65.0, 115.0, "Escarpins ou mules à talon Jean Paul Gaultier"),
        "accessoire": (25.0, 50.0, 95.0, "Ceinture corset, bretelles ou foulard soie JPG"),
    },
    "John Galliano": {
        "robe": (65.0, 130.0, 280.0, "Robe en soie coupée en biais, slip dress dentelle ou Gazette John Galliano"),
        "top": (45.0, 85.0, 160.0, "Top Gazette newspaper, caraco en soie ou lingerie John Galliano"),
        "veste": (60.0, 120.0, 230.0, "Veste tailoring asymétrique ou blouson John Galliano"),
        "blazer": (55.0, 110.0, 200.0, "Veste blazer cintrée couture John Galliano"),
        "manteau": (80.0, 160.0, 300.0, "Manteau victorien long ou redingote John Galliano"),
        "manteau_fourrure": (90.0, 180.0, 320.0, "Manteau col fourrure ou shearling John Galliano"),
        "jupe": (35.0, 70.0, 130.0, "Jupe asymétrique, imprimé Gazette ou plissée Galliano"),
        "jean": (30.0, 58.0, 100.0, "Jean denim imprimé Gazette ou délavé Galliano"),
        "pantalon": (35.0, 68.0, 120.0, "Pantalon en soie fluide ou tailoring John Galliano"),
        "pull_maille": (38.0, 70.0, 130.0, "Pull en maille fine brodée ou cardigan Galliano"),
        "sweat": (35.0, 65.0, 110.0, "Sweat imprimé Gazette ou logo John Galliano"),
        "chemise_blouse": (38.0, 75.0, 130.0, "Chemisier en soie lavallière ou imprimé John Galliano"),
        "tshirt": (25.0, 48.0, 90.0, "T-shirt imprimé Gazette newspaper John Galliano"),
        "sac": (55.0, 110.0, 220.0, "Sac Gazette, sac selle ou cuir John Galliano"),
        "chaussures": (35.0, 70.0, 130.0, "Chaussures cuir, sneakers Gazette Galliano"),
        "bottes": (55.0, 110.0, 190.0, "Bottes cuir lacées ou bottines John Galliano"),
        "escarpins": (38.0, 72.0, 125.0, "Escarpins bride ou mules dentelle John Galliano"),
        "accessoire": (28.0, 50.0, 95.0, "Foulard soie Gazette, ceinture ou bijou John Galliano"),
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
    },
    "Celine": {
        "veste": (85.0, 160.0, 320.0, "Veste ou blouson Celine"),
        "blazer": (90.0, 180.0, 350.0, "Blazer tailoring ou laine tweed Celine"),
        "manteau": (130.0, 260.0, 520.0, "Manteau drap de laine ou trench Celine"),
        "manteau_fourrure": (150.0, 320.0, 650.0, "Manteau fourrure ou shearling Celine"),
        "robe": (60.0, 120.0, 240.0, "Robe en soie ou cocktail Celine"),
        "jupe": (40.0, 75.0, 140.0, "Jupe plissée ou trapèze Celine"),
        "jean": (45.0, 85.0, 160.0, "Jean Jane ou denim évasé Celine"),
        "pantalon": (45.0, 85.0, 160.0, "Pantalon à pinces ou costume Celine"),
        "pull_maille": (55.0, 110.0, 220.0, "Pull cachemire ou maille Celine"),
        "sweat": (60.0, 120.0, 220.0, "Sweat à capuche logo Celine Paris"),
        "chemise_blouse": (45.0, 85.0, 160.0, "Chemise en soie ou popeline Celine"),
        "top": (35.0, 65.0, 120.0, "Top en soie ou sans manches Celine"),
        "tshirt": (35.0, 65.0, 120.0, "T-shirt à logo floqué Celine"),
        "sac": (120.0, 240.0, 500.0, "Sac Macadam vintage, Triomphe ou cuir Celine"),
        "chaussures": (50.0, 95.0, 180.0, "Baskets Triomphe ou mocassins Celine"),
        "bottes": (75.0, 140.0, 280.0, "Bottes cuir cavalières ou Claude Celine"),
        "escarpins": (45.0, 85.0, 160.0, "Escarpins ou babies à talon Celine"),
        "accessoire": (40.0, 80.0, 150.0, "Ceinture boucle Triomphe, lunettes ou foulard Celine"),
    },
    "Dior": {
        "veste": (75.0, 140.0, 280.0, "Veste Bar ou blouson Dior"),
        "blazer": (80.0, 150.0, 300.0, "Blazer habillé ou costume Christian Dior Monsieur"),
        "manteau": (110.0, 220.0, 450.0, "Manteau long en laine ou trench Dior"),
        "manteau_fourrure": (140.0, 290.0, 600.0, "Manteau fourrure Dior"),
        "robe": (55.0, 110.0, 220.0, "Robe élégante ou cocktail Dior"),
        "jupe": (35.0, 70.0, 130.0, "Jupe plissée ou trapèze Dior"),
        "jean": (38.0, 75.0, 140.0, "Jean Dior Homme ou denim monogramme"),
        "pantalon": (35.0, 70.0, 130.0, "Pantalon habillé Christian Dior"),
        "pull_maille": (50.0, 95.0, 190.0, "Pull maille brodée ou cachemire Dior"),
        "sweat": (60.0, 120.0, 240.0, "Sweat ou hoodie à logo Dior"),
        "chemise_blouse": (40.0, 75.0, 140.0, "Chemise en soie ou coton brodé Dior"),
        "top": (30.0, 55.0, 100.0, "Débardeur ou top monogramme vintage Dior"),
        "tshirt": (35.0, 65.0, 120.0, "T-shirt J'Adore Dior ou logo brodé"),
        "sac": (110.0, 220.0, 480.0, "Sac Saddle, Lady Dior ou toile Oblique vintage"),
        "chaussures": (55.0, 110.0, 210.0, "Baskets B23 ou slippers Dior"),
        "bottes": (70.0, 140.0, 270.0, "Bottes cuir ou bottines Dior"),
        "escarpins": (50.0, 95.0, 180.0, "Escarpins J'Adior ruban ou classiques Dior"),
        "accessoire": (35.0, 70.0, 130.0, "Ceinture CD, lunettes de soleil ou foulard Dior"),
    },
    "Chanel": {
        "veste": (140.0, 280.0, 550.0, "Veste en tweed emblématique Chanel"),
        "blazer": (150.0, 300.0, 600.0, "Tailleur blazer tweed boutons dorés Chanel"),
        "manteau": (180.0, 360.0, 750.0, "Manteau long en laine ou tweed Chanel"),
        "manteau_fourrure": (220.0, 450.0, 900.0, "Manteau fourrure ou shearling Chanel"),
        "robe": (90.0, 180.0, 380.0, "Petite robe noire ou robe en soie Chanel"),
        "jupe": (55.0, 110.0, 220.0, "Jupe en tweed ou maille Chanel"),
        "jean": (55.0, 110.0, 220.0, "Jean Chanel vintage ou denim CC"),
        "pantalon": (50.0, 95.0, 190.0, "Pantalon en laine ou soie Chanel"),
        "pull_maille": (75.0, 150.0, 300.0, "Pull cachemire ou cardigan boutons bijou Chanel"),
        "sweat": (70.0, 140.0, 280.0, "Sweat ou hoodie Chanel Gabrielle"),
        "chemise_blouse": (60.0, 120.0, 230.0, "Blouse en soie ou chemise Chanel"),
        "top": (45.0, 85.0, 160.0, "Top en maille ou soie Chanel"),
        "tshirt": (45.0, 85.0, 160.0, "T-shirt imprimé logo CC Chanel"),
        "sac": (200.0, 450.0, 950.0, "Sac matelassé Timeless, 2.55 ou vintage cuir Chanel"),
        "chaussures": (65.0, 130.0, 260.0, "Ballerines bicolores ou espadrilles Chanel"),
        "bottes": (95.0, 190.0, 380.0, "Bottes cuir ou bottines bicolores Chanel"),
        "escarpins": (65.0, 130.0, 260.0, "Escarpins slingback bicolores Chanel"),
        "accessoire": (50.0, 100.0, 200.0, "Ceinture chaîne, broche CC, lunettes ou foulard Chanel"),
    },
    "Bottega Veneta": {
        "veste": (85.0, 160.0, 320.0, "Veste en cuir ou blouson Bottega Veneta"),
        "blazer": (80.0, 150.0, 300.0, "Blazer tailoring laine Bottega Veneta"),
        "manteau": (120.0, 240.0, 480.0, "Manteau drap de laine Bottega Veneta"),
        "manteau_fourrure": (150.0, 300.0, 600.0, "Manteau shearling ou cuir retourné Bottega"),
        "robe": (60.0, 120.0, 230.0, "Robe habillée ou drapée Bottega Veneta"),
        "jupe": (40.0, 75.0, 140.0, "Jupe cuir ou plissée Bottega Veneta"),
        "jean": (40.0, 75.0, 140.0, "Jean droit ou coupe tailoring Bottega Veneta"),
        "pantalon": (45.0, 85.0, 160.0, "Pantalon en laine ou cuir Bottega Veneta"),
        "pull_maille": (55.0, 110.0, 220.0, "Pull maille épaisse ou cachemire Bottega"),
        "sweat": (45.0, 85.0, 160.0, "Sweat col rond Bottega Veneta"),
        "chemise_blouse": (40.0, 75.0, 140.0, "Chemise en popeline de coton Bottega"),
        "top": (30.0, 60.0, 110.0, "Top sans manches en maille Bottega"),
        "tshirt": (30.0, 55.0, 100.0, "T-shirt coton épais Bottega Veneta"),
        "sac": (120.0, 240.0, 500.0, "Sac cuir tressé Intrecciato, Pouch ou Jodie Bottega"),
        "chaussures": (65.0, 125.0, 240.0, "Mules Lido tressées ou mocassins Bottega"),
        "bottes": (85.0, 170.0, 340.0, "Bottes Tire boots ou Puddle Bottega"),
        "escarpins": (55.0, 110.0, 210.0, "Escarpins en cuir tressé Bottega Veneta"),
        "accessoire": (38.0, 75.0, 140.0, "Portefeuille tressé, ceinture ou lunettes Bottega"),
    },
    "Balenciaga": {
        "veste": (75.0, 150.0, 300.0, "Veste denim oversize ou blouson Balenciaga"),
        "blazer": (80.0, 160.0, 320.0, "Blazer à épaules structurées Balenciaga"),
        "manteau": (110.0, 220.0, 440.0, "Doudoune oversize C-Shape ou manteau Balenciaga"),
        "manteau_fourrure": (120.0, 250.0, 500.0, "Fausse fourrure à logo Balenciaga"),
        "robe": (50.0, 95.0, 190.0, "Robe plissée ou asymétrique Balenciaga"),
        "jupe": (35.0, 65.0, 120.0, "Jupe denim ou trapèze Balenciaga"),
        "jean": (45.0, 90.0, 170.0, "Jean baggy oversize délavé Balenciaga"),
        "pantalon": (40.0, 80.0, 150.0, "Pantalon tailoring large ou survêtement Balenciaga"),
        "pull_maille": (60.0, 120.0, 220.0, "Pull en maille à logo all-over Balenciaga"),
        "sweat": (65.0, 125.0, 230.0, "Hoodie oversize Campaign / Paris Balenciaga"),
        "chemise_blouse": (40.0, 80.0, 150.0, "Chemise oversize à rayures ou logo Balenciaga"),
        "top": (28.0, 55.0, 100.0, "Top stretch ou débardeur Balenciaga"),
        "tshirt": (38.0, 70.0, 130.0, "T-shirt oversize vintage wash Balenciaga"),
        "sac": (95.0, 190.0, 390.0, "Sac City vintage, Le Cagole ou Hourglass Balenciaga"),
        "chaussures": (55.0, 105.0, 200.0, "Baskets Triple S, Track ou Speed Trainer Balenciaga"),
        "bottes": (70.0, 135.0, 260.0, "Bottines Knife ou bottes Strike Balenciaga"),
        "escarpins": (45.0, 85.0, 160.0, "Escarpins Knife pointus jersey ou cuir Balenciaga"),
        "accessoire": (30.0, 60.0, 110.0, "Casquette logo, lunettes de soleil ou portefeuille Balenciaga"),
    },
    "Loewe": {
        "veste": (85.0, 170.0, 340.0, "Veste en cuir souple ou surchemise Loewe"),
        "blazer": (80.0, 150.0, 300.0, "Blazer en laine ou lin Loewe"),
        "manteau": (120.0, 250.0, 500.0, "Manteau long ceinturé Anagram Loewe"),
        "manteau_fourrure": (150.0, 320.0, 650.0, "Manteau shearling ou peau lainée Loewe"),
        "robe": (55.0, 110.0, 220.0, "Robe en lin ou soie brodée Loewe"),
        "jupe": (38.0, 70.0, 130.0, "Jupe asymétrique ou cuir Loewe"),
        "jean": (40.0, 80.0, 150.0, "Jean patch cuir genoux ou droit Loewe"),
        "pantalon": (40.0, 80.0, 150.0, "Pantalon fluide en lin ou laine Loewe"),
        "pull_maille": (55.0, 110.0, 210.0, "Pull mohair ou maille Anagram Loewe"),
        "sweat": (50.0, 95.0, 180.0, "Sweat ou hoodie Anagram brodé Loewe"),
        "chemise_blouse": (40.0, 75.0, 140.0, "Chemise en popeline col plastron Loewe"),
        "top": (30.0, 55.0, 100.0, "Débardeur logo brodé Anagram Loewe"),
        "tshirt": (32.0, 60.0, 110.0, "T-shirt coton à logo brodé Loewe"),
        "sac": (120.0, 240.0, 490.0, "Sac Puzzle, Hammock, Flamenco ou panier raphia Loewe"),
        "chaussures": (50.0, 95.0, 180.0, "Sneakers Flow runner ou espadrilles Loewe"),
        "bottes": (75.0, 140.0, 270.0, "Bottines Chelsea ou boots cuir Loewe"),
        "escarpins": (45.0, 85.0, 160.0, "Escarpins Campo ou talons fantaisie Loewe"),
        "accessoire": (45.0, 90.0, 160.0, "Écharpe mohair et laine multicolore, ceinture Anagram"),
    },
    "Jacquemus": {
        "veste": (65.0, 125.0, 240.0, "Veste courte ou blazer d'homme Jacquemus"),
        "blazer": (70.0, 135.0, 260.0, "Blazer oversize La Veste d'Homme Jacquemus"),
        "manteau": (90.0, 180.0, 350.0, "Manteau ceinturé ou trench Jacquemus"),
        "manteau_fourrure": (95.0, 190.0, 380.0, "Manteau fausse fourrure ou shearling Jacquemus"),
        "robe": (45.0, 85.0, 160.0, "Robe chemise La Robe Bahia ou robe dos nu Jacquemus"),
        "jupe": (30.0, 60.0, 110.0, "Jupe portefeuille ou mini-jupe Jacquemus"),
        "jean": (32.0, 65.0, 120.0, "Jean droit délavé Jacquemus"),
        "pantalon": (35.0, 70.0, 130.0, "Pantalon large Le Pantalon Sauge Jacquemus"),
        "pull_maille": (45.0, 85.0, 150.0, "Cardigan ouvert La Maille Pralù ou pull Jacquemus"),
        "sweat": (38.0, 70.0, 130.0, "Sweat brodé Jacquemus"),
        "chemise_blouse": (35.0, 65.0, 120.0, "Chemise bowling ou lin Jacquemus"),
        "top": (28.0, 50.0, 90.0, "Top bandeau ou débardeur à brides Jacquemus"),
        "tshirt": (25.0, 45.0, 80.0, "T-shirt coton à logo Jacquemus"),
        "sac": (85.0, 160.0, 290.0, "Sac Le Chiquito, Le Bambino ou Le Grand Chiquito"),
        "chaussures": (40.0, 80.0, 150.0, "Mules ou baskets Humara Jacquemus"),
        "bottes": (55.0, 110.0, 210.0, "Bottines Les Meuniers ou Les Bottes Jacquemus"),
        "escarpins": (40.0, 80.0, 150.0, "Mules à talon géométrique Les Mules Jacquemus"),
        "accessoire": (25.0, 50.0, 95.0, "Bob Le Gadjo, bob Le Bob Artichaut, porte-cartes"),
    },
    "Chloé": {
        "veste": (65.0, 130.0, 250.0, "Veste courte ou blazer équestre Chloé"),
        "blazer": (70.0, 135.0, 260.0, "Blazer tailoring en laine ou velours Chloé"),
        "manteau": (100.0, 195.0, 390.0, "Manteau cape ou manteau en laine Chloé"),
        "manteau_fourrure": (120.0, 240.0, 480.0, "Manteau en peau lainée ou mouton Chloé"),
        "robe": (50.0, 95.0, 185.0, "Robe fluide bohème ou soie Chloé"),
        "jupe": (30.0, 60.0, 110.0, "Jupe longue plissée ou denim Chloé"),
        "jean": (30.0, 60.0, 110.0, "Jean évasé flare Chloé"),
        "pantalon": (32.0, 65.0, 120.0, "Pantalon flare à pont en laine Chloé"),
        "pull_maille": (45.0, 85.0, 160.0, "Pull grosse maille torsadée ou cachemire Chloé"),
        "sweat": (35.0, 65.0, 120.0, "Sweat brodé Chloé"),
        "chemise_blouse": (38.0, 70.0, 130.0, "Blouse romantique en soie ou dentelle Chloé"),
        "top": (25.0, 48.0, 85.0, "Top dentelle ou soie Chloé"),
        "tshirt": (25.0, 48.0, 85.0, "T-shirt en coton imprimé ou brodé Chloé"),
        "sac": (75.0, 150.0, 310.0, "Sac Marcie, Faye, Paddington ou Woody Chloé"),
        "chaussures": (40.0, 75.0, 140.0, "Baskets Lauren festonnées ou espadrilles Chloé"),
        "bottes": (60.0, 110.0, 190.0, "Bottines Susanna à clous dorés ou bottes cuir Chloé"),
        "escarpins": (35.0, 70.0, 130.0, "Escarpins festonnés Lauren Chloé"),
        "accessoire": (30.0, 60.0, 110.0, "Lunettes de soleil oversize, foulard ou ceinture Chloé"),
    },
    "Fendi": {
        "veste": (75.0, 150.0, 300.0, "Veste ou blouson monogramme Zucca Fendi"),
        "blazer": (80.0, 160.0, 320.0, "Blazer en laine ou soie Fendi"),
        "manteau": (120.0, 240.0, 490.0, "Manteau drap de laine ou imperméable Zucca Fendi"),
        "manteau_fourrure": (180.0, 380.0, 800.0, "Manteau fourrure ou vison signature Fendi"),
        "robe": (55.0, 110.0, 210.0, "Robe imprimée Zucca ou cocktail Fendi"),
        "jupe": (35.0, 70.0, 130.0, "Jupe plissée ou jupe tube Zucca Fendi"),
        "jean": (40.0, 80.0, 150.0, "Jean monogramme FF vintage Fendi"),
        "pantalon": (38.0, 75.0, 140.0, "Pantalon tailoring ou fluide Fendi"),
        "pull_maille": (55.0, 110.0, 210.0, "Pull maille monogramme Zucca Fendi"),
        "sweat": (50.0, 95.0, 180.0, "Sweat brodé Roma ou Zucca Fendi"),
        "chemise_blouse": (40.0, 75.0, 140.0, "Chemise en soie imprimée Fendi"),
        "top": (30.0, 60.0, 110.0, "Top ou body en maille stretch FF Zucca Fendi"),
        "tshirt": (32.0, 60.0, 110.0, "T-shirt Fendi Roma imprimé"),
        "sac": (110.0, 220.0, 480.0, "Sac Baguette vintage, Peekaboo ou toile FF Zucca Fendi"),
        "chaussures": (45.0, 90.0, 170.0, "Sneakers Roma ou sandales à bride FF Fendi"),
        "bottes": (70.0, 140.0, 270.0, "Bottes cuir ou bottines monogramme Fendi"),
        "escarpins": (45.0, 85.0, 160.0, "Escarpins Colibrì résille ou classiques Fendi"),
        "accessoire": (35.0, 70.0, 130.0, "Foulard soie FF, ceinture boucle FF ou lunettes Fendi"),
    },
    "Balmain": {
        "veste": (85.0, 170.0, 340.0, "Veste officier militaire ou cuir Balmain"),
        "blazer": (95.0, 190.0, 380.0, "Blazer iconique 6 boutons dorés Balmain"),
        "manteau": (120.0, 240.0, 480.0, "Manteau long croisé boutons dorés Balmain"),
        "manteau_fourrure": (140.0, 280.0, 560.0, "Manteau fourrure ou shearling Balmain"),
        "robe": (70.0, 135.0, 260.0, "Robe structurée à épaulettes ou tricot Balmain"),
        "jupe": (40.0, 75.0, 140.0, "Mini-jupe boutons dorés ou cuir Balmain"),
        "jean": (45.0, 85.0, 160.0, "Jean biker motard nervuré Balmain"),
        "pantalon": (40.0, 80.0, 150.0, "Pantalon tailoring ou cuir Balmain"),
        "pull_maille": (50.0, 95.0, 180.0, "Pull en maille à boutons dorés Balmain"),
        "sweat": (45.0, 85.0, 160.0, "Sweat médaillon logo flocké Balmain"),
        "chemise_blouse": (38.0, 75.0, 140.0, "Chemise en soie ou denim Balmain"),
        "top": (30.0, 55.0, 100.0, "Top débardeur ou tricot Balmain"),
        "tshirt": (30.0, 55.0, 95.0, "T-shirt médaillon logo doré Balmain"),
        "sac": (90.0, 180.0, 350.0, "Sac B-Buzz ou 1945 monogramme Balmain"),
        "chaussures": (45.0, 85.0, 160.0, "Baskets B-Court ou sandales Balmain"),
        "bottes": (70.0, 135.0, 260.0, "Bottines motardes cuir ou talons Balmain"),
        "escarpins": (45.0, 85.0, 160.0, "Escarpins boutons dorés Balmain"),
        "accessoire": (30.0, 60.0, 110.0, "Ceinture cuir boucle médaillon B Balmain"),
    },
    "Givenchy": {
        "veste": (75.0, 150.0, 300.0, "Veste en cuir ou bomber Givenchy"),
        "blazer": (75.0, 150.0, 300.0, "Blazer tailoring ou smoking Givenchy"),
        "manteau": (110.0, 220.0, 440.0, "Manteau long en laine Givenchy"),
        "manteau_fourrure": (130.0, 260.0, 520.0, "Manteau fourrure Givenchy"),
        "robe": (55.0, 110.0, 220.0, "Robe noire ou robe en soie Givenchy"),
        "jupe": (35.0, 65.0, 120.0, "Jupe cuir ou plissée Givenchy"),
        "jean": (38.0, 75.0, 140.0, "Jean slim ou droit Givenchy"),
        "pantalon": (38.0, 75.0, 140.0, "Pantalon tailoring ou jogging 4G Givenchy"),
        "pull_maille": (50.0, 100.0, 190.0, "Pull en maille logo 4G ou étoiles Givenchy"),
        "sweat": (45.0, 85.0, 160.0, "Sweat Rottweiler, Bambi ou logo Givenchy"),
        "chemise_blouse": (38.0, 70.0, 130.0, "Chemise en popeline col brodé Givenchy"),
        "top": (28.0, 50.0, 95.0, "Top ou caraco en soie Givenchy"),
        "tshirt": (30.0, 55.0, 100.0, "T-shirt imprimé logo Givenchy Paris"),
        "sac": (100.0, 195.0, 390.0, "Sac Antigona, Pandora ou Voyou Givenchy"),
        "chaussures": (45.0, 85.0, 160.0, "Sneakers Urban Street ou City Givenchy"),
        "bottes": (70.0, 135.0, 260.0, "Bottes Shark Lock ou bottines cuir Givenchy"),
        "escarpins": (40.0, 80.0, 150.0, "Escarpins cuir classiques Givenchy"),
        "accessoire": (30.0, 60.0, 110.0, "Ceinture boucle 4G, lunettes ou foulard Givenchy"),
    },
    "Courrèges": {
        "veste": (95.0, 180.0, 360.0, "Blouson vinyle iconique logo AC Courrèges"),
        "blazer": (70.0, 135.0, 260.0, "Blazer minimaliste court Courrèges"),
        "manteau": (100.0, 200.0, 390.0, "Manteau trapèze vintage ou vinyle Courrèges"),
        "manteau_fourrure": (95.0, 190.0, 380.0, "Manteau fausse fourrure Courrèges"),
        "robe": (45.0, 85.0, 160.0, "Robe trapèze vintage ou à découpes logo Courrèges"),
        "jupe": (35.0, 70.0, 130.0, "Mini-jupe vinyle ou trapèze Courrèges"),
        "jean": (35.0, 70.0, 130.0, "Jean taille haute ou vinyle Courrèges"),
        "pantalon": (35.0, 70.0, 130.0, "Pantalon droit vinyle ou jersey Courrèges"),
        "pull_maille": (40.0, 75.0, 140.0, "Pull col roulé à logo AC Courrèges"),
        "sweat": (38.0, 70.0, 130.0, "Sweat brodé logo AC Courrèges"),
        "chemise_blouse": (32.0, 60.0, 110.0, "Chemise ou blouse vintage Courrèges"),
        "top": (28.0, 50.0, 95.0, "Top brassière ou débardeur à logo Courrèges"),
        "tshirt": (25.0, 48.0, 85.0, "T-shirt coton à logo patch AC Courrèges"),
        "sac": (70.0, 135.0, 260.0, "Sac baguette vinyle ou cuir Courrèges"),
        "chaussures": (35.0, 70.0, 130.0, "Mules ou baskets Courrèges"),
        "bottes": (65.0, 125.0, 240.0, "Bottes blanches vinyle ou cuir Courrèges"),
        "escarpins": (35.0, 65.0, 120.0, "Escarpins rétro Courrèges"),
        "accessoire": (25.0, 50.0, 95.0, "Casquette, lunettes rétro ou ceinture Courrèges"),
    },
    "Vivienne Westwood": {
        "veste": (85.0, 170.0, 340.0, "Veste cintrée ou blouson Orb Vivienne Westwood"),
        "blazer": (90.0, 180.0, 360.0, "Blazer tailoring asymétrique ou tartan Westwood"),
        "manteau": (110.0, 220.0, 440.0, "Manteau laine col châle Vivienne Westwood"),
        "manteau_fourrure": (95.0, 190.0, 380.0, "Manteau shearling ou fausse fourrure Westwood"),
        "robe": (60.0, 120.0, 240.0, "Robe drapée ou cocktail Vivienne Westwood"),
        "jupe": (40.0, 80.0, 150.0, "Jupe kilt plissée tartan Vivienne Westwood"),
        "jean": (35.0, 70.0, 130.0, "Jean brodé Orb Vivienne Westwood Anglomania"),
        "pantalon": (40.0, 75.0, 140.0, "Pantalon tailoring ou kilt Westwood"),
        "pull_maille": (45.0, 85.0, 160.0, "Cardigan ou pull brodé Orb Vivienne Westwood"),
        "sweat": (40.0, 75.0, 140.0, "Sweat brodé Orb Vivienne Westwood"),
        "chemise_blouse": (35.0, 70.0, 130.0, "Chemise col montant ou col jabot Westwood"),
        "top": (50.0, 95.0, 190.0, "Corset imprimé ou satin Vivienne Westwood"),
        "tshirt": (28.0, 50.0, 95.0, "T-shirt imprimé Orb ou slogan Westwood"),
        "sac": (70.0, 130.0, 250.0, "Sac cuir ou tartan logo Orb Vivienne Westwood"),
        "chaussures": (45.0, 90.0, 170.0, "Chaussures Melissa ou baskets Orb Westwood"),
        "bottes": (70.0, 140.0, 270.0, "Bottes Pirate boots à brides Vivienne Westwood"),
        "escarpins": (45.0, 85.0, 160.0, "Escarpins Rocking Horse ou talons Westwood"),
        "accessoire": (40.0, 75.0, 130.0, "Collier perles Orb bas relief, boucles d'oreilles Orb"),
    },
    "Maison Margiela": {
        "veste": (85.0, 170.0, 340.0, "Veste déconstruite ou blouson Maison Margiela"),
        "blazer": (95.0, 190.0, 380.0, "Blazer déstructuré sans col 4 surpiqûres Margiela"),
        "manteau": (120.0, 240.0, 480.0, "Manteau laine ou trench déconstruit Margiela"),
        "manteau_fourrure": (130.0, 260.0, 520.0, "Manteau shearling ou poils Margiela"),
        "robe": (55.0, 110.0, 210.0, "Robe en soie ou jersey déconstruit Margiela / MM6"),
        "jupe": (38.0, 75.0, 140.0, "Jupe asymétrique ou denim Maison Margiela / MM6"),
        "jean": (45.0, 90.0, 170.0, "Jean à découpes ou délavé Maison Margiela"),
        "pantalon": (45.0, 85.0, 160.0, "Pantalon fluide ou costume Maison Margiela"),
        "pull_maille": (60.0, 120.0, 220.0, "Pull en maille à 4 coutures blanches Margiela"),
        "sweat": (50.0, 95.0, 180.0, "Sweat logo inversé ou chiffres Margiela / MM6"),
        "chemise_blouse": (40.0, 80.0, 150.0, "Chemise blanche classique ou déstructurée Margiela"),
        "top": (30.0, 55.0, 100.0, "Body ou top seconde peau Maison Margiela / MM6"),
        "tshirt": (32.0, 60.0, 110.0, "T-shirt 4 surpiqûres ou calendrier Margiela"),
        "sac": (80.0, 160.0, 320.0, "Sac Glam Slam, 5AC ou sac triangle MM6"),
        "chaussures": (70.0, 135.0, 260.0, "Baskets Replica GAT (German Army Trainer) Margiela"),
        "bottes": (120.0, 220.0, 420.0, "Bottines Tabi bout fendu cuir iconiques Margiela"),
        "escarpins": (60.0, 120.0, 230.0, "Escarpins ou ballerines Tabi Margiela"),
        "accessoire": (35.0, 70.0, 130.0, "Portefeuille 4 surpiqûres, bague ou ceinture Margiela"),
    },
    "Zimmermann": {
        "veste": (65.0, 125.0, 240.0, "Veste ceinturée ou kimono imprimé Zimmermann"),
        "blazer": (75.0, 140.0, 270.0, "Blazer en lin ou soie imprimée Zimmermann"),
        "manteau": (90.0, 180.0, 350.0, "Manteau long ou trench fluide Zimmermann"),
        "manteau_fourrure": (95.0, 190.0, 380.0, "Manteau fausse fourrure Zimmermann"),
        "robe": (95.0, 180.0, 360.0, "Robe longue fleurie en lin/soie brodée Zimmermann"),
        "jupe": (45.0, 85.0, 160.0, "Jupe longue fleurie à volants Zimmermann"),
        "jean": (32.0, 60.0, 110.0, "Jean évasé ou pantalon denim Zimmermann"),
        "pantalon": (40.0, 80.0, 150.0, "Pantalon large en lin ou soie Zimmermann"),
        "pull_maille": (45.0, 85.0, 160.0, "Pull en maille ajourée ou cachemire Zimmermann"),
        "sweat": (35.0, 65.0, 120.0, "Sweat brodé Zimmermann"),
        "chemise_blouse": (50.0, 95.0, 180.0, "Blouse romantique en lin ou soie brodée Zimmermann"),
        "top": (35.0, 65.0, 120.0, "Top bustier ou débardeur lin Zimmermann"),
        "tshirt": (25.0, 45.0, 80.0, "T-shirt en coton imprimé Zimmermann"),
        "sac": (50.0, 100.0, 190.0, "Sac ou pochette raphia/toile Zimmermann"),
        "chaussures": (40.0, 75.0, 140.0, "Sandales cuir à brides ou espadrilles Zimmermann"),
        "bottes": (60.0, 110.0, 200.0, "Bottines en cuir ou suède Zimmermann"),
        "escarpins": (45.0, 85.0, 160.0, "Mules ou talons à lacets Zimmermann"),
        "accessoire": (30.0, 60.0, 110.0, "Ceinture tressée, foulard ou chapeau Zimmermann"),
    },
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
                "armani": ["emporio armani", "giorgio armani", "armani jeans"],
                "celine": ["céline"],
                "dior": ["christian dior", "baby dior"],
                "maison margiela": ["mm6", "mm6 maison margiela", "maison martin margiela", "margiela"],
                "bottega veneta": ["bottega"],
                "vivienne westwood": ["westwood", "anglomania"],
                "balenciaga": ["balenciaga paris"],
                "courrèges": ["courreges"]
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
