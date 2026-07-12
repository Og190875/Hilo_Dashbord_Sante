"""
sommeil_db.py — Hilo V8.0.0
Module base de données — Données sommeil (PPC OSCAR + Withings)
"""

import csv
import io
from datetime import datetime
from hilo_db import get_conn

# ── Migration ──────────────────────────────────────────────────────────────────

def migrate_sommeil(conn):
    """Crée les tables sommeil si absentes — idempotent."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sommeil_ppc (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT    NOT NULL UNIQUE,
            duree_min       INTEGER,
            iah             REAL,
            ac              INTEGER,
            ao              INTEGER,
            hypopnees       INTEGER,
            pression_moy    REAL,
            pression_95     REAL,
            limitation_flux REAL,
            source_fichier  TEXT,
            importe_le      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sommeil_withings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT    NOT NULL UNIQUE,
            iah             REAL,
            cree_le         TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    # Table API séparée (nouvelles bases et migrations)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sommeil_withings_api (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT    NOT NULL UNIQUE,
            iah             REAL    NOT NULL,
            breathing       REAL    DEFAULT NULL,
            duree_min       INTEGER DEFAULT NULL,
            startdate_ts    INTEGER DEFAULT NULL,
            importe_le      TEXT    NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()

# ── Import OSCAR CSV ───────────────────────────────────────────────────────────

def _duree_en_minutes(s):
    """Convertit 'HH:MM:SS' en minutes entières."""
    try:
        parts = str(s).strip().split(':')
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        pass
    return None

def _flt(val):
    try:
        v = float(str(val).replace(',', '.').strip())
        return None if v == 0 and str(val).strip() == '' else v
    except Exception:
        return None

def _int(val):
    try:
        return int(float(str(val).replace(',', '.').strip()))
    except Exception:
        return None

def import_oscar_csv(db_path, csv_content, filename=""):
    """
    Importe un CSV OSCAR (encodage ISO-8859-1) dans sommeil_ppc.
    csv_content : bytes ou str
    Retourne dict {ok, inseres, doublons, erreurs, total}
    """
    if isinstance(csv_content, bytes):
        csv_content = csv_content.decode('iso-8859-1')

    reader = csv.DictReader(io.StringIO(csv_content))
    inseres = 0
    doublons = 0
    erreurs = []

    with get_conn(db_path) as conn:
        migrate_sommeil(conn)
        for i, row in enumerate(reader, 1):
            try:
                date = (row.get('Date') or '').strip()
                if not date or len(date) < 10:
                    continue
                date = date[:10]  # YYYY-MM-DD

                duree_min    = _duree_en_minutes(row.get('Temps total', ''))
                iah          = _flt(row.get('IAH', ''))
                ac           = _int(row.get('AC Occurrence', ''))
                ao           = _int(row.get('AO Occurrence', ''))
                hypopnees    = _int(row.get('H Occurrence', ''))
                pression_moy = _flt(row.get('Moyenne Pression', ''))
                pression_95  = _flt(row.get('95% Pression', ''))
                lim_flux     = _flt(row.get('Moyenne Limitation de flux.', ''))

                conn.execute("""
                    INSERT OR IGNORE INTO sommeil_ppc
                        (date, duree_min, iah, ac, ao, hypopnees,
                         pression_moy, pression_95, limitation_flux,
                         source_fichier, importe_le)
                    VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """, (date, duree_min, iah, ac, ao, hypopnees,
                      pression_moy, pression_95, lim_flux, filename))

                changes = conn.execute("SELECT changes()").fetchone()[0]
                if changes > 0:
                    inseres += 1
                else:
                    doublons += 1

            except Exception as e:
                erreurs.append(f"Ligne {i} : {e}")

        conn.commit()

    return {
        'ok': True,
        'inseres': inseres,
        'doublons': doublons,
        'erreurs': erreurs,
        'total': inseres + doublons,
    }

# ── OSCAR détaillé (sessions + events + pressure) ────────────────────────────

def _ensure_oscar_tables(conn):
    """Crée les tables OSCAR avancées si elles n'existent pas."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS oscar_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT    NOT NULL UNIQUE,
            session_id      INTEGER,
            debut_ts        INTEGER,
            fin_ts          INTEGER,
            duree_min       INTEGER,
            n_ca            INTEGER DEFAULT 0,
            n_hypo          INTEGER DEFAULT 0,
            n_obs           INTEGER DEFAULT 0,
            n_total         INTEGER DEFAULT 0,
            iah_calc        REAL,
            pression_moy    REAL,
            pression_p95    REAL,
            pression_min    REAL,
            pression_max    REAL,
            source_fichier  TEXT,
            importe_le      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_oscar_sessions_date
            ON oscar_sessions(date);
        CREATE TABLE IF NOT EXISTS oscar_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            session_id  INTEGER NOT NULL,
            ts          INTEGER NOT NULL,
            heure       TEXT    NOT NULL,
            type_event  TEXT    NOT NULL,
            duree_sec   REAL    DEFAULT NULL,
            importe_le  TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_oscar_events_date
            ON oscar_events(date);
        CREATE TABLE IF NOT EXISTS oscar_pressure (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            session_id  INTEGER NOT NULL,
            ts          INTEGER NOT NULL,
            valeur      REAL    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_oscar_pressure_date
            ON oscar_pressure(date);
        CREATE INDEX IF NOT EXISTS idx_oscar_pressure_session
            ON oscar_pressure(session_id);
    """)
    conn.commit()


def detect_oscar_format(csv_content):
    """Détecte le format du CSV OSCAR depuis les en-têtes.
    Retourne 'resume' ou 'detail' ou None si non reconnu.
    """
    if isinstance(csv_content, bytes):
        for enc in ('utf-8-sig', 'iso-8859-1', 'latin-1', 'cp1252'):
            try:
                first_line = csv_content.split(b'\n')[0].decode(enc).strip()
                break
            except Exception:
                continue
    else:
        first_line = csv_content.split('\n')[0].strip()

    headers = [h.strip().strip('"') for h in first_line.split(',')]

    if 'Date et heure' in headers and 'Session' in headers and 'Évènements' in headers:
        return 'detail'
    if 'Date' in headers and 'IAH' in headers and 'Temps total' in headers:
        return 'resume'
    # Essai avec point-virgule
    headers = [h.strip().strip('"') for h in first_line.split(';')]
    if 'Date' in headers and 'IAH' in headers:
        return 'resume'
    return None


def import_oscar_detail(db_path, csv_content, filename=""):
    """Importe un CSV OSCAR détaillé dans oscar_sessions, oscar_events, oscar_pressure.
    Retourne dict {ok, sessions, apnees, pressions, erreurs}
    """
    import time as _time
    from collections import defaultdict

    if isinstance(csv_content, bytes):
        for enc in ('utf-8-sig', 'iso-8859-1', 'latin-1', 'cp1252'):
            try:
                csv_content = csv_content.decode(enc)
                break
            except Exception:
                continue

    EVENTS_APNEES  = {"ClearAirway", "Hypopnea", "Obstructive", "Apnea"}
    EVENT_PRESSURE = "Pressure"
    BATCH_SIZE     = 5000

    rows_apnees   = []
    rows_pressure = []
    sessions_raw  = defaultdict(lambda: {
        "debut_ts": None, "fin_ts": None,
        "date": None, "pressure": []
    })
    erreurs = []

    reader = csv.DictReader(io.StringIO(csv_content))
    for i, row in enumerate(reader, 1):
        try:
            dt_str  = (row.get('Date et heure') or '').strip()
            sess_id = row.get('Session', '').strip()
            ev_type = (row.get('Évènements') or row.get('Ev\xc3\xa8nements') or '').strip()
            valeur_s= (row.get('Date/Durée') or row.get('Date/Dur\xc3\xa9e') or '').strip()

            if not dt_str or not sess_id: continue
            sess_id = int(sess_id)
            dt = datetime.fromisoformat(dt_str)
            ts = int(dt.timestamp())
            valeur = float(valeur_s) if valeur_s else None

            # Date de nuit
            if dt.hour < 15:
                from datetime import timedelta as _td
                nuit = (dt - _td(days=1)).strftime("%Y-%m-%d")
            else:
                nuit = dt.strftime("%Y-%m-%d")

            # Bornes session
            s = sessions_raw[sess_id]
            if s["debut_ts"] is None or ts < s["debut_ts"]: s["debut_ts"] = ts
            if s["fin_ts"]   is None or ts > s["fin_ts"]:   s["fin_ts"]   = ts
            if s["date"] is None: s["date"] = nuit

            if ev_type in EVENTS_APNEES:
                rows_apnees.append((nuit, sess_id, ts, dt.strftime("%H:%M:%S"), ev_type, valeur))
            elif ev_type == EVENT_PRESSURE and valeur is not None:
                rows_pressure.append((nuit, sess_id, ts, valeur))
                s["pressure"].append(valeur)

        except Exception as e:
            erreurs.append(f"Ligne {i}: {e}")
            continue

    # Calcul stats par session
    apnees_by_date = defaultdict(lambda: {"n_ca":0,"n_hypo":0,"n_obs":0})
    for a in rows_apnees:
        t = a[4]
        if t == "ClearAirway":  apnees_by_date[a[0]]["n_ca"]   += 1
        elif t == "Hypopnea":   apnees_by_date[a[0]]["n_hypo"] += 1
        elif t == "Obstructive":apnees_by_date[a[0]]["n_obs"]  += 1
        elif t == "Apnea":      apnees_by_date[a[0]]["n_ca"]   += 1  # NC = Apnee non classifiee

    def p95(vals):
        if not vals: return None
        return round(sorted(vals)[int(len(vals)*0.95)], 2)

    # Fusionner les sessions de la même date (ex: nuit interrompue = 2 session_id)
    from collections import defaultdict as _dd
    merged = _dd(lambda: {
        "session_id": None, "debut_ts": None, "fin_ts": None,
        "date": None, "pressure": []
    })
    for sess_id, s in sessions_raw.items():
        d = s["date"]
        m = merged[d]
        m["date"] = d
        # Garder le premier session_id rencontré pour la date
        if m["session_id"] is None:
            m["session_id"] = sess_id
        # Étendre les bornes temporelles
        if m["debut_ts"] is None or s["debut_ts"] < m["debut_ts"]:
            m["debut_ts"] = s["debut_ts"]
        if m["fin_ts"] is None or s["fin_ts"] > m["fin_ts"]:
            m["fin_ts"] = s["fin_ts"]
        m["pressure"].extend(s["pressure"])

    sessions_data = []
    for d, m in merged.items():
        dbt  = m["debut_ts"]
        fnt  = m["fin_ts"]
        sess_id = m["session_id"]
        # Durée = somme des durées réelles des sessions (pas juste fin-debut)
        # On calcule la durée totale de toutes les sessions de cette date
        duree_tot = 0
        for sid, s in sessions_raw.items():
            if s["date"] == d and s["debut_ts"] and s["fin_ts"]:
                duree_tot += (s["fin_ts"] - s["debut_ts"]) / 60
        duree = round(duree_tot) if duree_tot > 0 else None
        apn  = apnees_by_date.get(d, {})
        n_ca = apn.get("n_ca",0); n_hypo=apn.get("n_hypo",0); n_obs=apn.get("n_obs",0)
        n_tot= n_ca + n_hypo + n_obs
        iah  = round(n_tot / (duree/60), 2) if duree and duree > 0 else None
        pvals= m["pressure"]
        sessions_data.append((
            d, sess_id, dbt, fnt, duree,
            n_ca, n_hypo, n_obs, n_tot, iah,
            round(sum(pvals)/len(pvals),2) if pvals else None,
            p95(pvals),
            round(min(pvals),1) if pvals else None,
            round(max(pvals),1) if pvals else None,
            filename,
        ))

    with get_conn(db_path) as conn:
        _ensure_oscar_tables(conn)

        # Supprimer données existantes pour les dates concernées
        dates = list(set(s[0] for s in sessions_data))
        for d in dates:
            conn.execute("DELETE FROM oscar_sessions WHERE date=?", (d,))
            conn.execute("DELETE FROM oscar_events   WHERE date=?", (d,))
            conn.execute("DELETE FROM oscar_pressure WHERE date=?", (d,))

        conn.executemany("""
            INSERT OR REPLACE INTO oscar_sessions
                (date,session_id,debut_ts,fin_ts,duree_min,
                 n_ca,n_hypo,n_obs,n_total,iah_calc,
                 pression_moy,pression_p95,pression_min,pression_max,source_fichier)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, sessions_data)

        conn.executemany("""
            INSERT INTO oscar_events (date,session_id,ts,heure,type_event,duree_sec)
            VALUES (?,?,?,?,?,?)
        """, rows_apnees)

        for i in range(0, len(rows_pressure), BATCH_SIZE):
            conn.executemany("""
                INSERT INTO oscar_pressure (date,session_id,ts,valeur)
                VALUES (?,?,?,?)
            """, rows_pressure[i:i+BATCH_SIZE])

        # Sync debut_ts/fin_ts dans sommeil_ppc si colonne existe
        try:
            for s in sessions_data:
                conn.execute("""
                    UPDATE sommeil_ppc SET debut_ts=?, fin_ts=?
                    WHERE date=? AND (debut_ts IS NULL OR debut_ts=0)
                """, (s[2], s[3], s[0]))
        except Exception:
            pass  # colonnes pas encore ajoutées

        conn.commit()

    return {
        'ok':       True,
        'sessions': len(sessions_data),
        'apnees':   len(rows_apnees),
        'pressions':len(rows_pressure),
        'erreurs':  erreurs[:10],
    }


# ── Sync oscar_sessions → sommeil_ppc ───────────────────────────────────────

def sync_oscar_to_ppc(db_path):
    """Synchronise oscar_sessions vers sommeil_ppc (sync complete).
    - MAJ TOUTES les colonnes depuis oscar_sessions (iah, ac, ao, hypopnees,
      pression_moy, pression_95, duree_min, debut_ts, fin_ts)
    - INSERT si la date n'existe pas dans sommeil_ppc
    Retourne {ok, maj, inseres}
    """
    maj     = 0
    inseres = 0

    with get_conn(db_path) as conn:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='oscar_sessions'"
        ).fetchone()
        if not exists:
            return {'ok': False, 'error': 'Table oscar_sessions introuvable'}

        sessions = conn.execute(
            "SELECT date, iah_calc, debut_ts, fin_ts, duree_min, "
            "n_ca, n_hypo, n_obs, pression_moy, pression_p95 "
            "FROM oscar_sessions WHERE iah_calc IS NOT NULL"
        ).fetchall()

        for s in sessions:
            date   = s[0]
            iah    = s[1]
            debut  = s[2]
            fin    = s[3]
            duree  = s[4]
            n_ca   = s[5]
            n_hypo = s[6]
            n_obs  = s[7]
            p_moy  = s[8]
            p_95   = s[9]

            existing = conn.execute(
                "SELECT id FROM sommeil_ppc WHERE date=?", (date,)
            ).fetchone()

            if existing:
                # MAJ complète — oscar_sessions est la source de vérité
                conn.execute("""
                    UPDATE sommeil_ppc SET
                        iah=?, ac=?, ao=?, hypopnees=?,
                        pression_moy=?, pression_95=?,
                        duree_min=?, debut_ts=?, fin_ts=?,
                        source_fichier='oscar_sessions'
                    WHERE date=?
                """, (iah, n_ca, n_obs, n_hypo,
                       p_moy, p_95, duree, debut, fin, date))
                maj += 1
            else:
                conn.execute("""
                    INSERT OR IGNORE INTO sommeil_ppc
                        (date, duree_min, iah, ac, ao, hypopnees,
                         pression_moy, pression_95, debut_ts, fin_ts,
                         source_fichier, importe_le)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """, (date, duree, iah, n_ca, n_obs, n_hypo,
                       p_moy, p_95, debut, fin, 'oscar_sessions'))
                inseres += 1

        conn.commit()

    return {'ok': True, 'maj_iah': maj, 'maj_ts': maj, 'inseres': inseres}


def save_withings(db_path, date, iah, breathing_disturbances=None, duree_min=None):
    """Sauvegarde manuelle d'un IAH Withings dans sommeil_withings (saisies manuelles).
    N'écrase jamais une valeur existante — INSERT OR IGNORE.
    """
    with get_conn(db_path) as conn:
        migrate_sommeil(conn)
        conn.execute("""
            INSERT OR IGNORE INTO sommeil_withings (date, iah)
            VALUES (?, ?)
        """, (date, float(iah)))
        conn.commit()
    return {'ok': True}


def save_withings_api(db_path, date, iah, breathing=None, duree_min=None, startdate_ts=None):
    """Sauvegarde un import API dans sommeil_withings_api (table séparée).
    UPDATE toujours si la date existe déjà.
    """
    with get_conn(db_path) as conn:
        migrate_sommeil(conn)
        conn.execute("""
            INSERT INTO sommeil_withings_api (date, iah, breathing, duree_min, startdate_ts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                iah          = excluded.iah,
                breathing    = excluded.breathing,
                duree_min    = excluded.duree_min,
                startdate_ts = excluded.startdate_ts,
                importe_le   = datetime('now')
        """, (date, float(iah), breathing, duree_min, startdate_ts))
        conn.commit()


def save_withings_batch(db_path, entries):
    """Import batch depuis SleepAnalyser Withings → sommeil_withings_api (table séparée).
    entries = [{'date': 'YYYY-MM-DD', 'iah': float, 'breathing': float|None,
                'duree_min': int|None, 'startdate_ts': int|None}]
    Règles :
      - AHI = 0 ou < 0 ignoré (sieste/artefact/invalide)
      - Plusieurs entrées même date : on garde la plus grande AHI
      - sommeil_withings (saisies manuelles) JAMAIS touchée
    Retourne {'ok': True, 'importe': n, 'mis_a_jour': n, 'ignores': n}
    """
    # Dédoublonner par date : garder la plus grande AHI valide
    par_date = {}
    ignores  = 0
    for e in entries:
        ahi = e.get('iah')
        if ahi is None or ahi <= 0:
            ignores += 1
            continue
        date = e['date']
        if date not in par_date or ahi > par_date[date]['iah']:
            par_date[date] = e

    importe = mis_a_jour = 0
    with get_conn(db_path) as conn:
        migrate_sommeil(conn)
        for date, e in sorted(par_date.items()):
            existing = conn.execute(
                "SELECT id FROM sommeil_withings_api WHERE date = ?", (date,)
            ).fetchone()
            conn.execute("""
                INSERT INTO sommeil_withings_api
                    (date, iah, breathing, duree_min, startdate_ts)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    iah          = excluded.iah,
                    breathing    = excluded.breathing,
                    duree_min    = excluded.duree_min,
                    startdate_ts = excluded.startdate_ts,
                    importe_le   = datetime('now')
            """, (date, float(e['iah']),
                   e.get('breathing'), e.get('duree_min'), e.get('startdate_ts')))
            if existing:
                mis_a_jour += 1
            else:
                importe += 1
        conn.commit()
    return {'ok': True, 'importe': importe, 'mis_a_jour': mis_a_jour, 'ignores': ignores}

def propagate_api_to_withings(db_path):
    """Propage les nouvelles entrées de sommeil_withings_api vers sommeil_withings.
    INSERT OR IGNORE : n'écrase jamais une saisie manuelle existante.
    Retourne {'ok': True, 'ajoutes': n}
    """
    with get_conn(db_path) as conn:
        migrate_sommeil(conn)
        # Insérer uniquement les dates absentes de sommeil_withings
        result = conn.execute("""
            INSERT OR IGNORE INTO sommeil_withings (date, iah, breathing_disturbances, duree_min)
            SELECT a.date, a.iah, a.breathing, a.duree_min
            FROM sommeil_withings_api a
            WHERE NOT EXISTS (
                SELECT 1 FROM sommeil_withings w WHERE w.date = a.date
            )
        """)
        ajoutes = result.rowcount
        conn.commit()
    return {'ok': True, 'ajoutes': ajoutes}


def delete_withings(db_path, entry_id):
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM sommeil_withings WHERE id=?", (entry_id,))
        conn.commit()
    return {'ok': True}

# ── Lecture données ────────────────────────────────────────────────────────────

def get_sommeil_data(db_path, date_start=None, date_end=None):
    """
    Retourne les données sommeil fusionnées PPC + Withings,
    triées par date décroissante, avec tension matin si disponible.
    """
    with get_conn(db_path) as conn:
        migrate_sommeil(conn)

        where = []
        params = []
        if date_start:
            where.append("date >= ?")
            params.append(date_start)
        if date_end:
            where.append("date <= ?")
            params.append(date_end)
        w = ("WHERE " + " AND ".join(where)) if where else ""

        ppc_rows = conn.execute(
            f"SELECT * FROM sommeil_ppc {w} ORDER BY date DESC", params
        ).fetchall()

        with_rows = conn.execute(
            f"SELECT * FROM sommeil_withings {w} ORDER BY date DESC", params
        ).fetchall()

        # Tension du lendemain matin (mesures entre 05:00 et 12:00)
        # On joint par date+1
        tension_map = {}
        rows_t = conn.execute("""
            SELECT date(timestamp) as jour,
                   AVG(systolic)  as sys,
                   AVG(diastolic) as dia,
                   AVG(heartrate) as fc
            FROM mesures
            WHERE strftime('%H', timestamp) BETWEEN '05' AND '12'
            GROUP BY jour
        """).fetchall()
        for r in rows_t:
            tension_map[r['jour']] = {
                'sys': round(r['sys'], 1) if r['sys'] else None,
                'dia': round(r['dia'], 1) if r['dia'] else None,
                'fc':  round(r['fc'],  1) if r['fc']  else None,
            }

    # Indexer Withings par date
    with_map = {r['date']: dict(r) for r in with_rows}

    # Fusionner PPC + Withings + tension
    result = []
    dates_vues = set()

    for r in ppc_rows:
        d = r['date']
        dates_vues.add(d)
        # La tension du matin = lendemain de la nuit
        from datetime import date as dt_date, timedelta
        try:
            lendemain = (datetime.strptime(d, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        except Exception:
            lendemain = None

        entry = dict(r)
        entry['iah_withings']  = with_map.get(d, {}).get('iah')
        entry['withings_id']   = with_map.get(d, {}).get('id')
        entry['duree_w_min']   = with_map.get(d, {}).get('duree_min')
        entry['nuit_courte']   = (with_map.get(d, {}).get('duree_min') or 999) < 300
        entry['tension']      = tension_map.get(lendemain) if lendemain else None
        result.append(entry)

    # Ajouter les dates Withings sans PPC
    for d, w in with_map.items():
        if d in dates_vues:
            continue
        try:
            lendemain = (datetime.strptime(d, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        except Exception:
            lendemain = None
        result.append({
            'date': d,
            'duree_min': None, 'iah': None, 'ac': None, 'ao': None, 'nuit_courte': False,
            'hypopnees': None, 'pression_moy': None, 'pression_95': None,
            'limitation_flux': None, 'source_fichier': None,
            'iah_withings': w.get('iah'),
            'withings_id': w.get('id'),
            'tension': tension_map.get(lendemain) if lendemain else None,
        })

    result.sort(key=lambda x: x['date'], reverse=True)
    return result

def get_sommeil_stats(db_path):
    """Statistiques globales sommeil pour le dashboard."""
    with get_conn(db_path) as conn:
        migrate_sommeil(conn)
        ppc = conn.execute("""
            SELECT COUNT(*) as n, AVG(iah) as iah_moy,
                   MIN(iah) as iah_min, MAX(iah) as iah_max,
                   AVG(pression_moy) as pression_moy,
                   MIN(date) as date_min, MAX(date) as date_max
            FROM sommeil_ppc WHERE iah IS NOT NULL
        """).fetchone()
        withings = conn.execute("""
            SELECT COUNT(*) as n, AVG(iah) as iah_moy,
                   MIN(date) as date_min, MAX(date) as date_max
            FROM sommeil_withings WHERE iah IS NOT NULL
        """).fetchone()

    return {
        'ppc':     dict(ppc)     if ppc     else {},
        'withings': dict(withings) if withings else {},
    }

def get_sommeil_graphique(db_path, mois=6):
    """
    Retourne les données pour le graphique tendance IAH (N derniers mois).
    Chaque point : date, iah_ppc, iah_withings
    """
    with get_conn(db_path) as conn:
        migrate_sommeil(conn)
        ppc = conn.execute("""
            SELECT date, iah FROM sommeil_ppc
            WHERE date >= date('now', ?)
              AND iah IS NOT NULL
            ORDER BY date
        """, (f'-{mois} months',)).fetchall()

        withings = conn.execute("""
            SELECT date, iah FROM sommeil_withings
            WHERE date >= date('now', ?)
              AND iah IS NOT NULL
            ORDER BY date
        """, (f'-{mois} months',)).fetchall()

    ppc_map = {r['date']: r['iah'] for r in ppc}
    with_map = {r['date']: r['iah'] for r in withings}
    all_dates = sorted(set(ppc_map) | set(with_map))

    return [
        {
            'date':         d,
            'iah_ppc':      ppc_map.get(d),
            'iah_withings': with_map.get(d),
        }
        for d in all_dates
    ]

def get_sommeil_stats_detail(db_path):
    """Stats détaillées par année et par mois pour les deux sources."""
    with get_conn(db_path) as conn:
        migrate_sommeil(conn)

        # ── Withings par année ──
        w_annee = conn.execute("""
            SELECT strftime('%Y', date) as periode,
                   COUNT(*) as n,
                   SUM(CASE WHEN iah < 15 THEN 1 ELSE 0 END)              as n0_14,
                   SUM(CASE WHEN iah >= 15 AND iah < 30 THEN 1 ELSE 0 END) as n15_29,
                   SUM(CASE WHEN iah >= 30 THEN 1 ELSE 0 END)              as n30p,
                   ROUND(AVG(iah), 2) as moy
            FROM sommeil_withings WHERE iah IS NOT NULL
            GROUP BY periode ORDER BY periode
        """).fetchall()

        # ── Withings par mois ──
        w_mois = conn.execute("""
            SELECT strftime('%Y-%m', date) as periode,
                   COUNT(*) as n,
                   SUM(CASE WHEN iah < 15 THEN 1 ELSE 0 END)              as n0_14,
                   SUM(CASE WHEN iah >= 15 AND iah < 30 THEN 1 ELSE 0 END) as n15_29,
                   SUM(CASE WHEN iah >= 30 THEN 1 ELSE 0 END)              as n30p,
                   ROUND(AVG(iah), 2) as moy
            FROM sommeil_withings WHERE iah IS NOT NULL
            GROUP BY periode ORDER BY periode
        """).fetchall()

        # ── PPC par année ──
        p_annee = conn.execute("""
            SELECT strftime('%Y', date) as periode,
                   COUNT(*) as n,
                   SUM(CASE WHEN iah < 15 THEN 1 ELSE 0 END)              as n0_14,
                   SUM(CASE WHEN iah >= 15 AND iah < 30 THEN 1 ELSE 0 END) as n15_29,
                   SUM(CASE WHEN iah >= 30 THEN 1 ELSE 0 END)              as n30p,
                   ROUND(AVG(iah), 2)          as moy,
                   ROUND(AVG(pression_moy), 2) as pression_moy
            FROM sommeil_ppc WHERE iah IS NOT NULL
            GROUP BY periode ORDER BY periode
        """).fetchall()

        # ── PPC par mois ──
        p_mois = conn.execute("""
            SELECT strftime('%Y-%m', date) as periode,
                   COUNT(*) as n,
                   SUM(CASE WHEN iah < 15 THEN 1 ELSE 0 END)              as n0_14,
                   SUM(CASE WHEN iah >= 15 AND iah < 30 THEN 1 ELSE 0 END) as n15_29,
                   SUM(CASE WHEN iah >= 30 THEN 1 ELSE 0 END)              as n30p,
                   ROUND(AVG(iah), 2)          as moy,
                   ROUND(AVG(pression_moy), 2) as pression_moy
            FROM sommeil_ppc WHERE iah IS NOT NULL
            GROUP BY periode ORDER BY periode
        """).fetchall()

    def to_list(rows):
        return [dict(r) for r in rows]

    return {
        'w_annee': to_list(w_annee),
        'w_mois':  to_list(w_mois),
        'p_annee': to_list(p_annee),
        'p_mois':  to_list(p_mois),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Import OSCAR V2 (DB directe)
# ─────────────────────────────────────────────────────────────────────────────

def test_oscar_v2_connection(oscar_db_path):
    """Teste la connexion à la DB OSCAR V2. Retourne (ok, message)."""
    try:
        import sqlite3 as _sq
        con = _sq.connect(f"file:{oscar_db_path}?mode=ro", uri=True)
        row = con.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        n   = con.execute("SELECT COUNT(*) FROM daily_summaries").fetchone()[0]
        con.close()
        return True, f"OSCAR V2 connecté — schéma v{row[0]}, {n} nuits disponibles"
    except Exception as e:
        return False, f"Erreur : {e}"


def import_oscar_v2(oscar_db_path, hilo_db_path, profile_id=1):
    """
    Importe toutes les nuits depuis la DB OSCAR V2 vers Hilo.
    Retourne dict {ok, importees, mises_a_jour, erreurs, message}
    """
    import sqlite3 as _sq
    import struct as _struct

    CHANNEL_PRESSURE = 4364
    CHANNEL_CA   = 4097  # ClearAirway
    CHANNEL_OBS  = 4098  # Obstructive
    CHANNEL_HYPO = 4099  # Hypopnea
    CHANNEL_NC   = 4100  # Apnea (Non classée)

    result = {'ok': False, 'importees': 0, 'mises_a_jour': 0, 'erreurs': 0, 'message': ''}

    try:
        ocon = _sq.connect(f"file:{oscar_db_path}?mode=ro", uri=True)
        ocon.row_factory = _sq.Row

        # 1. Lire toutes les nuits depuis daily_summaries
        nuits = ocon.execute("""
            SELECT date, ahi, clear_airway_count, hypopnea_count,
                   obstructive_count, unclassified_count,
                   pressure_avg, pressure_95th, pressure_min, pressure_max,
                   total_hours
            FROM daily_summaries
            WHERE profile_id = ?
            ORDER BY date
        """, (profile_id,)).fetchall()

        # 2. Lire les sessions pour avoir debut_ts / fin_ts par date
        sessions_map = {}
        rows_s = ocon.execute("""
            SELECT date((s.start_time/1000) - 12*3600, 'unixepoch', 'localtime') as nuit,
                   MIN(s.start_time/1000) as debut_ts,
                   MAX(s.end_time/1000)   as fin_ts
            FROM sessions s
            JOIN machines m ON m.id = s.machine_id
            WHERE m.profile_id = ?
            GROUP BY nuit
        """, (profile_id,)).fetchall()
        for r in rows_s:
            sessions_map[r['nuit']] = {'debut_ts': r['debut_ts'], 'fin_ts': r['fin_ts']}

        # 3. Lire les event_lists pour les événements détaillés par session
        events_by_date = {}
        # Lire les événements individuels depuis respiratory_events
        rows_e = ocon.execute("""
            SELECT date((s.start_time/1000) - 12*3600, 'unixepoch', 'localtime') as nuit,
                   s.session_id,
                   re.channel_id,
                   re.start_time/1000 as ts,
                   re.duration        as duree_sec
            FROM respiratory_events re
            JOIN sessions s ON s.id = re.session_id
            JOIN machines m ON m.id = s.machine_id
            WHERE m.profile_id = ?
            AND re.channel_id IN (4097, 4098, 4099, 4100)
            ORDER BY nuit, re.start_time
        """, (profile_id,)).fetchall()

        CH_TO_TYPE = {4097: 'ClearAirway', 4098: 'Obstructive', 4099: 'Hypopnea', 4100: 'Apnea'}
        for r in rows_e:
            d  = r['nuit']
            ch = r['channel_id']
            if d not in events_by_date:
                events_by_date[d] = []
            events_by_date[d].append({
                'session_id': r['session_id'],
                'ts':         r['ts'],
                'heure':      '',
                'type':       CH_TO_TYPE[ch],
                'duree':      r['duree_sec'],
            })

        # 4. Lire les blobs de pression par date
        import zlib as _zlib
        from collections import defaultdict

        def _decode_blob(blob_raw, blob_comp, method):
            """Décode un blob OSCAR (raw ou qCompress).
            - method=0 : données brutes dans data_blob
            - method=1 : qCompress dans data_compressed
            - time_compressed utilise TOUJOURS qCompress (4 bytes header + zlib)
            """
            if method == 0 and blob_raw:
                return bytes(blob_raw)
            if blob_comp:
                data = bytes(blob_comp)
                # time_compressed utilise toujours qCompress quel que soit method
                try:
                    return _zlib.decompress(data[4:])  # strip 4-byte qCompress header
                except _zlib.error:
                    try:
                        return _zlib.decompress(data)  # fallback sans header
                    except _zlib.error:
                        return None
            return None

        pressure_by_date = {}
        rows_p = ocon.execute("""
            SELECT date((s.start_time/1000) - 12*3600, 'unixepoch', 'localtime') as nuit,
                   s.session_id,
                   el.event_type,
                   el.first_time/1000 as t0_sec,
                   el.count,
                   el.rate,
                   el.gain, el.offset,
                   ed.compression_method,
                   ed.data_blob, ed.data_compressed,
                   ed.time_blob, ed.time_compressed
            FROM event_lists el
            JOIN event_data ed ON ed.eventlist_id = el.id
            JOIN sessions s ON s.id = el.session_id
            JOIN machines m ON m.id = s.machine_id
            WHERE m.profile_id = ?
            AND el.channel_id = ?
            ORDER BY nuit, el.first_time
        """, (profile_id, CHANNEL_PRESSURE)).fetchall()

        for r in rows_p:
            d      = r['nuit']
            gain   = r['gain']
            offset = r['offset']
            method = r['compression_method']
            count  = r['count']
            t0_ms  = r['t0_sec'] * 1000  # on repasse en ms pour calculs internes
            ev_type = r['event_type']

            # Décoder le blob de données
            raw_bytes = _decode_blob(r['data_blob'], r['data_compressed'], method)
            if not raw_bytes:
                continue
            n   = len(raw_bytes) // 2
            raw = _struct.unpack(f'<{n}h', raw_bytes)
            values = [round(v * gain + offset, 4) for v in raw]

            # Calculer les timestamps
            if ev_type == 1:
                # EVL_Event (ResMed) : time_blob contient des deltas uint32 en ms
                tb_bytes = _decode_blob(r['time_blob'], r['time_compressed'], method)
                if tb_bytes and len(tb_bytes) >= n * 4:
                    deltas = _struct.unpack(f'<{n}I', tb_bytes[:n*4])
                    ts_list = [int(t0_ms + d_ms) // 1000 for d_ms in deltas]
                else:
                    # Fallback interpolation
                    rate_ms = r['rate'] or 1000
                    ts_list = [int(t0_ms + i * rate_ms) // 1000 for i in range(n)]
            else:
                # EVL_Waveform : espacement uniforme selon rate (ms/sample)
                rate_ms = r['rate'] or 1000
                ts_list = [int(t0_ms + i * rate_ms) // 1000 for i in range(n)]

            # Sous-échantillonnage par minute (moyenne)
            by_min = defaultdict(list)
            for ts_s, val in zip(ts_list, values):
                min_key = ts_s // 60
                by_min[min_key].append(val)

            if d not in pressure_by_date:
                pressure_by_date[d] = []
            # Stocker chaque segment avec son session_id
            pressure_by_date[d].append({
                'session_id': r['session_id'],
                'by_min': dict(by_min),
            })

        ocon.close()

        # 5. Écrire dans Hilo
        with get_conn(hilo_db_path, timeout=60) as hcon:
            # S'assurer que les tables existent
            hcon.execute("""CREATE TABLE IF NOT EXISTS oscar_sessions (
                date TEXT PRIMARY KEY, session_id INTEGER, debut_ts INTEGER, fin_ts INTEGER,
                duree_min INTEGER, iah_calc REAL, n_ca INTEGER, n_hypo INTEGER,
                n_obs INTEGER, n_total INTEGER,
                pression_moy REAL, pression_p95 REAL, pression_min REAL, pression_max REAL,
                source_fichier TEXT, importe_le TEXT DEFAULT (datetime('now')))""")
            hcon.execute("""CREATE TABLE IF NOT EXISTS oscar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, session_id INTEGER, ts INTEGER, heure TEXT,
                type_event TEXT, duree_sec INTEGER)""")
            hcon.execute("""CREATE TABLE IF NOT EXISTS oscar_pressure (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT, session_id INTEGER, ts INTEGER, valeur REAL)""")

            from datetime import datetime as _dt
            now = _dt.now().strftime('%Y-%m-%d %H:%M:%S')

            for nuit in nuits:
                d        = nuit['date']
                sess     = sessions_map.get(d, {})
                debut_ts = sess.get('debut_ts')
                fin_ts   = sess.get('fin_ts')
                duree    = round(nuit['total_hours'] * 60, 1) if nuit['total_hours'] else None
                n_ca     = nuit['clear_airway_count'] or 0
                n_hypo   = nuit['hypopnea_count']     or 0
                n_obs    = nuit['obstructive_count']  or 0
                n_nc     = nuit['unclassified_count'] or 0
                n_total  = n_ca + n_hypo + n_obs + n_nc

                try:
                    # Upsert session
                    existing = hcon.execute("SELECT date FROM oscar_sessions WHERE date=?", (d,)).fetchone()
                    if existing:
                        hcon.execute("""UPDATE oscar_sessions SET
                            debut_ts=?, fin_ts=?, duree_min=?, iah_calc=?,
                            n_ca=?, n_hypo=?, n_obs=?, n_total=?,
                            pression_moy=?, pression_p95=?, pression_min=?, pression_max=?,
                            source_fichier='oscar_v2', importe_le=?
                            WHERE date=?""",
                            (debut_ts, fin_ts, duree, nuit['ahi'],
                             n_ca, n_hypo, n_obs, n_total,
                             nuit['pressure_avg'], nuit['pressure_95th'],
                             nuit['pressure_min'], nuit['pressure_max'],
                             now, d))
                        result['mises_a_jour'] += 1
                    else:
                        hcon.execute("""INSERT INTO oscar_sessions
                            (date, debut_ts, fin_ts, duree_min, iah_calc,
                             n_ca, n_hypo, n_obs, n_total,
                             pression_moy, pression_p95, pression_min, pression_max,
                             source_fichier, importe_le)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'oscar_v2',?)""",
                            (d, debut_ts, fin_ts, duree, nuit['ahi'],
                             n_ca, n_hypo, n_obs, n_total,
                             nuit['pressure_avg'], nuit['pressure_95th'],
                             nuit['pressure_min'], nuit['pressure_max'], now))
                        result['importees'] += 1

                    # Événements — supprimer et réinsérer
                    hcon.execute("DELETE FROM oscar_events WHERE date=?", (d,))
                    evts = events_by_date.get(d, [])
                    for e in evts:
                        hcon.execute("""INSERT INTO oscar_events (date, session_id, ts, heure, type_event, duree_sec)
                            VALUES (?,?,?,?,?,?)""",
                            (d, e['session_id'], e['ts'], e['heure'], e['type'], e['duree']))

                    # Pression — supprimer et réinsérer (multi-sessions)
                    hcon.execute("DELETE FROM oscar_pressure WHERE date=?", (d,))
                    segments = pressure_by_date.get(d, [])
                    for seg in segments:
                        sid = seg['session_id']
                        for mk in sorted(seg['by_min'].keys()):
                            vals = seg['by_min'][mk]
                            ts   = mk * 60
                            valeur = round(sum(vals)/len(vals), 4)
                            hcon.execute("INSERT INTO oscar_pressure (date, session_id, ts, valeur) VALUES (?,?,?,?)",
                                         (d, sid, ts, valeur))

                except Exception as e:
                    result['erreurs'] += 1
                    print(f"Erreur nuit {d}: {e}")

        # Sync vers sommeil_ppc (hors du with pour libérer le verrou d'abord)
        result['ok'] = True
        sync_oscar_to_ppc(hilo_db_path)
        result['message'] = (f"Import OK — {result['importees']} nouvelles nuits, "
                             f"{result['mises_a_jour']} mises à jour, "
                             f"{result['erreurs']} erreurs")
        return result

    except Exception as e:
        result['message'] = f"Erreur globale : {e}"
        return result
