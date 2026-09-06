# 📋 Changelog — Hilo Dashboard Santé

> Versions antérieures à V9.0.0 : voir historique local (non publié sur GitHub)

---

## V9.0.8 — 06 Septembre 2026
- Fix : rafraîchissement automatique des courbes/stats Sommeil après import OSCAR V2
- Fix : bouton 💤 "pendant sommeil PPC" masqué si module Sommeil désactivé ou pas de sessions OSCAR en base (F5 requis après changement de module)
- dashboard_template.py : commentaire ajouté pour documenter la section _B64 (template Dashboard Tension encodé en base64)
- Fix : page Saisie vélo — suppression du popup "météo pas récupérée" et correction de l'enregistrement de la sortie
- Fix : direction du vent — moyenne circulaire au lieu de moyenne arithmétique (évitait erreur N→S autour de 0°/360°)
- Fix : import GPS — ne tente plus la météo pour les sorties qui en ont déjà une
- Fix : export CSV SQL — lève la limite des 1000 lignes pour exporter toutes les données
- Fix : impression Sommeil — graphiques vides corrigés (chargement forcé avant capture)
- Fix : impression Sommeil — hauteur max des donuts limitée à 200px pour équilibrer la mise en page
- Fix : rapport automesures — résumé final "Suivi continu" affiche la moyenne bracelet Hilo (au lieu du bras secondaire), avec code couleur correct (cible ou ESH)
- Amélioration : rapport automesures — poids/IMC calculé depuis la moyenne des 30 jours précédant le protocole (si module Poids actif), sinon fallback profil
- Fix : FC moyenne — exclut les valeurs à 0 (mesures sans FC renseignée) dans tous les calculs
- Fix : mesures d'automesures exclues des courbes, stats et calculs (vue mesures_hilo), sauf onglet Automesures
- Amélioration : tag automatique AUTOMESURE sur les mesures bras S (matching sys/dia exact ±10min) après import PDF ou injection protocole
- Amélioration : champ poids dans la fiche patient — grisé et non modifiable si API Withings active, affiche le dernier poids Withings
- Fix : champ poids éditable si module Poids OFF ou saisie manuelle

---

## V9.0.7 — 12 juillet 2026
- Tooltip graphique Sommeil/Détail nuit : affichage contextuel selon le dataset survolé (Pression, Sys/Dia/FC, Événement + durée)
- Météo automatique après import GPS : tentative directe sans délai codé en dur
- Si données pas encore disponibles sur le serveur : message "météo pas encore disponible sur le serveur"
- Météo au démarrage : centroïde GPS utilisé (au lieu de Troyes fixe)
- Sorties sans GPS exclues de la synchro météo automatique
- Page Saisie : bouton "Récupérer météo" supprimé, remplacé par message informatif
- README : renommage Hilo → Hilo_Dashboard, structure projet mise à jour, fonctionnalités enrichies (automesures, Paramètres, Aktiia™/Hilo™)
- Import Données : fond jaune/orange sur la zone fichier sélectionné pour meilleure visibilité
- Page Saisie vélo : bouton "Récupérer météo" supprimé, remplacé par message informatif

---

## V9.0.7 — 11 juillet 2026
- Météo automatique après import GPS : tentative directe sans délai codé en dur
- Si données pas encore disponibles sur le serveur : message "météo pas encore disponible sur le serveur"
- Météo au démarrage : centroïde GPS utilisé (au lieu de Troyes fixe)
- Sorties sans GPS exclues de la synchro météo automatique
- Bandeau météo : distinction sorties synchronisées / en attente serveur

---

## V9.0.6 — 11 juillet 2026
- Widget IAH PPC page Accueil rafraîchi automatiquement après synchro OSCAR
- Tendance IAH PPC : calcul quinzaine (Q1→Q2) au lieu de premier/dernier jour
- README mis à jour (avertissement médical, liens OSCAR)

---

## V9.0.5 — 5 juillet 2026
- Météo vélo calculée avec le centroïde GPS réel de la sortie (au lieu de Troyes fixe)
- Import GPS : INSERT OR IGNORE — les données existantes ne sont plus écrasées à chaque import
- Carte GPS : effacée proprement si pas de points GPS (plus de tracé fantôme)
- Paramètres → SQL : bouton Effacer pour vider le champ avant une nouvelle requête
- README : ajout de l'histoire du projet

---

## V9.0.4 — 3 juillet 2026
- Ajout du fichier `CHANGELOG.md`
- Mise à jour `git_push.py` avec saisie automatique des notes de version

---

## V9.0.3 — 3 juillet 2026
- `.gitignore` mis à jour (`.github/`, `git_push.py`)
- Nettoyage anciens specs (`hilo.spec`, `hilo_macos.spec`)

---

## V9.0.2 — 3 juillet 2026
- Fix exports HTML : `modules=` manquant dans tous les `render_template` (FTP, local, journalier, auto)
- Specs renommés : `hilo_windows.spec`, `hilo_macos_x64.spec`, `hilo_macos_arm.spec`
- Dossier `icons/` créé (`.ico` + `.icns`)
- `git_push.py` retiré du projet

---

## V9.0.1 — *non publié sur GitHub*
- Synchro OSCAR V2 au démarrage (badge indépendant Withings/Météo/OSCAR)
- Module `requests` ajouté pour la météo vélo

---

## V9.0.0 — 28 juin 2026 — Première publication GitHub
- Système activation/désactivation modules (`applyModules()` au chargement)
- Build Windows `.exe` via PyInstaller (Thonny)
- Modules par défaut au premier setup (tension ON, reste OFF)
- `app_modules` créée dans `init_db()`
- Shutdown Windows propre via `os._exit(0)`, délai heartbeat 120s
