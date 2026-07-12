# 🩺 Hilo — Dashboard Santé Personnel

## 💬 L'histoire du projet

Depuis fin 2024 j'utilise le bracelet connecté Hilo™ pour suivre ma tension artérielle car, comme beaucoup de personnes, je souffre d'hypertension. J'aime analyser mes données, mais les rapports de l'application du bracelet n'étaient pas exploitables.

J'ai commencé avec un petit script Python pour extraire les données en CSV et les traiter dans un tableur. Ayant également de l'apnée du sommeil, j'avais un second tableur pour ces données. L'idée est alors venue de tout centraliser dans une base de données unique, pour voir si tel ou tel paramètre avait un impact sur ma santé.

C'est ainsi qu'est né ce projet, développé avec l'aide de l'IA (Claude d'Anthropic). De fil en aiguille, j'ai ajouté mes données Withings via leur API (poids, masse grasse et musculaire, Sleep Analyzer), ainsi que l'import des points GPS de mes sorties vélo et la météo associée. Le logiciel [Oscar](https://www.sleepfiles.com/OSCAR/) (gestion de ma machine PPC) est également passé en base de données — les deux bases sont maintenant liées, sans import de CSV entre les deux systèmes.

Ce projet n'est pas encore parfait à 100%, mais il fonctionne très bien. À chaque nouvel import de données, une copie HTML est générée pour la partager avec un proche ou un médecin, ou directement sur un serveur FTP.

Merci pour votre visite, et prenez soin de vous. 🙏

*Olivier — Troyes, France*

---

## ⚠️ Avertissement médical / Medical Disclaimer

**Hilo_Dashboard n'est pas une application médicale.** Les données affichées sont fournies à titre informatif uniquement et ne constituent en aucun cas un diagnostic médical. Toute décision concernant votre santé doit être prise en concertation avec un professionnel de santé qualifié.

**Hilo_Dashboard is not a medical application.** The data displayed is provided for informational purposes only and does not constitute a medical diagnosis. Any decision regarding your health must be made in consultation with a qualified healthcare professional.

---

**Hilo_Dashboard** est un dashboard santé personnel open-source qui centralise et visualise vos données de santé au quotidien : tension artérielle, sommeil PPC (OSCAR), poids (Withings), et activités vélo (GPS).

---

## ✨ Fonctionnalités

- **Tension artérielle** — import PDF Aktiia, historique, courbes, statistiques, cibles personnalisées, protocoles d'automesures
- **Sommeil PPC** — synchronisation directe depuis OSCAR V2, détail nuit (pression, événements, IAH)
- **Poids** — suivi manuel ou synchronisation Withings API, IMC, sparkline
- **Activités vélo** — import GPS Withings, carte Leaflet, D+, météo, statistiques
- **Corrélations** — analyse croisée tension/sommeil/poids
- **Paramètres** — activation/désactivation des modules, profil, cibles, traitements, configuration Withings API, export FTP, base de données, requêtes SQL

---

## 🖥️ Stack technique

- **Backend** : Python 3.11, Flask
- **Base de données** : SQLite (`hilo.db`)
- **Frontend** : Chart.js, Tailwind CSS, Leaflet.js, Jinja2
- **Build Windows** : PyInstaller

---

## 🚀 Installation (macOS / Linux)

### Prérequis
- Python 3.11+
- pip

### Démarrage

```bash
git clone https://github.com/Og190875/Hilo.git
cd Hilo
pip install -r requirements.txt
python launch_hilo.py
```

L'application s'ouvre automatiquement dans votre navigateur sur `http://127.0.0.1:5050`.

Au premier lancement, une page de configuration vous demande de renseigner votre profil et de choisir l'emplacement de la base de données.

---

## 🪟 Build Windows (.exe)

Pour générer un `.exe` autonome sous Windows (via Python Thonny ou Python officiel) :

```bat
build_windows.bat
```

Le fichier `dist\Hilo.exe` est généré. Double-cliquez pour lancer l'application.

---

## 🍎 Build macOS (.app)

### macOS ARM (Apple Silicon — M1/M2/M3/M4)

```bash
pip install pyinstaller flask pdfplumber pandas requests
pyinstaller hilo_macos_arm.spec
```

### macOS Intel (x86_64) — depuis un Mac Apple Silicon via Rosetta

```bash
# Ouvrir un shell Rosetta
arch -x86_64 zsh

# Activer le venv Intel (à créer une fois)
# /usr/local/Cellar/python@3.11/3.11.x/bin/python3.11 -m venv ~/venv-hilo-intel
source ~/venv-hilo-intel/bin/activate

cd /chemin/vers/hilo
pyinstaller hilo_macos_x64.spec
```

Le fichier `dist/Hilo.app` est généré. Double-cliquez pour lancer l'application.

> **Note :** à la première ouverture sur macOS, faire clic droit → Ouvrir si macOS bloque l'app non signée.

---

## 📁 Structure du projet

```
hilo_final/
├── launch_hilo.py          # Point d'entrée
├── app.py                  # Routes Flask
├── hilo_db.py              # Base de données Hilo
├── sommeil_db.py           # Gestion données OSCAR/PPC
├── hilo_core.py            # Fonctions métier
├── hilo_colors.py          # Palette couleurs
├── am_rapport.py           # Rapports automesures
├── dashboard_template.py   # Template export HTML
├── migrate_hilo_db.py      # Migrations DB
├── requirements.txt        # Dépendances Python
├── hilo_windows.spec       # Config PyInstaller Windows
├── hilo_macos_x64.spec     # Config PyInstaller macOS Intel
├── hilo_macos_arm.spec     # Config PyInstaller macOS ARM
├── build_windows.bat       # Script build Windows
├── icons/
│   ├── dashboard_sante.ico   # Icône Windows
│   └── dashboard_sante.icns  # Icône macOS
├── templates/              # Templates Jinja2
└── static/                 # Fichiers statiques
```

---

## ⚙️ Configuration des modules

Dans **Paramètres → Modules**, activez ou désactivez chaque module selon vos appareils :

| Module | Description |
|--------|-------------|
| Tension | Import PDF Aktiia, bracelet Withings |
| Sommeil | Synchronisation OSCAR V2 (PPC) |
| Poids | Saisie manuelle ou API Withings |
| Activités | Import GPS Withings (vélo) |
| Corrélations | Analyses croisées |

---

## 📋 Prérequis selon les modules

- **Tension Aktiia™ / Hilo™** : exports PDF depuis l'app Aktiia™ / Hilo™
- **Sommeil OSCAR** : logiciel [OSCAR](https://www.sleepfiles.com/OSCAR/) installé avec sa base SQLite — [dépôt GitLab](https://gitlab.com/CrimsonNape/oscar-sql)
- **Poids/Activités Withings** : compte Withings + clés API (configurables dans Paramètres)

---

## 📄 Licence

MIT — libre d'utilisation, modification et distribution.

---

## 👤 Auteur

Olivier — [github.com/Og190875](https://github.com/Og190875)
