"""
hilo_db.py — Hilo V8.5.0
Module SQLite : profil utilisateur + mesures + historique imports
+ Migration versionnée + toutes tables V7.2.x
"""

import sqlite3
from pathlib import Path
from datetime import datetime, date
from contextlib import contextmanager
import pandas as pd

# ── Connexion ─────────────────────────────────────────────────────────────────
@contextmanager
def get_conn(db_path, timeout=30):
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ── Migration versionnée ──────────────────────────────────────────────────────

# Colonnes étendues à garantir dans la table profil
PROFIL_COLUMNS = {
    'cible_fc':  'INTEGER NOT NULL DEFAULT 60',
    'taille':    'INTEGER DEFAULT NULL',
    'poids':     'REAL    DEFAULT NULL',
    'jour_debut':'INTEGER NOT NULL DEFAULT 6',
    'jour_fin':  'INTEGER NOT NULL DEFAULT 22',
}

def ensure_profil_columns(conn):
    """Ajoute les colonnes manquantes dans profil — idempotent."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(profil)").fetchall()}
    for col, typedef in PROFIL_COLUMNS.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE profil ADD COLUMN {col} {typedef}")
                print(f"[DB] Colonne ajoutée : profil.{col}")
            except Exception as e:
                print(f"[DB] Impossible d'ajouter profil.{col} : {e}")

def migrate_db(conn):
    """Applique toutes les migrations manquantes."""
    # Migration structurelle des colonnes profil (toujours vérifier)
    ensure_profil_columns(conn)
    # V7.2.4 — tables automesures (CREATE IF NOT EXISTS = idempotent)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS am_protocoles (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            label               TEXT    NOT NULL DEFAULT '',
            date_debut          TEXT    NOT NULL,
            date_fin            TEXT,
            n_jours             INTEGER NOT NULL DEFAULT 3,
            n_mesures_seance    INTEGER NOT NULL DEFAULT 3,
            intervalle_minutes  INTEGER NOT NULL DEFAULT 2,
            moments             TEXT    NOT NULL DEFAULT '["MATIN","SOIR"]',
            exclusion_rang1     INTEGER NOT NULL DEFAULT 1,
            seuil_completude    INTEGER NOT NULL DEFAULT 80,
            statut              TEXT    NOT NULL DEFAULT 'EN_COURS',
            moy_sys             REAL,
            moy_dia             REAL,
            moy_fc              REAL,
            classif_mode        TEXT    NOT NULL DEFAULT 'esh',
            inject_mesures          INTEGER NOT NULL DEFAULT 1,
            bras_prioritaire        TEXT    NOT NULL DEFAULT 'G',
            bras_secondaire_actif   INTEGER NOT NULL DEFAULT 0,
            cree_le             TEXT    NOT NULL DEFAULT (datetime('now')),
            modifie_le          TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS am_seances (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            protocole_id    INTEGER NOT NULL,
            jour            INTEGER NOT NULL,
            moment          TEXT    NOT NULL,
            rang            INTEGER NOT NULL,
            systolic        INTEGER NOT NULL,
            diastolic       INTEGER NOT NULL,
            heartrate       INTEGER,
            timestamp       TEXT    NOT NULL,
            mode_saisie     TEXT    NOT NULL DEFAULT 'REEL',
            note            TEXT,
            exclu_calcul    INTEGER NOT NULL DEFAULT 0,
            injecte         INTEGER NOT NULL DEFAULT 0,
            bras            TEXT    NOT NULL DEFAULT 'P',
            cree_le         TEXT    NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (protocole_id) REFERENCES am_protocoles(id),
            UNIQUE(protocole_id, jour, moment, rang, bras)
        );
        CREATE INDEX IF NOT EXISTS idx_am_seances_proto
            ON am_seances(protocole_id, jour, moment);
    """)
    # Ajouter intervalle_minutes si absent (migration base existante)
    try:
        conn.execute('ALTER TABLE am_protocoles ADD COLUMN intervalle_minutes INTEGER NOT NULL DEFAULT 2')
    except Exception:
        pass  # Colonne déjà présente
    # Ajouter classification manuelle sur mesures
    try:
        conn.execute("ALTER TABLE mesures ADD COLUMN classification TEXT DEFAULT NULL")
    except Exception:
        pass
    # V7.2.6 : moyennes bras secondaire
    for _col in ["ALTER TABLE am_protocoles ADD COLUMN moy_sys_s REAL",
                 "ALTER TABLE am_protocoles ADD COLUMN moy_dia_s REAL"]:
        try: conn.execute(_col)
        except Exception: pass
    # V7.2.5 : double bras — colonnes
    for col_sql in [
        "ALTER TABLE am_protocoles ADD COLUMN bras_prioritaire TEXT NOT NULL DEFAULT 'G'",
        "ALTER TABLE am_protocoles ADD COLUMN bras_secondaire_actif INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE am_seances ADD COLUMN bras TEXT NOT NULL DEFAULT 'P'",
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass
    # V8.1 : masse grasse & masse musculaire dans poids_historique
    for col_sql in [
        "ALTER TABLE poids_historique ADD COLUMN masse_grasse REAL DEFAULT NULL",
        "ALTER TABLE poids_historique ADD COLUMN masse_musculaire REAL DEFAULT NULL",
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass

    # V7.2.5 : recréer am_seances si la contrainte UNIQUE ne contient pas encore 'bras'
    tbl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='am_seances'"
    ).fetchone()
    tbl_ddl = (tbl[0] if tbl else '').lower()
    if 'unique' in tbl_ddl and 'bras' not in tbl_ddl:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS am_seances_v725 (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                protocole_id    INTEGER NOT NULL,
                jour            INTEGER NOT NULL,
                moment          TEXT    NOT NULL,
                rang            INTEGER NOT NULL,
                systolic        INTEGER NOT NULL,
                diastolic       INTEGER NOT NULL,
                heartrate       INTEGER,
                timestamp       TEXT    NOT NULL,
                mode_saisie     TEXT    NOT NULL DEFAULT 'REEL',
                note            TEXT,
                exclu_calcul    INTEGER NOT NULL DEFAULT 0,
                injecte         INTEGER NOT NULL DEFAULT 0,
                bras            TEXT    NOT NULL DEFAULT 'P',
                cree_le         TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (protocole_id) REFERENCES am_protocoles(id),
                UNIQUE(protocole_id, jour, moment, rang, bras)
            );
            INSERT OR IGNORE INTO am_seances_v725
                (id, protocole_id, jour, moment, rang, systolic, diastolic,
                 heartrate, timestamp, mode_saisie, note, exclu_calcul, injecte, bras, cree_le)
            SELECT id, protocole_id, jour, moment, rang, systolic, diastolic,
                   heartrate, timestamp, mode_saisie, note, exclu_calcul, injecte,
                   COALESCE(bras, 'P'), cree_le
            FROM am_seances;
            DROP TABLE am_seances;
            ALTER TABLE am_seances_v725 RENAME TO am_seances;
            CREATE INDEX IF NOT EXISTS idx_am_seances_proto
                ON am_seances(protocole_id, jour, moment);
        """)

# ── Création de la base ───────────────────────────────────────────────────────
def init_db(db_path):
    """Crée la base et les tables si elles n'existent pas."""
    # executescript() fait un commit implicite — connexion séparée obligatoire
    conn0 = sqlite3.connect(str(db_path))
    conn0.executescript("""
            -- ── Tables existantes ──────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS profil (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                nom         TEXT    NOT NULL DEFAULT '',
                prenom      TEXT    NOT NULL DEFAULT '',
                naissance   TEXT    NOT NULL DEFAULT '',
                sexe        TEXT    NOT NULL DEFAULT 'M',
                cible_sys   INTEGER NOT NULL DEFAULT 130,
                cible_dia   INTEGER NOT NULL DEFAULT 80,
                cible_fc    INTEGER NOT NULL DEFAULT 60,
                taille      INTEGER DEFAULT NULL,
                poids       REAL    DEFAULT NULL,
                jour_debut  INTEGER NOT NULL DEFAULT 6,
                jour_fin    INTEGER NOT NULL DEFAULT 22,
                cree_le     TEXT    NOT NULL DEFAULT (datetime('now')),
                modifie_le  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mesures (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL UNIQUE,
                systolic    INTEGER NOT NULL,
                diastolic   INTEGER NOT NULL,
                heartrate   INTEGER NOT NULL,
                source_pdf  TEXT    DEFAULT '',
                importe_le  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_mesures_ts ON mesures(timestamp);

            CREATE TABLE IF NOT EXISTS imports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_name    TEXT    NOT NULL,
                date_import TEXT    NOT NULL DEFAULT (datetime('now')),
                n_extraites INTEGER NOT NULL DEFAULT 0,
                n_ajoutees  INTEGER NOT NULL DEFAULT 0,
                n_doublons  INTEGER NOT NULL DEFAULT 0,
                erreur      TEXT    DEFAULT NULL
            );

            -- ── Versioning BDD ─────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS db_version (
                version      INTEGER PRIMARY KEY,
                appliquee_le TEXT    NOT NULL DEFAULT (datetime('now')),
                description  TEXT    DEFAULT ''
            );

            -- ── Paramètres génériques extensibles ──────────────────────────
            CREATE TABLE IF NOT EXISTS hilo_settings (
                cle         TEXT    PRIMARY KEY,
                valeur      TEXT,
                description TEXT,
                modifie_le  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- ── Traçabilité toutes opérations ──────────────────────────────
            CREATE TABLE IF NOT EXISTS hilo_historique (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date_op     TEXT    NOT NULL DEFAULT (datetime('now')),
                type        TEXT    NOT NULL,
                description TEXT,
                detail      TEXT,
                utilisateur TEXT    DEFAULT 'default'
            );

            -- ── Traitements médicaux ───────────────────────────────────────
            CREATE TABLE IF NOT EXISTS traitements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                medicament  TEXT    NOT NULL,
                dosage      TEXT,
                moment      TEXT    NOT NULL DEFAULT 'matin',
                date_debut  TEXT,
                date_fin    TEXT    DEFAULT NULL,
                note        TEXT,
                cree_le     TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- ── Protocoles automesures V7.2.4 ──────────────────────────────
            CREATE TABLE IF NOT EXISTS am_protocoles (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                label               TEXT    NOT NULL DEFAULT '',
                date_debut          TEXT    NOT NULL,
                date_fin            TEXT,
                n_jours             INTEGER NOT NULL DEFAULT 3,
                n_mesures_seance    INTEGER NOT NULL DEFAULT 3,
                moments             TEXT    NOT NULL DEFAULT '["MATIN","SOIR"]',
                exclusion_rang1     INTEGER NOT NULL DEFAULT 1,
                seuil_completude    INTEGER NOT NULL DEFAULT 80,
                statut              TEXT    NOT NULL DEFAULT 'EN_COURS',
                moy_sys             REAL,
                moy_dia             REAL,
                moy_fc              REAL,
                classif_mode        TEXT    NOT NULL DEFAULT 'esh',
                inject_mesures      INTEGER NOT NULL DEFAULT 1,
                cree_le             TEXT    NOT NULL DEFAULT (datetime('now')),
                modifie_le          TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- ── Séances automesures V7.2.4 ─────────────────────────────────
            CREATE TABLE IF NOT EXISTS am_seances (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                protocole_id    INTEGER NOT NULL,
                jour            INTEGER NOT NULL,
                moment          TEXT    NOT NULL,
                rang            INTEGER NOT NULL,
                systolic        INTEGER NOT NULL,
                diastolic       INTEGER NOT NULL,
                heartrate       INTEGER,
                timestamp       TEXT    NOT NULL,
                mode_saisie     TEXT    NOT NULL DEFAULT 'REEL',
                note            TEXT,
                exclu_calcul    INTEGER NOT NULL DEFAULT 0,
                injecte         INTEGER NOT NULL DEFAULT 0,
                cree_le         TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (protocole_id) REFERENCES am_protocoles(id),
                UNIQUE(protocole_id, jour, moment, rang)
            );

            CREATE INDEX IF NOT EXISTS idx_am_seances_proto
                ON am_seances(protocole_id, jour, moment);

            -- ── Suivi du poids ─────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS poids_historique (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                poids       REAL    NOT NULL,
                mesure_le   TEXT    NOT NULL DEFAULT (datetime('now')),
                note        TEXT,
                cree_le     TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- ── Tables de réserve ──────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS hilo_reserve_1 (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_id      INTEGER,
                ref_table   TEXT,
                cle         TEXT,
                valeur      TEXT,
                cree_le     TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS hilo_tags (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_id      INTEGER,
                ref_table   TEXT,
                tag         TEXT,
                cree_le     TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS hilo_alertes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                type        TEXT,
                message     TEXT,
                lu          INTEGER NOT NULL DEFAULT 0,
                cree_le     TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS withings_config (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                client_id       TEXT,
                consumer_secret TEXT,
                access_token    TEXT,
                refresh_token   TEXT,
                modifie_le      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- ── Modules actifs/inactifs ────────────────────────────────────
            CREATE TABLE IF NOT EXISTS app_modules (
                module       TEXT    PRIMARY KEY,
                actif        INTEGER NOT NULL DEFAULT 1,
                poids_manuel INTEGER NOT NULL DEFAULT 0,
                poids_api    INTEGER NOT NULL DEFAULT 0
            );
        """)
    conn0.commit()
    conn0.close()
    # Migration dans une connexion séparée (après executescript)
    with get_conn(db_path) as conn:
        migrate_db(conn)
    # Créer les tables sommeil (sommeil_withings, sommeil_ppc, oscar_sessions...)
    try:
        import sommeil_db as _sdb
        with get_conn(db_path) as conn:
            _sdb.migrate_sommeil(conn)
    except Exception as _e:
        print(f"[init_db] migrate_sommeil ignorée : {_e}")

def db_exists(db_path):
    """Vérifie si la base existe et contient un profil."""
    p = Path(db_path)
    if not p.exists():
        return False
    try:
        with get_conn(db_path) as conn:
            row = conn.execute("SELECT id FROM profil WHERE id=1").fetchone()
            return row is not None
    except Exception:
        return False

# ── Profil ────────────────────────────────────────────────────────────────────
def save_profil(db_path, nom, prenom, naissance, sexe, cible_sys, cible_dia,
                cible_fc=60, taille=None, poids=None, jour_debut=6, jour_fin=22):
    """Crée ou met à jour le profil (id=1, toujours une seule ligne)."""
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO profil (id, nom, prenom, naissance, sexe,
                cible_sys, cible_dia, cible_fc, taille, poids,
                jour_debut, jour_fin, modifie_le)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                nom        = excluded.nom,
                prenom     = excluded.prenom,
                naissance  = excluded.naissance,
                sexe       = excluded.sexe,
                cible_sys  = excluded.cible_sys,
                cible_dia  = excluded.cible_dia,
                cible_fc   = excluded.cible_fc,
                taille     = excluded.taille,
                poids      = excluded.poids,
                jour_debut = excluded.jour_debut,
                jour_fin   = excluded.jour_fin,
                modifie_le = datetime('now')
        """, (nom, prenom, naissance, sexe,
              int(cible_sys), int(cible_dia), int(cible_fc),
              taille, poids, int(jour_debut), int(jour_fin)))

def get_profil(db_path):
    """Retourne le profil sous forme de dict, ou None."""
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM profil WHERE id=1").fetchone()
        if not row:
            return None
        p = dict(row)
        # Valeurs par défaut défensives pour colonnes potentiellement absentes
        p.setdefault('cible_fc',   60)
        p.setdefault('taille',     None)
        p.setdefault('poids',      None)
        p.setdefault('jour_debut', 6)
        p.setdefault('jour_fin',   22)
        # Calculer l'âge dynamiquement
        try:
            naiss = datetime.strptime(p["naissance"], "%Y-%m-%d").date()
            today = date.today()
            age   = today.year - naiss.year - (
                (today.month, today.day) < (naiss.month, naiss.day)
            )
            p["age"] = age
        except Exception:
            p["age"] = "?"
        # Symbole sexe
        p["sexe_symbol"] = "♂" if p["sexe"] == "M" else "♀"
        return p

# ── Mesures ───────────────────────────────────────────────────────────────────
def normalize_ts(ts_str):
    """Normalise timestamp → YYYY-MM-DDTHH:MM."""
    import re
    ts = str(ts_str).strip()
    ts = re.sub(r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}).*$', r'\1T\2', ts)
    ts = re.sub(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}).*$',     r'\1',    ts)
    return ts

def inject_mesures(db_path, df, source_pdf=""):
    """
    Injecte un DataFrame de mesures dans la base.
    Retourne dict: {added, duplicates, total, error}
    """
    try:
        df = df.copy()
        df["timestamp"] = df["timestamp"].apply(normalize_ts)
        for col in ["systolic","diastolic","heartrate"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["systolic","diastolic","heartrate"])
        df[["systolic","diastolic","heartrate"]] = \
            df[["systolic","diastolic","heartrate"]].astype(int)

        added = 0
        duplicates = 0
        with get_conn(db_path) as conn:
            for _, row in df.iterrows():
                try:
                    conn.execute("""
                        INSERT INTO mesures (timestamp, systolic, diastolic, heartrate, source_pdf)
                        VALUES (?, ?, ?, ?, ?)
                    """, (row["timestamp"], int(row["systolic"]),
                          int(row["diastolic"]), int(row["heartrate"]), source_pdf))
                    added += 1
                except sqlite3.IntegrityError:
                    duplicates += 1

            total = conn.execute("SELECT COUNT(*) FROM mesures").fetchone()[0]

        return {"added": added, "duplicates": duplicates, "total": total, "error": None}
    except Exception as e:
        return {"added": 0, "duplicates": 0, "total": 0, "error": str(e)}

def get_mesures(db_path, date_start=None, date_end=None):
    """Retourne les mesures sous forme de liste de dicts."""
    sql  = "SELECT * FROM mesures"
    args = []
    conditions = []
    if date_start:
        conditions.append("timestamp >= ?")
        args.append(date_start)
    if date_end:
        conditions.append("timestamp <= ?")
        args.append(date_end + "T23:59")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY timestamp"

    with get_conn(db_path) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]

def get_mesures_page(db_path, page=1, per_page=50, search="", date_start=None, date_end=None):
    """Retourne les mesures paginées avec total."""
    conditions = []
    args = []
    if search:
        conditions.append("timestamp LIKE ?")
        args.append(f"%{search}%")
    if date_start:
        conditions.append("timestamp >= ?")
        args.append(date_start)
    if date_end:
        conditions.append("timestamp <= ?")
        args.append(date_end + "T23:59")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * per_page
    with get_conn(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM mesures{where}", args).fetchone()[0]
        rows  = conn.execute(
            f"SELECT * FROM mesures{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            args + [per_page, offset]
        ).fetchall()
    return {"total": total, "page": page, "per_page": per_page,
            "rows": [dict(r) for r in rows]}

def update_mesure(db_path, mesure_id, systolic, diastolic, heartrate, classification=None):
    """Met à jour une mesure existante."""
    with get_conn(db_path) as conn:
        conn.execute("""
            UPDATE mesures SET systolic=?, diastolic=?, heartrate=? WHERE id=?
        """, (int(systolic), int(diastolic), int(heartrate), int(mesure_id)))

def delete_mesure(db_path, mesure_id):
    """Supprime une mesure par son id."""
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM mesures WHERE id=?", (int(mesure_id),))


def get_stats_db(db_path):
    """Retourne des stats globales sur la base."""
    with get_conn(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM mesures").fetchone()[0]
        minmax = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM mesures"
        ).fetchone()
        n_imports = conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]

        # Stats tables supplémentaires
        def _count(sql):
            try: return conn.execute(sql).fetchone()[0]
            except: return 0

        n_poids     = _count("SELECT COUNT(*) FROM poids_historique")
        n_sw        = _count("SELECT COUNT(*) FROM sommeil_withings")
        n_sw_api    = _count("SELECT COUNT(*) FROM sommeil_withings_api")
        n_ppc       = _count("SELECT COUNT(*) FROM sommeil_ppc")
        n_am        = _count("SELECT COUNT(*) FROM am_protocoles")
        n_traitements = _count("SELECT COUNT(*) FROM traitements")

        poids_minmax = conn.execute(
            "SELECT MIN(date(mesure_le)), MAX(date(mesure_le)) FROM poids_historique"
        ).fetchone()
        try:
            sw_minmax = conn.execute(
                "SELECT MIN(date), MAX(date) FROM sommeil_withings"
            ).fetchone()
        except Exception:
            sw_minmax = (None, None)
        try:
            ppc_minmax = conn.execute(
                "SELECT MIN(date), MAX(date) FROM sommeil_ppc"
            ).fetchone()
        except Exception:
            ppc_minmax = (None, None)

    # Taille du fichier DB
    import os as _os
    try:
        db_size_mb = round(_os.path.getsize(db_path) / (1024*1024), 1)
    except Exception:
        db_size_mb = None

    # Format EU des dates
    from datetime import date as _date
    MOIS_FR = ['Jan','Fév','Mar','Avr','Mai','Juin','Juil','Aoû','Sep','Oct','Nov','Déc']
    def _eu(iso):
        if not iso or iso == '—': return '—'
        try:
            d = _date.fromisoformat(str(iso)[:10])
            return f"{d.day:02d} {MOIS_FR[d.month-1]} {d.year}"
        except: return str(iso)

    return {
        "n_mesures":      n,
        "date_min":       minmax[0][:10] if minmax[0] else "—",
        "date_max":       minmax[1][:10] if minmax[1] else "—",
        "n_imports":      n_imports,
        "n_poids":        n_poids,
        "poids_min":      _eu(poids_minmax[0]),
        "poids_max":      _eu(poids_minmax[1]),
        "n_sommeil_w":    n_sw,
        "n_sommeil_api":  n_sw_api,
        "sw_min":         _eu(sw_minmax[0]),
        "sw_max":         _eu(sw_minmax[1]),
        "n_sommeil_ppc":  n_ppc,
        "ppc_min":        _eu(ppc_minmax[0]),
        "ppc_max":        _eu(ppc_minmax[1]),
        "n_am":           n_am,
        "n_traitements":  n_traitements,
        "db_size_mb":     db_size_mb,
    }

def log_import(db_path, pdf_name, n_extraites, n_ajoutees, n_doublons, erreur=None):
    """Enregistre un import dans l'historique."""
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO imports (pdf_name, n_extraites, n_ajoutees, n_doublons, erreur)
            VALUES (?, ?, ?, ?, ?)
        """, (pdf_name, n_extraites, n_ajoutees, n_doublons, erreur))

def get_imports(db_path, limit=20):
    """Retourne les derniers imports."""
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM imports ORDER BY date_import DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

def reset_mesures(db_path):
    """Supprime toutes les mesures (garde le profil et l'historique)."""
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM mesures")
        conn.execute("DELETE FROM imports")

def reset_all(db_path):
    """Réinitialisation complète — supprime la base."""
    Path(db_path).unlink(missing_ok=True)

def backup_db(db_path):
    """Copie la base vers un fichier horodaté dans le même dossier.
    Retourne le chemin du backup créé."""
    from datetime import datetime
    import shutil
    src = Path(db_path)
    ts  = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    dst = src.parent / f"hilo_backup_{ts}.db"
    shutil.copy2(str(src), str(dst))
    return str(dst)

def restore_db(db_path, backup_path):
    """Restaure la base depuis un fichier backup.
    Vérifie l'intégrité du backup, sauvegarde la base actuelle, puis remplace.
    Retourne dict {ok, backup_created, error}."""
    import shutil
    backup = Path(backup_path)
    if not backup.exists():
        return {"ok": False, "error": "Fichier backup introuvable"}
    # Vérifier l'intégrité du backup
    try:
        import sqlite3
        conn = sqlite3.connect(str(backup))
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        if result != "ok":
            return {"ok": False, "error": f"Backup corrompu : {result}"}
    except Exception as e:
        return {"ok": False, "error": f"Lecture backup impossible : {e}"}
    # Sauvegarder la base actuelle avant remplacement
    try:
        saved = backup_db(db_path)
    except Exception as e:
        saved = None
    # Remplacer
    try:
        shutil.copy2(str(backup), str(db_path))
        return {"ok": True, "backup_created": saved}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def integrity_check(db_path):
    """Lance PRAGMA integrity_check + freelist_count sur la base.
    Filtre les avertissements bénins (pages libres 'never used').
    Retourne dict {ok, result, errors, warnings}."""
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        conn.close()
        results = [r[0] for r in rows]
        # Séparer vraies erreurs et avertissements bénins (pages libres)
        real_errors = [r for r in results if r != "ok" and "never used" not in r]
        warnings    = [r for r in results if "never used" in r]
        ok = len(real_errors) == 0
        return {
            "ok":        ok,
            "result":    "ok" if ok else "Erreurs détectées",
            "errors":    real_errors,
            "warnings":  warnings,
            "freelist":  freelist,
            "page_count": page_count,
            "note":      f"{freelist} page(s) libre(s) sur {page_count} — normal après suppressions. Lancez VACUUM pour optimiser." if freelist > 0 else ""
        }
    except Exception as e:
        return {"ok": False, "result": str(e), "errors": [str(e)], "warnings": []}

def open_folder(db_path):
    """Retourne le chemin du dossier contenant la base."""
    return str(Path(db_path).parent)

# ── Import depuis hilo.csv ────────────────────────────────────────────────────
def import_from_csv(db_path, csv_path):
    """
    Importe un hilo.csv existant dans la base SQLite.
    Retourne dict stats.
    """
    try:
        df = pd.read_csv(csv_path)
        df.columns = [c.lower() for c in df.columns]
        required = {"timestamp","systolic","diastolic","heartrate"}
        if not required.issubset(set(df.columns)):
            return {"added":0,"duplicates":0,"total":0,
                    "error":f"Colonnes manquantes : {required - set(df.columns)}"}
        result = inject_mesures(db_path, df, source_pdf="import_csv")
        if not result["error"]:
            log_import(db_path, str(csv_path), len(df),
                      result["added"], result["duplicates"])
        return result
    except Exception as e:
        return {"added":0,"duplicates":0,"total":0,"error":str(e)}

# ── Paramètres hilo_settings ──────────────────────────────────────────────────
def get_setting(db_path, cle, default=None):
    """Retourne la valeur d'un paramètre."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT valeur FROM hilo_settings WHERE cle=?", (cle,)
        ).fetchone()
        return row[0] if row else default

def set_setting(db_path, cle, valeur, description=""):
    """Enregistre ou met à jour un paramètre."""
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO hilo_settings (cle, valeur, description, modifie_le)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(cle) DO UPDATE SET
                valeur     = excluded.valeur,
                modifie_le = datetime('now')
        """, (cle, str(valeur), description))

# ── Historique opérations ─────────────────────────────────────────────────────
def log_historique(db_path, type_op, description, detail=None):
    """Enregistre une opération dans l'historique."""
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO hilo_historique (type, description, detail)
            VALUES (?, ?, ?)
        """, (type_op, description, detail))

def get_historique(db_path, limit=50):
    """Retourne les dernières opérations."""
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM hilo_historique
            ORDER BY date_op DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

# ── Poids ─────────────────────────────────────────────────────────────────────
def save_poids(db_path, poids, note=""):
    """Enregistre une nouvelle mesure de poids."""
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO poids_historique (poids, note)
            VALUES (?, ?)
        """, (float(poids), note))
    log_historique(db_path, "POIDS", f"Poids enregistré : {poids} kg")

def get_poids_historique(db_path):
    """Retourne l'historique des poids."""
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM poids_historique ORDER BY mesure_le DESC
        """).fetchall()
    return [dict(r) for r in rows]

def get_poids_actuel(db_path):
    """Retourne le dernier poids enregistré."""
    with get_conn(db_path) as conn:
        row = conn.execute("""
            SELECT poids FROM poids_historique ORDER BY mesure_le DESC LIMIT 1
        """).fetchone()
    return row[0] if row else None

# ── Withings ──────────────────────────────────────────────────────────────────

def get_withings_config(db_path):
    """Retourne la config Withings (ou None)."""
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM withings_config WHERE id=1").fetchone()
    return dict(row) if row else {}

def save_withings_credentials(db_path, client_id, consumer_secret):
    """Sauvegarde client_id et consumer_secret (sans toucher aux tokens)."""
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO withings_config (id, client_id, consumer_secret)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                client_id       = excluded.client_id,
                consumer_secret = excluded.consumer_secret,
                modifie_le      = datetime('now')
        """, (client_id, consumer_secret))

def save_withings_tokens(db_path, access_token, refresh_token):
    """Sauvegarde les tokens OAuth Withings."""
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO withings_config (id, access_token, refresh_token)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                access_token  = excluded.access_token,
                refresh_token = excluded.refresh_token,
                modifie_le    = datetime('now')
        """, (access_token, refresh_token))

def save_poids_withings(db_path, date_str, poids_kg,
                        masse_grasse=None, masse_musculaire=None):
    """Insère ou met à jour une mesure Withings pour un jour donné.
    date_str : 'YYYY-MM-DD'
    Si la ligne existe déjà, on complète les colonnes masse_grasse / masse_musculaire
    si elles sont NULL et qu'on dispose d'une nouvelle valeur.
    Retourne True si une ligne a été insérée, False si doublon poids ignoré.
    """
    with get_conn(db_path) as conn:
        existing = conn.execute("""
            SELECT id, masse_grasse, masse_musculaire
            FROM poids_historique
            WHERE date(mesure_le) = ?
        """, (date_str,)).fetchone()
        if existing:
            # Mise à jour des colonnes composition si absentes
            updates, params = [], []
            if masse_grasse is not None and existing["masse_grasse"] is None:
                updates.append("masse_grasse = ?"); params.append(masse_grasse)
            if masse_musculaire is not None and existing["masse_musculaire"] is None:
                updates.append("masse_musculaire = ?"); params.append(masse_musculaire)
            if updates:
                params.append(existing["id"])
                conn.execute(
                    f"UPDATE poids_historique SET {', '.join(updates)} WHERE id = ?",
                    params
                )
            return False   # doublon poids ignoré
        conn.execute("""
            INSERT INTO poids_historique
                (poids, masse_grasse, masse_musculaire, mesure_le, cree_le, note)
            VALUES (?, ?, ?, ?, ?, 'Withings')
        """, (float(poids_kg), masse_grasse, masse_musculaire,
              f"{date_str} 08:00:00", f"{date_str} 08:00:00"))
    return True

# ── Traitements ───────────────────────────────────────────────────────────────

def get_traitements(db_path):
    """Retourne tous les traitements triés par date_debut DESC."""
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM traitements ORDER BY date_debut DESC, cree_le DESC
        """).fetchall()
    return [dict(r) for r in rows]

def add_traitement(db_path, medicament, dosage, moments, date_debut, date_fin=None, note=None):
    """Ajoute un nouveau traitement. moments = liste ex: ['matin','soir']."""
    moment_str = ",".join(moments) if isinstance(moments, list) else moments
    with get_conn(db_path) as conn:
        cur = conn.execute("""
            INSERT INTO traitements (medicament, dosage, moment, date_debut, date_fin, note)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (medicament.strip(), dosage, moment_str, date_debut, date_fin or None, note))
        return cur.lastrowid

def update_traitement(db_path, traitement_id, medicament, dosage, moments, date_debut, date_fin=None, note=None):
    """Met à jour un traitement existant."""
    moment_str = ",".join(moments) if isinstance(moments, list) else moments
    with get_conn(db_path) as conn:
        conn.execute("""
            UPDATE traitements
            SET medicament=?, dosage=?, moment=?, date_debut=?, date_fin=?, note=?
            WHERE id=?
        """, (medicament.strip(), dosage, moment_str, date_debut, date_fin or None, note, int(traitement_id)))

def delete_traitement(db_path, traitement_id):
    """Supprime un traitement."""
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM traitements WHERE id=?", (int(traitement_id),))



# ── Page d'accueil — stats 30j glissants + tendance ──────────────────────────

def get_home_stats(db_path):
    """
    Retourne toutes les données nécessaires à la page d'accueil :
    - Stats globales (n total, plage dates, dernier import)
    - Stats 30j glissants : moyenne sys/dia/fc, distribution classification
    - Tendance mensuelle sys/dia (régression linéaire sur 30j)
    - Position vs cible (écart moyen 30j)
    """
    from datetime import date, timedelta
    import math

    today = date.today()
    d30   = (today - timedelta(days=30)).isoformat()

    with get_conn(db_path) as conn:
        # ── Global ──────────────────────────────────────────────────────
        n_total = conn.execute("SELECT COUNT(*) FROM mesures").fetchone()[0]
        mm = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM mesures"
        ).fetchone()
        last_import = conn.execute(
            "SELECT pdf_name, date_import FROM imports ORDER BY date_import DESC LIMIT 1"
        ).fetchone()

        # ── 30 jours glissants ───────────────────────────────────────────
        rows30 = conn.execute("""
            SELECT timestamp, systolic, diastolic, heartrate
            FROM mesures
            WHERE timestamp >= ?
            ORDER BY timestamp
        """, (d30 + 'T00:00',)).fetchall()

    rows30 = [dict(r) for r in rows30]
    n30    = len(rows30)

    # Valeurs par défaut
    result = {
        "n_total":        n_total,
        "date_min":       mm[0][:10] if mm[0] else None,
        "date_max":       mm[1][:10] if mm[1] else None,
        "date_min_eu":    _fmt_eu(mm[0][:10]) if mm[0] else "—",
        "date_max_eu":    _fmt_eu(mm[1][:10]) if mm[1] else "—",
        "last_import":    dict(last_import) if last_import else None,
        "n30":            n30,
        "moy_sys30":      None, "moy_dia30": None, "moy_fc30": None,
        "tendance_sys":   None, "tendance_dia": None,
        "ecart_sys30":    None, "ecart_dia30":  None,
        "donut_sys30":    {}, "donut_dia30":    {},
        "sparkline_sys":  [], "sparkline_dia":  [],
        "spark_dates":    [],
    }

    if n30 == 0:
        return result

    sys_vals = [r["systolic"]  for r in rows30]
    dia_vals = [r["diastolic"] for r in rows30]
    fc_vals  = [r["heartrate"] for r in rows30 if r["heartrate"]]

    result["moy_sys30"] = round(sum(sys_vals) / n30, 1)
    result["moy_dia30"] = round(sum(dia_vals) / n30, 1)
    result["moy_fc30"]  = round(sum(fc_vals)  / len(fc_vals), 1) if fc_vals else None

    # ── Tendance : régression linéaire (mmHg/mois) ───────────────────────
    def tendance_mmhg_mois(day_vals_dict):
        """Régression linéaire sur moyennes journalières → mmHg/mois."""
        days = sorted(day_vals_dict.keys())
        n = len(days)
        if n < 2:
            return 0.0
        # Utiliser le rang du jour (0..n-1) comme x, moyenne journalière comme y
        ys = [sum(day_vals_dict[d]) / len(day_vals_dict[d]) for d in days]
        xs = list(range(n))
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs)
        if den == 0:
            return 0.0
        # pente en mmHg/jour × 30 = mmHg/mois
        slope_per_day = num / den
        return round(slope_per_day * 30, 1)

    # Regrouper par jour pour la régression (même données que sparklines)
    from collections import defaultdict as _dd
    day_sys_reg = _dd(list)
    day_dia_reg = _dd(list)
    for r in rows30:
        d = r["timestamp"][:10]
        day_sys_reg[d].append(r["systolic"])
        day_dia_reg[d].append(r["diastolic"])

    result["tendance_sys"] = tendance_mmhg_mois(day_sys_reg)
    result["tendance_dia"] = tendance_mmhg_mois(day_dia_reg)

    # ── Écart vs cible ──────────────────────────────────────────────────
    profil = get_profil(db_path)
    if profil:
        cible_sys = profil.get("cible_sys", 130)
        cible_dia = profil.get("cible_dia", 80)
        result["ecart_sys30"] = round(result["moy_sys30"] - cible_sys, 1)
        result["ecart_dia30"] = round(result["moy_dia30"] - cible_dia, 1)

    # ── Distribution classification 30j (pour donuts) ─────────────────
    from hilo_colors import get_classification

    def classif_sys_only(sys):
        """Classification basée uniquement sur la systolique."""
        if   sys < 120: return "optimale"
        elif sys < 130: return "normale"
        elif sys < 140: return "elevee"
        elif sys < 160: return "hta1"
        elif sys < 180: return "hta2"
        else:           return "hta3"

    def classif_dia_only(dia):
        """Classification basée uniquement sur la diastolique (bornes ESH)."""
        if   dia < 80:  return "optimale"
        elif dia < 85:  return "normale"
        elif dia < 90:  return "elevee"
        elif dia < 100: return "hta1"
        elif dia < 110: return "hta2"
        else:           return "hta3"

    counts_sys = {"optimale":0,"normale":0,"elevee":0,"hta1":0,"hta2":0,"hta3":0}
    counts_dia = {"optimale":0,"normale":0,"elevee":0,"hta1":0,"hta2":0,"hta3":0}
    for r in rows30:
        cs = classif_sys_only(r["systolic"])
        cd = classif_dia_only(r["diastolic"])
        counts_sys[cs] = counts_sys.get(cs, 0) + 1
        counts_dia[cd] = counts_dia.get(cd, 0) + 1
    result["donut_sys30"] = {k: round(v / n30 * 100, 1) for k, v in counts_sys.items() if v}
    result["donut_dia30"] = {k: round(v / n30 * 100, 1) for k, v in counts_dia.items() if v}

    # ── Sparklines : moyenne journalière 30j ──────────────────────────
    from collections import defaultdict
    day_sys = defaultdict(list)
    day_dia = defaultdict(list)
    for r in rows30:
        d = r["timestamp"][:10]
        day_sys[d].append(r["systolic"])
        day_dia[d].append(r["diastolic"])
    days_sorted = sorted(day_sys.keys())
    result["spark_dates"]   = days_sorted
    result["sparkline_sys"] = [round(sum(day_sys[d])/len(day_sys[d]),1) for d in days_sorted]
    result["sparkline_dia"] = [round(sum(day_dia[d])/len(day_dia[d]),1) for d in days_sorted]

    # ── IAH PPC 30 jours (depuis sommeil_ppc) ────────────────────────────
    try:
        with get_conn(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            if "sommeil_ppc" in tables:
                rows_iah = conn.execute("""
                    SELECT date, iah FROM sommeil_ppc
                    WHERE date >= ? AND iah IS NOT NULL
                    ORDER BY date
                """, (d30,)).fetchall()
                if rows_iah:
                    iah_vals  = [r[1] for r in rows_iah]
                    n         = len(iah_vals)
                    moy_iah   = round(sum(iah_vals) / n, 2)
                    n_iah_ok  = sum(1 for v in iah_vals if v < 5)
                    n_iah_mod = sum(1 for v in iah_vals if 5 <= v < 15)
                    n_iah_elv = sum(1 for v in iah_vals if v >= 15)
                    # Tendance : moyenne Q2 (15 derniers jours) vs Q1 (15 premiers jours)
                    mi        = n // 2
                    moy_q1    = round(sum(iah_vals[:mi]) / mi, 2) if mi > 0 else None
                    moy_q2    = round(sum(iah_vals[mi:]) / (n - mi), 2) if (n - mi) > 0 else None
                    delta_q   = round(moy_q2 - moy_q1, 2) if moy_q1 is not None and moy_q2 is not None else None
                    result["iah_ppc_30"] = {
                        "moy":      moy_iah,
                        "n_nuits":  n,
                        "n_ok":     n_iah_ok,
                        "n_mod":    n_iah_mod,
                        "n_elv":    n_iah_elv,
                        "moy_q1":   moy_q1,
                        "moy_q2":   moy_q2,
                        "delta_q":  delta_q,
                        "spark_dates": [r[0] for r in rows_iah],
                        "spark_vals":  [r[1] for r in rows_iah],
                    }
    except Exception:
        pass

    return result


_MOIS_FR = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]

def _fmt_eu(iso):
    """YYYY-MM-DD → 13 Mar 2026"""
    try:
        y, m, d = iso.split("-")
        mois = _MOIS_FR[int(m) - 1]
        return f"{int(d):02d} {mois} {y}"
    except Exception:
        return iso


def get_trend_thresholds(db_path):
    """Retourne les 4 seuils de tendance configurables (stable = zone entre hausse et baisse)."""
    return {
        "forte_hausse": float(get_setting(db_path, "trend_forte_hausse", "3.0")),
        "hausse":       float(get_setting(db_path, "trend_hausse",       "1.0")),
        "baisse":       float(get_setting(db_path, "trend_baisse",       "-1.0")),
        "forte_baisse": float(get_setting(db_path, "trend_forte_baisse", "-3.0")),
    }


def set_trend_thresholds(db_path, forte_hausse, hausse, baisse, forte_baisse):
    """Enregistre les 4 seuils. Hausse toujours >0, baisse toujours <0."""
    set_setting(db_path, "trend_forte_hausse", str(abs(forte_hausse)),  "Seuil forte hausse mmHg/mois")
    set_setting(db_path, "trend_hausse",       str(abs(hausse)),        "Seuil hausse mmHg/mois")
    set_setting(db_path, "trend_baisse",       str(-abs(baisse)),       "Seuil baisse mmHg/mois")
    set_setting(db_path, "trend_forte_baisse", str(-abs(forte_baisse)), "Seuil forte baisse mmHg/mois")

# ══════════════════════════════════════════════════════════════════════════════
# AUTOMESURES V7.2.4 — Protocoles & Séances
# ══════════════════════════════════════════════════════════════════════════════

import json as _json
from datetime import date as _date, timedelta as _td

# ── Protocoles ────────────────────────────────────────────────────────────────

def am_create_protocole(db_path, label, date_debut, n_jours=3,
                         n_mesures_seance=3, intervalle_minutes=2, moments=None,
                         bras_prioritaire='G', bras_secondaire_actif=False,
                         exclusion_rang1=True, seuil_completude=80,
                         classif_mode='esh', inject_mesures=True):
    """Crée un nouveau protocole. Retourne son id."""
    if moments is None:
        moments = ["MATIN", "SOIR"]
    moments_json = _json.dumps(moments)
    with get_conn(db_path) as conn:
        cur = conn.execute("""
            INSERT INTO am_protocoles
                (label, date_debut, n_jours, n_mesures_seance, intervalle_minutes, moments,
                 exclusion_rang1, seuil_completude, classif_mode, inject_mesures,
                 bras_prioritaire, bras_secondaire_actif)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (label, date_debut, n_jours, n_mesures_seance, intervalle_minutes, moments_json,
              int(exclusion_rang1), seuil_completude,
              classif_mode, int(inject_mesures),
              bras_prioritaire, int(bras_secondaire_actif)))
        pid = cur.lastrowid
    log_historique(db_path, "AUTO_CREATE",
        f"Protocole #{pid} créé : {label}", f"{n_jours}j × {n_mesures_seance} mesures")
    return pid


def am_get_protocole(db_path, protocole_id):
    """Retourne un protocole enrichi (moments parsé, stats complétude)."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM am_protocoles WHERE id=?", (protocole_id,)
        ).fetchone()
    if not row:
        return None
    p = dict(row)
    p['moments'] = _json.loads(p['moments'])
    p.update(_am_completude(db_path, p))
    return p


def am_list_protocoles(db_path):
    """Liste tous les protocoles, du plus récent au plus ancien."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM am_protocoles ORDER BY cree_le DESC"
        ).fetchall()
    result = []
    for row in rows:
        p = dict(row)
        p['moments'] = _json.loads(p['moments'])
        p.update(_am_completude(db_path, p))
        result.append(p)
    return result


def am_get_actif(db_path):
    """Retourne le protocole EN_COURS, ou None."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM am_protocoles WHERE statut='EN_COURS' ORDER BY cree_le DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    p = dict(row)
    p['moments'] = _json.loads(p['moments'])
    p.update(_am_completude(db_path, p))
    return p


def am_clore_protocole(db_path, protocole_id):
    """Clôt un protocole : calcule les moyennes finales, statut → TERMINÉ."""
    moys = _am_calc_moyennes(db_path, protocole_id)
    with get_conn(db_path) as conn:
        # date_fin = date_debut + n_jours - 1 (vraie dernière journée du protocole)
        proto_row = conn.execute(
            "SELECT date_debut, n_jours FROM am_protocoles WHERE id=?", (protocole_id,)
        ).fetchone()
        if proto_row and proto_row['date_debut']:
            from datetime import date as _dt, timedelta as _td
            try:
                date_fin_reelle = (
                    _dt.fromisoformat(proto_row['date_debut']) +
                    _td(days=int(proto_row['n_jours']) - 1)
                ).isoformat()
            except Exception:
                date_fin_reelle = _date.today().isoformat()
        else:
            date_fin_reelle = _date.today().isoformat()

        conn.execute("""
            UPDATE am_protocoles
            SET statut='TERMINE', date_fin=?, moy_sys=?, moy_dia=?, moy_fc=?,
                modifie_le=datetime('now')
            WHERE id=?
        """, (date_fin_reelle,
              moys['moy_sys'], moys['moy_dia'], moys['moy_fc'],
              protocole_id))
    log_historique(db_path, "AUTO_CLOS",
        f"Protocole #{protocole_id} clôturé",
        f"Moy: {moys['moy_sys']}/{moys['moy_dia']} mmHg")
    return moys


def am_archiver_protocole(db_path, protocole_id):
    """Archive un protocole terminé."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE am_protocoles SET statut='ARCHIVE', modifie_le=datetime('now') WHERE id=?",
            (protocole_id,)
        )
    log_historique(db_path, "AUTO_ARCHIVE", f"Protocole #{protocole_id} archivé")


def am_delete_protocole(db_path, protocole_id):
    """Supprime un protocole et toutes ses séances."""
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM am_seances   WHERE protocole_id=?", (protocole_id,))
        conn.execute("DELETE FROM am_protocoles WHERE id=?",           (protocole_id,))
    log_historique(db_path, "AUTO_DELETE", f"Protocole #{protocole_id} supprimé")


# ── Séances ───────────────────────────────────────────────────────────────────

def am_add_seance(db_path, protocole_id, jour, moment, rang,
                   systolic, diastolic, heartrate=None,
                   timestamp=None, mode_saisie='REEL', note='', bras='P'):
    """
    Ajoute ou met à jour une mesure d'une séance.
    exclu_calcul = True si rang == 1 ET exclusion_rang1 activée sur le protocole.
    Recalcule les moyennes du protocole après insertion.
    """
    from datetime import datetime as _dt
    if timestamp is None:
        timestamp = _dt.now().strftime("%Y-%m-%dT%H:%M")

    # Lire le paramètre exclusion_rang1 du protocole
    with get_conn(db_path) as conn:
        proto = conn.execute(
            "SELECT exclusion_rang1 FROM am_protocoles WHERE id=?", (protocole_id,)
        ).fetchone()
    exclu = int(proto['exclusion_rang1']) == 1 and rang == 1 if proto else rang == 1

    with get_conn(db_path) as conn:
        # Vérifier si la contrainte UNIQUE inclut déjà bras (nouvelle base migrée)
        tbl_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='am_seances'"
        ).fetchone()
        has_bras_unique = tbl_sql and 'bras' in (tbl_sql[0] or '').lower() and                           'unique' in (tbl_sql[0] or '').lower()

        existing = conn.execute(
            "SELECT id FROM am_seances WHERE protocole_id=? AND jour=? AND moment=? AND rang=? AND bras=?",
            (protocole_id, jour, moment, rang, bras)
        ).fetchone()

        if existing:
            # Mise à jour simple si la ligne existe déjà
            conn.execute("""
                UPDATE am_seances SET
                    systolic=?, diastolic=?, heartrate=?,
                    timestamp=?, mode_saisie=?, note=?, exclu_calcul=?
                WHERE id=?
            """, (systolic, diastolic, heartrate,
                   timestamp, mode_saisie, note, int(exclu), existing['id']))
        elif not has_bras_unique and bras == 'S':
            # Ancienne contrainte UNIQUE sans bras : le bras S ne peut pas coexister
            # avec le bras P sur la même ligne → on l'insère dans une table tampon
            # en supprimant d'abord l'éventuel conflit sur (proto, jour, moment, rang)
            # Solution : stocker bras S dans un enregistrement séparé en forçant
            # l'unicité via UPDATE si (proto, jour, moment, rang) existe déjà
            existing_any = conn.execute(
                "SELECT id, bras FROM am_seances WHERE protocole_id=? AND jour=? AND moment=? AND rang=?",
                (protocole_id, jour, moment, rang)
            ).fetchone()
            if existing_any:
                # La ligne existe pour bras P → on ne peut pas insérer S avec l'ancienne contrainte
                # On met à jour la colonne bras en S et on sauvegarde (perte du P dans ce cas rare)
                # L'utilisateur doit lancer la migration pour avoir les 2 bras simultanément
                conn.execute("""
                    INSERT OR IGNORE INTO am_seances
                        (protocole_id, jour, moment, rang, systolic, diastolic,
                         heartrate, timestamp, mode_saisie, note, exclu_calcul, bras)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (protocole_id, jour, moment, rang,
                      systolic, diastolic, heartrate,
                      timestamp, mode_saisie, note, int(exclu), bras))
                # Si INSERT OR IGNORE n'a rien fait (contrainte violée), on signale
                # via un flag mais on ne plante pas
            else:
                conn.execute("""
                    INSERT INTO am_seances
                        (protocole_id, jour, moment, rang, systolic, diastolic,
                         heartrate, timestamp, mode_saisie, note, exclu_calcul, bras)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (protocole_id, jour, moment, rang,
                      systolic, diastolic, heartrate,
                      timestamp, mode_saisie, note, int(exclu), bras))
        else:
            conn.execute("""
                INSERT INTO am_seances
                    (protocole_id, jour, moment, rang, systolic, diastolic,
                     heartrate, timestamp, mode_saisie, note, exclu_calcul, bras)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (protocole_id, jour, moment, rang,
                  systolic, diastolic, heartrate,
                  timestamp, mode_saisie, note, int(exclu), bras))

    # Recalculer et sauvegarder les moyennes en temps réel
    moys = _am_calc_moyennes(db_path, protocole_id)
    with get_conn(db_path) as conn:
        conn.execute("""
            UPDATE am_protocoles
            SET moy_sys=?, moy_dia=?, moy_fc=?, moy_sys_s=?, moy_dia_s=?, modifie_le=datetime('now')
            WHERE id=?
        """, (moys['moy_sys'], moys['moy_dia'], moys['moy_fc'],
               moys.get('moy_sys_s'), moys.get('moy_dia_s'), protocole_id))
    return moys


def am_delete_seance(db_path, seance_id):
    """Supprime une mesure individuelle et recalcule les moyennes."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT protocole_id FROM am_seances WHERE id=?", (seance_id,)
        ).fetchone()
        if not row:
            return
        protocole_id = row['protocole_id']
        conn.execute("DELETE FROM am_seances WHERE id=?", (seance_id,))
    moys = _am_calc_moyennes(db_path, protocole_id)
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE am_protocoles SET moy_sys=?, moy_dia=?, moy_fc=? WHERE id=?",
            (moys['moy_sys'], moys['moy_dia'], moys['moy_fc'], protocole_id)
        )


def am_get_seances(db_path, protocole_id):
    """
    Retourne toutes les séances d'un protocole sous forme de dict indexé
    { (jour, moment, rang): seance_dict }
    """
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM am_seances
            WHERE protocole_id=?
            ORDER BY jour, moment, rang
        """, (protocole_id,)).fetchall()
    grid = {}
    for r in rows:
        s = dict(r)
        bras = s.get('bras', 'P')
        grid[(s['jour'], s['moment'], s['rang'], bras)] = s
    return grid


def am_get_grille(db_path, protocole_id):
    """
    Retourne la grille complète pour affichage :
    { jour: { moment: { rang: seance|None, 'moy_seance': float|None } } }
    """
    proto  = am_get_protocole(db_path, protocole_id)
    if not proto:
        return {}
    seances = am_get_seances(db_path, protocole_id)
    bras_sec_actif = bool(proto.get('bras_secondaire_actif', 0))
    grille  = {}
    for jour in range(1, proto['n_jours'] + 1):
        grille[jour] = {}
        for moment in proto['moments']:
            def _build_bras(bras_key):
                rangs = {}
                sys_vals = []; dia_vals = []; fc_vals = []
                for rang in range(1, proto['n_mesures_seance'] + 1):
                    s = seances.get((jour, moment, rang, bras_key))
                    rangs[rang] = s
                    if s and not s['exclu_calcul']:
                        sys_vals.append(s['systolic'])
                        dia_vals.append(s['diastolic'])
                        if s['heartrate']: fc_vals.append(s['heartrate'])
                moy = None
                if sys_vals:
                    moy = {
                        'sys': round(sum(sys_vals)/len(sys_vals), 1),
                        'dia': round(sum(dia_vals)/len(dia_vals), 1),
                        'fc':  round(sum(fc_vals)/len(fc_vals), 1) if fc_vals else None,
                        'n_incluses': len(sys_vals),
                    }
                n_saisies = sum(1 for r in rangs.values() if r is not None)
                return {
                    'rangs':     rangs,
                    'moy_seance': moy,
                    'n_saisies': n_saisies,
                    'complete':  n_saisies >= proto['n_mesures_seance'],
                }
            cell_p = _build_bras('P')
            cell_s = _build_bras('S')  # toujours calculé, la grille affiche si valeurs présentes
            grille[jour][moment] = {**cell_p, 'bras_s': cell_s}
    return grille


# ── Injection dans mesures principales ───────────────────────────────────────

def am_inject_into_mesures(db_path, protocole_id):
    """
    Injecte les mesures incluses (non exclues) d'un protocole terminé
    dans la table mesures principale, avec source='AUTOMESURE'.
    Retourne { added, duplicates }.
    """
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT systolic, diastolic, heartrate, timestamp
            FROM am_seances
            WHERE protocole_id=? AND exclu_calcul=0
            ORDER BY timestamp
        """, (protocole_id,)).fetchall()

    added = dupes = 0
    for r in rows:
        try:
            with get_conn(db_path) as conn:
                conn.execute("""
                    INSERT INTO mesures (timestamp, systolic, diastolic, heartrate, source_pdf)
                    VALUES (?, ?, ?, ?, 'AUTOMESURE')
                """, (r['timestamp'], r['systolic'], r['diastolic'], r['heartrate'] or 0))
            added += 1
        except Exception:
            dupes += 1

    if added:
        with get_conn(db_path) as conn:
            conn.execute(
                "UPDATE am_protocoles SET injecte=1, modifie_le=datetime('now') WHERE id=?",
                (protocole_id,)
            )
        log_historique(db_path, "AUTO_INJECT",
            f"Protocole #{protocole_id} injecté en base",
            f"{added} mesures ajoutées, {dupes} doublons")
    return {'added': added, 'duplicates': dupes}


# ── Helpers internes ──────────────────────────────────────────────────────────

def _am_calc_moyennes(db_path, protocole_id):
    """Calcule les moyennes sur bras prioritaire (P) uniquement.
    Retourne aussi moy_sys_s/moy_dia_s pour le bras secondaire si présent."""
    def _calc(rows):
        if not rows: return None, None, None, 0
        sv = [r['systolic'] for r in rows]
        dv = [r['diastolic'] for r in rows]
        fv = [r['heartrate'] for r in rows if r['heartrate']]
        return (round(sum(sv)/len(sv),1), round(sum(dv)/len(dv),1),
                round(sum(fv)/len(fv),1) if fv else None, len(sv))
    with get_conn(db_path) as conn:
        rows_p = conn.execute(
            "SELECT systolic,diastolic,heartrate FROM am_seances WHERE protocole_id=? AND exclu_calcul=0 AND bras='P'",
            (protocole_id,)).fetchall()
        rows_s = conn.execute(
            "SELECT systolic,diastolic,heartrate FROM am_seances WHERE protocole_id=? AND exclu_calcul=0 AND bras='S'",
            (protocole_id,)).fetchall()
    ms, md, mf, ni = _calc(rows_p)
    ss, sd, _, _   = _calc(rows_s)
    return {
        'moy_sys': ms, 'moy_dia': md, 'moy_fc': mf, 'n_incluses': ni,
        'moy_sys_s': ss, 'moy_dia_s': sd,
    }


def _am_completude(db_path, proto):
    """Calcule le taux de complétude et les séances attendues/complètes."""
    n_jours   = proto['n_jours']
    moments   = proto['moments']
    n_mesures = proto.get('n_mesures_seance', 3)
    pid       = proto['id']

    seances_attendues = n_jours * len(moments)

    with get_conn(db_path) as conn:
        # Séances complètes = (jour, moment) ayant n_mesures rangs saisis
        rows = conn.execute("""
            SELECT jour, moment, COUNT(*) as n
            FROM am_seances
            WHERE protocole_id=? AND bras='P'
            GROUP BY jour, moment
        """, (pid,)).fetchall()

    seances_completes = sum(1 for r in rows if r['n'] >= n_mesures)
    mesures_saisies   = sum(r['n'] for r in rows)
    taux = round(seances_completes / seances_attendues * 100) if seances_attendues else 0

    return {
        'seances_attendues': seances_attendues,
        'seances_completes': seances_completes,
        'mesures_saisies':   mesures_saisies,
        'taux_completude':   taux,
        'rapport_possible':  taux >= proto.get('seuil_completude', 80),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Modules actifs
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MODULES = {
    'tension':      {'actif': 1, 'poids_manuel': 0, 'poids_api': 0},
    'sommeil':      {'actif': 1, 'poids_manuel': 0, 'poids_api': 0},
    'poids':        {'actif': 1, 'poids_manuel': 1, 'poids_api': 1},
    'activites':    {'actif': 1, 'poids_manuel': 0, 'poids_api': 0},
    'correlations': {'actif': 1, 'poids_manuel': 0, 'poids_api': 0},
}

def get_modules(db_path):
    result = {k: dict(v) for k, v in DEFAULT_MODULES.items()}
    try:
        with get_conn(db_path) as conn:
            rows = conn.execute("SELECT module, actif, poids_manuel, poids_api FROM app_modules").fetchall()
            for r in rows:
                if r['module'] in result:
                    result[r['module']]['actif']        = int(r['actif'])
                    result[r['module']]['poids_manuel'] = int(r['poids_manuel'])
                    result[r['module']]['poids_api']    = int(r['poids_api'])
    except Exception:
        pass
    return result

def save_modules(db_path, modules):
    with get_conn(db_path) as conn:
        for module, cfg in modules.items():
            conn.execute("""
                INSERT INTO app_modules (module, actif, poids_manuel, poids_api)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(module) DO UPDATE SET
                    actif        = excluded.actif,
                    poids_manuel = excluded.poids_manuel,
                    poids_api    = excluded.poids_api
            """, (module, int(cfg.get('actif',1)), int(cfg.get('poids_manuel',0)), int(cfg.get('poids_api',0))))
