import json
import sqlite3
import re
import os

# 1. Tier 1 Curated Benchmarks
TIER1_BENCHMARKS = {
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
        "accessoire": (40.0, 80.0, 150.0, "Ceinture boucle Triomphe, lunettes ou foulard Celine")
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
        "accessoire": (35.0, 70.0, 130.0, "Ceinture CD, lunettes de soleil ou foulard Dior")
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
        "accessoire": (50.0, 100.0, 200.0, "Ceinture chaîne, broche CC, lunettes ou foulard Chanel")
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
        "accessoire": (38.0, 75.0, 140.0, "Portefeuille tressé, ceinture ou lunettes Bottega")
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
        "accessoire": (30.0, 60.0, 110.0, "Casquette logo, lunettes de soleil ou portefeuille Balenciaga")
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
        "accessoire": (45.0, 90.0, 160.0, "Écharpe mohair et laine multicolore, ceinture Anagram")
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
        "accessoire": (25.0, 50.0, 95.0, "Bob Le Gadjo, bob Le Bob Artichaut, porte-cartes")
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
        "accessoire": (30.0, 60.0, 110.0, "Lunettes de soleil oversize, foulard ou ceinture Chloé")
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
        "accessoire": (35.0, 70.0, 130.0, "Foulard soie FF, ceinture boucle FF ou lunettes Fendi")
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
        "accessoire": (30.0, 60.0, 110.0, "Ceinture cuir boucle médaillon B Balmain")
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
        "accessoire": (30.0, 60.0, 110.0, "Ceinture boucle 4G, lunettes ou foulard Givenchy")
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
        "accessoire": (25.0, 50.0, 95.0, "Casquette, lunettes rétro ou ceinture Courrèges")
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
        "accessoire": (40.0, 75.0, 130.0, "Collier perles Orb bas relief, boucles d'oreilles Orb")
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
        "accessoire": (35.0, 70.0, 130.0, "Portefeuille 4 surpiqûres, bague ou ceinture Margiela")
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
        "accessoire": (30.0, 60.0, 110.0, "Ceinture tressée, foulard ou chapeau Zimmermann")
    }
}

# 2. Update src/scoring/resale_knowledge.py
def update_resale_knowledge_file():
    filepath = 'src/scoring/resale_knowledge.py'
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Format TIER1_BENCHMARKS as python code
    tier1_str_lines = []
    for brand, cats in TIER1_BENCHMARKS.items():
        tier1_str_lines.append(f'    "{brand}": {{')
        for cat, vals in cats.items():
            # escape string
            desc = vals[3].replace('"', '\\"')
            tier1_str_lines.append(f'        "{cat}": ({vals[0]}, {vals[1]}, {vals[2]}, "{desc}"),')
        tier1_str_lines.append('    },')

    new_dict_entries = '\n'.join(tier1_str_lines)

    # Insert before the end of CURATED_RESALE_BENCHMARKS
    # Guess is currently the last entry
    pattern = r'(\s*"Guess":\s*\{[^}]+\}\s*\n)(\})'
    replacement = r'\1' + ',\n' + new_dict_entries + '\n\\2'
    
    # Let's check if Guess is in content
    if '"Guess": {' in content and '    "Celine": {' not in content:
        # Find position of Guess's closing bracket
        # Let's do a clean search
        idx_guess = content.find('"Guess": {')
        idx_guess_end = content.find('    }\n}', idx_guess)
        if idx_guess_end != -1:
            split_pos = idx_guess_end + len('    }')
            new_content = content[:split_pos] + ',\n' + new_dict_entries + content[split_pos:]
            content = new_content
            print("Added 15 Tier 1 brands to CURATED_RESALE_BENCHMARKS")

    # Update aliases_brand
    old_aliases = '''            aliases_brand = {
                "roberto cavalli": ["cavalli", "class roberto cavalli"],
                "just cavalli": ["cavalli", "just cavalli"],
                "dolce & gabbana": ["d&g", "dolce", "dolce&gabbana"],
                "yves saint laurent": ["saint laurent", "ysl", "rive gauche"],
                "thierry mugler": ["mugler"],
                "max mara": ["sportmax", "weekend max mara", "marina rinaldi", "maxmara"],
                "armani": ["emporio armani", "giorgio armani", "armani jeans"]
            }'''

    new_aliases = '''            aliases_brand = {
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
            }'''

    if old_aliases in content:
        content = content.replace(old_aliases, new_aliases)
        print("Updated aliases_brand with Tier 1 aliases")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


# 3. Seed SQLite DB
def seed_sqlite_db():
    conn = sqlite3.connect('vinted_bot.db')
    cur = conn.cursor()
    count = 0
    for brand, cats in TIER1_BENCHMARKS.items():
        for cat, (r_min, r_target, r_max, desc) in cats.items():
            cur.execute("""
                INSERT OR REPLACE INTO resale_knowledge_base
                (brand, category, resale_min_flash, resale_target, resale_max_high, description, source)
                VALUES (?, ?, ?, ?, ?, ?, 'curated_tier1_luxury')
            """, (brand, cat, float(r_min), float(r_target), float(r_max), desc))
            count += 1
    conn.commit()
    total = cur.execute("SELECT COUNT(*) FROM resale_knowledge_base").fetchone()[0]
    conn.close()
    print(f"Seeded {count} new entries to SQLite! Total entries now: {total}")


# 4. Add Searches to config.json
TIER1_SEARCHES = [
    {
        "id": "b_celine",
        "name": "✨ CELINE",
        "enabled": True,
        "brand_ids": [1443],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_dior",
        "name": "✨ Dior",
        "enabled": True,
        "brand_ids": [671, 15430438],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_chanel",
        "name": "✨ Chanel",
        "enabled": True,
        "brand_ids": [481],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_bottega",
        "name": "✨ Bottega Veneta",
        "enabled": True,
        "brand_ids": [86972],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_balenciaga",
        "name": "✨ Balenciaga",
        "enabled": True,
        "brand_ids": [2369],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_loewe",
        "name": "✨ Loewe",
        "enabled": True,
        "brand_ids": [24209],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_jacquemus",
        "name": "✨ Jacquemus",
        "enabled": True,
        "brand_ids": [168278],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_chloe",
        "name": "✨ Chloé",
        "enabled": True,
        "brand_ids": [2113],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_fendi",
        "name": "✨ Fendi",
        "enabled": True,
        "brand_ids": [1189],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_balmain",
        "name": "✨ Balmain",
        "enabled": True,
        "brand_ids": [5101],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_givenchy",
        "name": "✨ Givenchy",
        "enabled": True,
        "brand_ids": [2371],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_courreges",
        "name": "✨ Courrèges",
        "enabled": True,
        "brand_ids": [12639],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_vivienne",
        "name": "✨ Vivienne Westwood",
        "enabled": True,
        "brand_ids": [14217],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_margiela",
        "name": "✨ Maison Margiela",
        "enabled": True,
        "brand_ids": [639289, 450765],
        "max_price": 20.0,
        "order": "newest_first"
    },
    {
        "id": "b_zimmermann",
        "name": "✨ Zimmermann",
        "enabled": True,
        "brand_ids": [172418],
        "max_price": 20.0,
        "order": "newest_first"
    }
]

def update_config_json():
    with open('config.json', 'r', encoding='utf-8') as f:
        conf = json.load(f)

    existing_ids = {s.get('id') for s in conf.get('searches', [])}
    added = 0
    for s in TIER1_SEARCHES:
        if s['id'] not in existing_ids:
            conf['searches'].append(s)
            added += 1

    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(conf, f, indent=2, ensure_ascii=False)

    print(f"Added {added} Tier 1 luxury searches to config.json! Total searches now: {len(conf['searches'])}")

if __name__ == '__main__':
    update_resale_knowledge_file()
    seed_sqlite_db()
    update_config_json()
