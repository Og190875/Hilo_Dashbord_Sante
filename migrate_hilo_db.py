"""
migrate_hilo_db.py — Hilo V8.1
Script de mise à jour de la base de données Hilo.

Usage :
    python migrate_hilo_db.py                  → utilise la base configurée dans hilo_config.json
    python migrate_hilo_db.py /chemin/hilo.db  → base spécifiée manuellement
"""

import sys
import json
import sqlite3
from pathlib import Path

# ── Localisation de la base ───────────────────────────────────────────────────

def get_db_path_from_args():
    if len(sys.argv) > 1:
        return sys.argv[1]
    return None

def get_db_path_from_config():
    config_path = Path(__file__).parent / "hilo_config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            return cfg.get("db_path")
        except Exception:
            pass
    return None

# ── Migrations ────────────────────────────────────────────────────────────────

MIGRATIONS = [
    # V7.2.4 — tables automesures
    ("am_protocoles", "CREATE TABLE IF NOT EXISTS am_protocoles (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL, statut TEXT NOT NULL DEFAULT 'en_cours', jour_debut TEXT, cree_le TEXT DEFAULT (datetime('now')), modifie_le TEXT DEFAULT (datetime('now')), moy_sys REAL, moy_dia REAL, moy_fc REAL, notes TEXT)"),
    ("am_seances",    "CREATE TABLE IF NOT EXISTS am_seances (id INTEGER PRIMARY KEY AUTOINCREMENT, protocole_id INTEGER NOT NULL REFERENCES am_protocoles(id), jour INTEGER NOT NULL, moment TEXT NOT NULL, rang INTEGER NOT NULL DEFAULT 1, sys INTEGER, dia INTEGER, fc INTEGER, saisi_le TEXT DEFAULT (datetime('now')), bras TEXT NOT NULL DEFAULT 'P')"),

    # V7.2.5 — double bras
    ("ALTER am_protocoles bras_prioritaire",       "ALTER TABLE am_protocoles ADD COLUMN bras_prioritaire TEXT NOT NULL DEFAULT 'G'"),
    ("ALTER am_protocoles bras_secondaire_actif",  "ALTER TABLE am_protocoles ADD COLUMN bras_secondaire_actif INTEGER NOT NULL DEFAULT 0"),
    ("ALTER am_seances bras",                      "ALTER TABLE am_seances ADD COLUMN bras TEXT NOT NULL DEFAULT 'P'"),

    # V7.2.6 — moyennes bras secondaire
    ("ALTER am_protocoles moy_sys_s",              "ALTER TABLE am_protocoles ADD COLUMN moy_sys_s REAL"),
    ("ALTER am_protocoles moy_dia_s",              "ALTER TABLE am_protocoles ADD COLUMN moy_dia_s REAL"),

    # V7.2.8 — historique poids
    ("poids_historique", "CREATE TABLE IF NOT EXISTS poids_historique (id INTEGER PRIMARY KEY AUTOINCREMENT, poids REAL NOT NULL, date TEXT NOT NULL DEFAULT (date('now')), note TEXT)"),

    # V7.2.x — classification mesures
    ("ALTER mesures classification",               "ALTER TABLE mesures ADD COLUMN classification TEXT DEFAULT NULL"),

    # V7.2.12 — taille/poids dans profil
    ("ALTER profil taille",                        "ALTER TABLE profil ADD COLUMN taille REAL"),
    ("ALTER profil poids",                         "ALTER TABLE profil ADD COLUMN poids REAL"),

    # V8.1 — configuration Withings (import poids)
    ("withings_config",
     """CREATE TABLE IF NOT EXISTS withings_config (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        client_id       TEXT,
        consumer_secret TEXT,
        access_token    TEXT,
        refresh_token   TEXT,
        modifie_le      TEXT NOT NULL DEFAULT (datetime('now'))
     )"""),
]

def run_migrations(db_path):
    print(f"\n🩺 Hilo — Migration base de données")
    print(f"   Base : {db_path}")
    print(f"   {'-'*50}")

    conn = sqlite3.connect(db_path)
    ok = 0
    skipped = 0
    errors = 0

    for name, sql in MIGRATIONS:
        try:
            conn.execute(sql)
            conn.commit()
            print(f"   ✅ {name}")
            ok += 1
        except sqlite3.OperationalError as e:
            err = str(e)
            if "duplicate column" in err or "already exists" in err:
                print(f"   ⏭  {name} (déjà présent)")
                skipped += 1
            else:
                print(f"   ❌ {name} → {err}")
                errors += 1
        except Exception as e:
            print(f"   ❌ {name} → {e}")
            errors += 1

    conn.close()

    print(f"   {'-'*50}")
    print(f"   ✅ {ok} migration(s) appliquée(s)")
    print(f"   ⏭  {skipped} déjà présente(s)")
    if errors:
        print(f"   ❌ {errors} erreur(s)")
    print()

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db_path = get_db_path_from_args() or get_db_path_from_config()

    if db_path and Path(db_path).exists():
        print(f"\n🩺 Base détectée : {db_path}")
        confirm = input("   Utiliser cette base ? (O/n) : ").strip().lower()
        if confirm == 'n':
            db_path = None

    if not db_path:
        print("\n🩺 Hilo — Migration base de données")
        db_path = input("   Chemin vers hilo.db : ").strip().strip('"').strip("'")

    if not db_path:
        print("❌ Aucun chemin saisi.")
        sys.exit(1)

    if not Path(db_path).exists():
        print(f"❌ Fichier introuvable : {db_path}")
        sys.exit(1)

    run_migrations(db_path)
    print("✅ Migration terminée. Vous pouvez relancer Hilo.")

if __name__ == "__main__":
    main()
