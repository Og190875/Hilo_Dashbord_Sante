"""
app.py — Hilo V8.6.7 — Flask + SQLite
"""

from flask import Flask, request, jsonify, render_template, redirect, url_for, session as flask_session, Response, make_response
from pathlib import Path
import json, os, sys, tempfile

BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import hilo_core
import hilo_db
import hilo_colors
import dashboard_template
import sommeil_db

# ── Format date européen ───────────────────────────────────────────────────────
MOIS_EU = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']

def format_date_eu(ts):
    """Convertit YYYY-MM-DD ou YYYY-MM-DDTHH:MM → 30 Jan 2026 - 09:41"""
    if not ts or ts == '—':
        return '—'
    try:
        from datetime import datetime
        ts = str(ts).strip()
        if 'T' in ts:
            d = datetime.strptime(ts[:16], "%Y-%m-%dT%H:%M")
            return f"{d.day:02d} {MOIS_EU[d.month-1]} {d.year} - {d.hour:02d}:{d.minute:02d}"
        elif len(ts) >= 10:
            d = datetime.strptime(ts[:10], "%Y-%m-%d")
            return f"{d.day:02d} {MOIS_EU[d.month-1]} {d.year}"
        return ts
    except Exception:
        return ts

def enrich_stats(stats):
    """Ajoute les dates formatées EU aux stats."""
    stats['date_min_eu'] = format_date_eu(stats.get('date_min', '—'))
    stats['date_max_eu'] = format_date_eu(stats.get('date_max', '—'))
    return stats

VERSION = os.environ.get("HILO_VERSION", "V8.6.7")

app = Flask(__name__,
            template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))
app.secret_key = "hilo-v71-local"
# ── Config base de données ────────────────────────────────────────────────────
CONFIG_FILE = Path.home() / ".hilo_config.json"

def load_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
    except Exception:
        pass
    return {}

def save_config(data):
    cfg = load_config()
    cfg.update(data)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def get_db_path():
    cfg = load_config()
    return cfg.get("db_path")

# ─────────────────────────────────────────────────────────────────────────────
# API : Suggestions de chemins pour la base
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/suggest-paths")
def api_suggest_paths():
    home = Path.home()
    suggestions = [
        {"label": "Documents/Hilo",  "path": str(home / "Documents" / "Hilo")},
        {"label": "Desktop/Hilo",    "path": str(home / "Desktop"   / "Hilo")},
        {"label": "Documents",       "path": str(home / "Documents")},
    ]
    return jsonify({"ok": True, "suggestions": suggestions})

# ─────────────────────────────────────────────────────────────────────────────
# SETUP — Premier lancement
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    db_path = get_db_path()
    if not db_path or not hilo_db.db_exists(db_path):
        return redirect(url_for("setup"))
    profil  = hilo_db.get_profil(db_path)
    stats   = enrich_stats(hilo_db.get_stats_db(db_path))
    modules = hilo_db.get_modules(db_path)
    return render_template("index.html",
                           profil=profil, stats=stats,
                           db_path=db_path, version=VERSION,
                           modules=modules)


# ─────────────────────────────────────────────────────────
# AIDE
# ─────────────────────────────────────────────────────────
@app.route("/aide")
def aide():
    return render_template("aide.html", version=VERSION)

@app.route("/setup")
def setup():
    return render_template("setup.html", version=VERSION)

@app.route("/api/setup", methods=["POST"])
def api_setup():
    """Crée la base et le profil au premier lancement."""
    data = request.json or {}
    db_folder = data.get("db_folder", "").strip()
    if not db_folder:
        return jsonify({"ok": False, "error": "Dossier non spécifié"}), 400

    db_dir = Path(db_folder)
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(db_dir / "hilo.db")

    try:
        hilo_db.init_db(db_path)
        hilo_db.save_profil(
            db_path,
            nom        = data.get("nom", "").strip(),
            prenom     = data.get("prenom", "").strip(),
            naissance  = data.get("naissance", "").strip(),
            sexe       = data.get("sexe", "M"),
            cible_sys  = int(data.get("cible_sys", 135)),
            cible_dia  = int(data.get("cible_dia", 85)),
            cible_fc   = int(data.get("cible_fc", 60)),
            taille     = float(data["taille"]) if data.get("taille") else None,
            poids      = float(data["poids"])  if data.get("poids")  else None,
        )
        # Modules par défaut : tension uniquement (les autres désactivés)
        hilo_db.save_modules(db_path, {
            'tension':      {'actif': 1, 'poids_manuel': 0, 'poids_api': 0},
            'sommeil':      {'actif': 0, 'poids_manuel': 0, 'poids_api': 0},
            'poids':        {'actif': 0, 'poids_manuel': 0, 'poids_api': 0},
            'activites':    {'actif': 0, 'poids_manuel': 0, 'poids_api': 0},
            'correlations': {'actif': 0, 'poids_manuel': 0, 'poids_api': 0},
        })
        save_config({"db_path": db_path})
        return jsonify({"ok": True, "db_path": db_path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# PAGE D'ACCUEIL — stats 30j, tendance, seuils
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/home-stats")
def api_home_stats():
    """Retourne toutes les stats pour la page d'accueil."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        stats      = hilo_db.get_home_stats(db_path)
        thresholds = hilo_db.get_trend_thresholds(db_path)
        return jsonify({"ok": True, "stats": stats, "thresholds": thresholds,
                        "meteo_velo_sync": _meteo_velo_sync})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/trend-thresholds", methods=["GET"])
def api_get_trend_thresholds():
    """Retourne les seuils de tendance."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    return jsonify({"ok": True, "thresholds": hilo_db.get_trend_thresholds(db_path)})

@app.route("/api/trend-thresholds", methods=["POST"])
def api_save_trend_thresholds():
    """Enregistre les seuils de tendance."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    try:
        hilo_db.set_trend_thresholds(
            db_path,
            forte_hausse = float(d.get("forte_hausse", 3.0)),
            hausse       = float(d.get("hausse",       1.0)),
            baisse       = float(d.get("baisse",      -1.0)),
            forte_baisse = float(d.get("forte_baisse",-3.0)),
        )
        hilo_db.log_historique(db_path, "PARAM", "Seuils tendance mis à jour")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

# ─────────────────────────────────────────────────────────────────────────────
# PROFIL & PARAMÈTRES
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/profil", methods=["GET"])
def api_get_profil():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    profil = hilo_db.get_profil(db_path)
    stats  = hilo_db.get_stats_db(db_path)
    return jsonify({"ok": True, "profil": profil, "stats": stats})

@app.route("/api/profil", methods=["POST"])
def api_save_profil():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    data = request.json or {}
    try:
        def _int(val, default):
            try: return int(val) if str(val).strip() not in ('', 'None', 'null') else default
            except: return default
        def _float(val, default):
            try: return float(val) if str(val).strip() not in ('', 'None', 'null') else default
            except: return default
        def _str(val):
            return (val or '').strip()

        hilo_db.save_profil(
            db_path,
            nom        = _str(data.get("nom")),
            prenom     = _str(data.get("prenom")),
            naissance  = _str(data.get("naissance")),
            sexe       = data.get("sexe", "M") or "M",
            cible_sys  = _int(data.get("cible_sys"), 135),
            cible_dia  = _int(data.get("cible_dia"), 85),
            cible_fc   = _int(data.get("cible_fc"),  60),
            taille     = _int(data.get("taille"),    None),
            poids      = _float(data.get("poids"),   None),
            jour_debut = _int(data.get("jour_debut"), 6),
            jour_fin   = _int(data.get("jour_fin"),  22),
        )
        # Log si cibles modifiées
        if "cible_sys" in data or "cible_dia" in data:
            hilo_db.log_historique(db_path, "PARAM",
                "Paramètres mis à jour",
                f"Cibles: {data.get('cible_sys','?')}/{data.get('cible_dia','?')} mmHg")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/sql", methods=["POST"])
def api_sql_query():
    """Exécute une requête SELECT sur Hilo.db ou Oscar.db."""
    try:
        db_path = get_db_path()
        if not db_path:
            return jsonify({"ok": False, "error": "Base non configurée"}), 400
        data     = request.get_json(force=True)
        query    = (data.get("query") or "").strip()
        use_db   = data.get("db", "hilo")

        # Sécurité : SELECT uniquement
        q_upper = query.upper().lstrip()
        if not q_upper.startswith("SELECT") and not q_upper.startswith("PRAGMA") and not q_upper.startswith("WITH"):
            return jsonify({"ok": False, "error": "Seules les requêtes SELECT / PRAGMA / WITH sont autorisées"}), 400
        forbidden = ["DROP","DELETE","UPDATE","INSERT","ALTER","CREATE","REPLACE","ATTACH","DETACH"]
        for kw in forbidden:
            if kw in q_upper:
                return jsonify({"ok": False, "error": f"Mot-clé interdit : {kw}"}), 400

        # Choisir la DB
        if use_db == "oscar":
            oscar_path = hilo_db.get_setting(db_path, "oscar_db_path", "")
            if not oscar_path:
                return jsonify({"ok": False, "error": "Chemin DB OSCAR non configuré"}), 400
            target_path = oscar_path
        else:
            target_path = db_path

        import sqlite3 as _sq
        con = _sq.connect(f"file:{target_path}?mode=ro", uri=True, timeout=10)
        con.row_factory = _sq.Row
        cur = con.execute(query)
        rows = cur.fetchmany(1000)  # max 1000 lignes
        cols = [d[0] for d in cur.description] if cur.description else []
        con.close()

        return jsonify({
            "ok":   True,
            "cols": cols,
            "rows": [list(r) for r in rows],
            "n":    len(rows),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────────────────────
# MODULES ACTIFS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/modules", methods=["GET"])
def api_get_modules():
    try:
        db_path = get_db_path()
        if not db_path:
            return jsonify({"ok": False, "error": "Base non configurée"}), 400
        modules = hilo_db.get_modules(db_path)
        return jsonify({"ok": True, "modules": modules})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/modules", methods=["POST"])
def api_save_modules():
    try:
        db_path = get_db_path()
        if not db_path:
            return jsonify({"ok": False, "error": "Base non configurée"}), 400
        data = request.get_json(force=True)
        modules = data.get("modules", {})
        if modules.get("poids", {}).get("actif", 1):
            if not modules["poids"].get("poids_manuel", 0) and not modules["poids"].get("poids_api", 0):
                return jsonify({"ok": False, "error": "Poids actif : au moins une source requise"}), 400
        hilo_db.save_modules(db_path, modules)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT PDF
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/upload-pdf", methods=["POST"])
def api_upload_pdf():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400

    files = request.files.getlist("pdfs")
    if not files:
        return jsonify({"ok": False, "error": "Aucun fichier reçu"}), 400

    tmp_dir = Path(tempfile.gettempdir()) / "hilo_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for f in files:
        fname_lower = f.filename.lower()

        # ── CSV OSCAR → détection automatique résumé ou détaillé ──────────
        if fname_lower.endswith('.csv'):
            try:
                content = f.read()
                fmt = sommeil_db.detect_oscar_format(content)
                if fmt == 'detail':
                    res = sommeil_db.import_oscar_detail(db_path, content, f.filename)
                    # Sync automatique oscar_sessions → sommeil_ppc
                    sync = sommeil_db.sync_oscar_to_ppc(db_path)
                    results.append({
                        "file":       f.filename,
                        "ok":         True,
                        "type":       "oscar_detail",
                        "sessions":   res["sessions"],
                        "apnees":     res["apnees"],
                        "pressions":  res["pressions"],
                        "erreurs":    res["erreurs"],
                        "sync_iah":   sync.get('maj_iah', 0),
                        "sync_ins":   sync.get('inseres', 0),
                    })
                elif fmt == 'resume':
                    results.append({"file": f.filename, "ok": False,
                        "error": "CSV résumé non supporté — importez uniquement le CSV détaillé OSCAR"})
                else:
                    results.append({"file": f.filename, "ok": False,
                        "error": "CSV non reconnu — vérifiez les en-têtes (OSCAR résumé ou détaillé attendu)"})
            except Exception as e:
                results.append({"file": f.filename, "ok": False, "error": str(e)})
            continue

        # ── PDF Hilo → import tension ─────────────────────────────────────────
        if not fname_lower.endswith('.pdf'):
            results.append({"file": f.filename, "ok": False, "error": "Format non supporté (PDF ou CSV OSCAR attendu)"})
            continue

        safe_name = Path(f.filename).name  # basename uniquement, ignore les sous-dossiers
        tmp_path = tmp_dir / safe_name
        f.save(str(tmp_path))

        try:
            parsed_rows, _, n_pages = hilo_core.extract_pdf(tmp_path)
            if not parsed_rows:
                results.append({"file": f.filename, "ok": True,
                                "n_pages": n_pages, "n_extraites": 0,
                                "warning": "Aucune mesure trouvée"})
                continue

            df = hilo_core.rows_to_df(parsed_rows)
            inj = hilo_db.inject_mesures(db_path, df, source_pdf=f.filename)

            if inj["error"]:
                results.append({"file": f.filename, "ok": False, "error": inj["error"]})
            else:
                hilo_db.log_import(db_path, f.filename,
                    len(parsed_rows), inj["added"], inj["duplicates"])
                hilo_db.log_historique(db_path, "IMPORT_PDF",
                    f"Import PDF : {Path(f.filename).name}",
                    f"{inj['added']} ajoutées, {inj['duplicates']} doublons")
                results.append({
                    "file":       f.filename,
                    "ok":         True,
                    "n_pages":    n_pages,
                    "n_extraites":len(parsed_rows),
                    "n_ajoutees": inj["added"],
                    "n_doublons": inj["duplicates"],
                    "total_db":   inj["total"],
                })
        except Exception as e:
            results.append({"file": f.filename, "ok": False, "error": str(e)})
        finally:
            try: tmp_path.unlink()
            except: pass

    # Auto-export local + FTP si des mesures ont été ajoutées
    if any(r.get("n_ajoutees", 0) > 0 for r in results):
        _auto_export(db_path)

    return jsonify({"ok": True, "results": results})

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT CSV
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/import-csv", methods=["POST"])
def api_import_csv():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400

    f = request.files.get("csv")
    if not f:
        # Accepte aussi contenu JSON (upload texte depuis setup)
        data = request.json or {}
        content = data.get("content", "")
        if not content:
            return jsonify({"ok": False, "error": "Aucun fichier CSV"}), 400
        tmp_path = Path(tempfile.gettempdir()) / "hilo_import.csv"
        tmp_path.write_text(content, encoding="utf-8")
    else:
        tmp_path = Path(tempfile.gettempdir()) / f.filename
        f.save(str(tmp_path))

    result = hilo_db.import_from_csv(db_path, tmp_path)
    try: tmp_path.unlink()
    except: pass
    if not result["error"]:
        hilo_db.log_historique(db_path, "IMPORT_CSV",
            f"Import CSV",
            f"{result['added']} ajoutées, {result['duplicates']} doublons")
        if result.get("added", 0) > 0:
            _auto_export(db_path)
    return jsonify({"ok": not result["error"], **result})

# ─────────────────────────────────────────────────────────────────────────────
# GESTION BASE
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/db/stats")
def api_db_stats():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    stats   = enrich_stats(hilo_db.get_stats_db(db_path))
    imports = hilo_db.get_imports(db_path, limit=10)
    return jsonify({"ok": True, "stats": stats, "imports": imports,
                    "db_path": db_path})

@app.route("/api/db/export-csv")
def api_export_csv():
    """Exporte toutes les mesures en CSV téléchargeable."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    import io
    mesures = hilo_db.get_mesures(db_path)
    if not mesures:
        return jsonify({"ok": False, "error": "Aucune mesure"}), 400
    import pandas as pd
    df  = pd.DataFrame(mesures)[["timestamp","systolic","diastolic","heartrate"]]
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=hilo_export.csv"}
    )

@app.route("/api/db/reset-mesures", methods=["POST"])
def api_reset_mesures():
    """Supprime toutes les mesures (garde le profil)."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        hilo_db.reset_mesures(db_path)
        hilo_db.log_historique(db_path, "RESET_MESURES", "Mesures vidées")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/db/reset-all", methods=["POST"])
def api_reset_all():
    """Réinitialisation complète — supprime la base et repart au setup."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        hilo_db.reset_all(db_path)
        save_config({"db_path": None})
        return jsonify({"ok": True, "redirect": "/setup"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/db/backup", methods=["POST"])
def api_db_backup():
    """Crée une copie horodatée de la base dans le même dossier."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        dst = hilo_db.backup_db(db_path)
        hilo_db.log_historique(db_path, "BACKUP", f"Sauvegarde créée : {Path(dst).name}")
        return jsonify({"ok": True, "path": dst, "name": Path(dst).name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/db/restore", methods=["POST"])
def api_db_restore():
    """Restaure la base depuis un fichier .db uploadé."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    f = request.files.get("backup")
    if not f:
        return jsonify({"ok": False, "error": "Aucun fichier"}), 400
    tmp_dir  = Path(tempfile.gettempdir()) / "hilo_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / "restore_candidate.db"
    f.save(str(tmp_path))
    try:
        result = hilo_db.restore_db(db_path, str(tmp_path))
        if result.get("ok"):
            hilo_db.log_historique(db_path, "RESTORE", "Base restaurée depuis backup",
                result.get("backup_created",""))
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        try: tmp_path.unlink()
        except: pass

@app.route("/api/db/vacuum", methods=["POST"])
def api_db_vacuum():
    db_path = get_db_path()
    if not db_path: return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        import sqlite3 as _sq3
        conn = _sq3.connect(db_path)
        size_before = conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]
        conn.execute("VACUUM")
        size_after  = conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]
        conn.close()
        saved = round((size_before - size_after) / 1024, 1)
        return jsonify({"ok": True, "note": f"{saved} Ko récupérés" if saved > 0 else "Base déjà optimisée"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/db/integrity")
def api_db_integrity():
    """Lance PRAGMA integrity_check sur la base."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    return jsonify(hilo_db.integrity_check(db_path))

@app.route("/api/historique")
def api_historique():
    """Retourne l'historique unifié : hilo_historique + imports PDF récents."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    limit = int(request.args.get("limit", 50))
    rows  = hilo_db.get_historique(db_path, limit=limit)
    # Enrichir avec date EU
    for r in rows:
        r["date_eu"] = format_date_eu(r["date_op"][:10]) + " " + r["date_op"][11:16] if r.get("date_op") else ""
    return jsonify({"ok": True, "historique": rows})

@app.route("/api/db/open-folder", methods=["POST"])
def api_db_open_folder():
    """Ouvre le dossier de la base dans le Finder/Explorateur."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        import subprocess, sys as _sys
        folder = hilo_db.open_folder(db_path)
        if _sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        elif _sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return jsonify({"ok": True, "path": folder})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────────────────────
# TRAITEMENTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/traitements")
def api_get_traitements():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    return jsonify({"ok": True, "traitements": hilo_db.get_traitements(db_path)})

@app.route("/api/traitements", methods=["POST"])
def api_add_traitement():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    if not d.get("medicament"):
        return jsonify({"ok": False, "error": "Médicament requis"}), 400
    try:
        new_id = hilo_db.add_traitement(
            db_path, d["medicament"], d.get("dosage",""),
            d.get("moments",[]), d.get("date_debut",""),
            d.get("date_fin",""), d.get("note","")
        )
        return jsonify({"ok": True, "id": new_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/traitements/<int:tid>", methods=["PUT"])
def api_update_traitement(tid):
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    if not d.get("medicament"):
        return jsonify({"ok": False, "error": "Médicament requis"}), 400
    try:
        hilo_db.update_traitement(
            db_path, tid, d["medicament"], d.get("dosage",""),
            d.get("moments",[]), d.get("date_debut",""),
            d.get("date_fin",""), d.get("note","")
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/traitements/<int:tid>", methods=["DELETE"])
def api_delete_traitement(tid):
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        hilo_db.delete_traitement(db_path, tid)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/mesures")
def api_get_mesures():
    """Retourne les mesures paginées pour la Zone Expert."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    search   = request.args.get("search", "").strip()
    date_start = request.args.get("date_start", "")
    date_end   = request.args.get("date_end", "")
    result = hilo_db.get_mesures_page(db_path, page, per_page, search,
                                      date_start or None, date_end or None)
    # Enrichir avec dates EU + classification
    profil = hilo_db.get_profil(db_path)
    from hilo_colors import get_classification
    for r in result["rows"]:
        r["ts_eu"] = format_date_eu(r["timestamp"])
        if not r.get("classification"):
            try:
                r["classification"] = get_classification(
                    r["systolic"], r["diastolic"],
                    profil.get("cible_sys", 135), profil.get("cible_dia", 85)
                )["label"]
            except Exception:
                r["classification"] = "—"
    return jsonify({"ok": True, **result})

@app.route("/api/mesures/<int:mesure_id>", methods=["PUT"])
def api_update_mesure(mesure_id):
    """Met à jour sys/dia/fc d'une mesure."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    data = request.json or {}
    try:
        hilo_db.update_mesure(db_path, mesure_id,
                              data["systolic"], data["diastolic"], data["heartrate"],
                              classification=data.get("classification"))
        hilo_db.log_historique(db_path, "EDIT_MESURE",
            f"Mesure #{mesure_id} modifiée",
            f"{data['systolic']}/{data['diastolic']} mmHg — FC {data['heartrate']} bpm")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/mesures/<int:mesure_id>", methods=["DELETE"])
def api_delete_mesure(mesure_id):
    """Supprime une mesure par son id."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        hilo_db.delete_mesure(db_path, mesure_id)
        hilo_db.log_historique(db_path, "DELETE_MESURE",
            f"Mesure #{mesure_id} supprimée")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/extract-pdf-csv", methods=["POST"])
def api_extract_pdf_csv():
    """Extraction brute PDF → texte brut + CSV sans injection en base."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    files = request.files.getlist("pdfs")
    if not files:
        return jsonify({"ok": False, "error": "Aucun fichier"}), 400
    import io
    import pandas as pd
    all_rows  = []
    all_text  = []
    results   = []
    tmp_dir   = Path(tempfile.gettempdir()) / "hilo_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            results.append({"file": f.filename, "ok": False, "error": "Pas un PDF"})
            continue
        safe_name = Path(f.filename).name
        tmp_path  = tmp_dir / safe_name
        f.save(str(tmp_path))
        try:
            parsed_rows, full_text, n_pages = hilo_core.extract_pdf(tmp_path)
            results.append({"file": safe_name, "ok": True,
                            "n_pages": n_pages, "n_extraites": len(parsed_rows)})
            all_rows.extend(parsed_rows)
            all_text.append(f"=== {safe_name} ({n_pages} pages) ===\n\n{full_text}")
        except Exception as e:
            results.append({"file": safe_name, "ok": False, "error": str(e)})
        finally:
            try: tmp_path.unlink()
            except: pass

    raw_text = "\n\n".join(all_text) if all_text else None

    if not all_rows:
        return jsonify({"ok": True, "results": results, "csv": None,
                        "raw_text": raw_text, "message": "Aucune mesure extraite"})
    df  = hilo_core.rows_to_df(all_rows)
    df  = df[["timestamp","systolic","diastolic","heartrate"]].sort_values("timestamp")
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return jsonify({"ok": True, "results": results,
                    "csv": buf.getvalue(), "raw_text": raw_text, "n_total": len(df)})

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    db_path = get_db_path()
    if not db_path or not hilo_db.db_exists(db_path):
        return redirect(url_for("setup"))

    profil  = hilo_db.get_profil(db_path)
    mesures = hilo_db.get_mesures(db_path)

    if not mesures:
        return render_template("index.html", profil=profil,
                               stats=enrich_stats(hilo_db.get_stats_db(db_path)),
                               db_path=db_path, version=VERSION,
                               modules=hilo_db.get_modules(db_path),
                               warning="Aucune mesure dans la base.")

    records = [{
        "ts":  m["timestamp"],
        "sys": m["systolic"],
        "dia": m["diastolic"],
        "fc":  m["heartrate"],
        "h":   int(m["timestamp"][11:13]) if len(m["timestamp"]) > 12 else 0,
    } for m in mesures]

    from datetime import datetime
    today = datetime.now().strftime("%d/%m/%Y %H:%M")

    # En-tête personnalisé
    patient_header = ""
    if profil:
        imc_str = ""
        if profil.get("taille") and profil.get("poids"):
            imc = profil["poids"] / (profil["taille"] / 100) ** 2
            imc_str = f"  ·  IMC {imc:.1f}"
        taille_str = f"  ·  {profil['taille']} cm" if profil.get("taille") else ""
        poids_str  = f"  ·  {profil['poids']} kg"  if profil.get("poids")  else ""
        patient_header = (
            f"{profil['prenom']} {profil['nom']}  ·  "
            f"{profil['sexe_symbol']}  ·  {profil['age']} ans"
            f"{taille_str}{poids_str}{imc_str}  ·  "
            f"Analyse du {today}"
        )

    date_min_iso = mesures[0]["timestamp"][:10]
    date_max_iso = mesures[-1]["timestamp"][:10]

    # Sessions PPC pour filtre Zz
    ppc_sessions_dash = []
    try:
        with hilo_db.get_conn(db_path) as conn:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='oscar_sessions'"
            ).fetchone()
            if exists:
                rows_ppc = conn.execute(
                    "SELECT debut_ts, fin_ts FROM oscar_sessions "
                    "WHERE debut_ts IS NOT NULL AND fin_ts IS NOT NULL"
                ).fetchall()
                ppc_sessions_dash = [{"debut": r[0], "fin": r[1]} for r in rows_ppc]
    except Exception:
        pass

    html = dashboard_template.render_dashboard(
        records_json     = json.dumps(records),
        ppc_sessions     = json.dumps(ppc_sessions_dash),
        date_min         = date_min_iso,
        date_max         = date_max_iso,
        date_min_eu      = format_date_eu(date_min_iso),
        date_max_eu      = format_date_eu(date_max_iso),
        generated        = today,
        n_total          = len(records),
        cible_sys        = profil["cible_sys"]  if profil else 130,
        cible_dia        = profil["cible_dia"]  if profil else 80,
        cible_fc         = profil["cible_fc"]   if profil else 60,
        jour_debut       = profil["jour_debut"] if profil else 6,
        jour_fin         = profil["jour_fin"]   if profil else 22,
        patient_header   = patient_header,
    )
    # En mode iframe (Flask app), masquer header + tabs standalone (déjà affichés par l'app)
    if request.args.get("iframe") == "1":
        html = html.replace(
            '</style>',
            '.dash-header,.tabs-bar{display:none!important}.layout{min-height:100vh}</style>',
            1
        )
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"]        = "no-cache"
    return resp

def _collect_export_data(db_path):
    """Collecte toutes les données nécessaires pour l'export HTML autonome."""
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    data = {}

    # Profil
    try:
        data["profil"] = hilo_db.get_profil(db_path) or {}
    except: data["profil"] = {}

    # Stats
    try:
        data["stats"] = enrich_stats(hilo_db.get_stats_db(db_path))
    except: data["stats"] = {}

    # Trend thresholds
    try:
        ts = hilo_db.get_trend_thresholds(db_path)
        data["trend_thresholds"] = ts if ts else {}
    except: data["trend_thresholds"] = {}

    # Traitements
    try:
        data["traitements"] = hilo_db.get_traitements(db_path)
    except: data["traitements"] = []

    # Mesures tension (champs utiles seulement pour alléger l'export)
    try:
        mesures = hilo_db.get_mesures(db_path)
        KEEP = {'id','timestamp','systolic','diastolic','heartrate','source_pdf','classification'}
        data["mesures"] = [{k:v for k,v in m.items() if k in KEEP}
                           for m in (mesures or [])]
    except: data["mesures"] = []

    # Home stats (même format que /api/home-stats)
    try:
        hs = hilo_db.get_home_stats(db_path)
        data["home_stats"] = hs if hs else {}
    except: data["home_stats"] = {}

    # Poids (tout l'historique)
    try:
        poids = hilo_db.get_poids_historique(db_path)
        data["poids"] = poids if poids else []
    except: data["poids"] = []

    # Sommeil stats + data
    try:
        import sommeil_db as _sl
        sl_raw = _sl.get_sommeil_data(db_path)
        data["sommeil_data"] = sl_raw if sl_raw else []
        # /api/sommeil/stats → {ok, stats: {ppc, withings}}
        sl_stats = _sl.get_sommeil_stats(db_path)
        data["sommeil_stats"] = sl_stats if sl_stats else {}
        # /api/sommeil/stats-detail → {ok, w_annee, w_mois, p_annee, p_mois} (clés à la racine)
        sl_detail = _sl.get_sommeil_stats_detail(db_path)
        data["sommeil_stats_detail"] = sl_detail if sl_detail else {}
    except: data["sommeil_data"] = []; data["sommeil_stats"] = {}; data["sommeil_stats_detail"] = {}

    # Dashboard Tension (HTML complet pour iframe — encodé base64)
    try:
        import base64 as _b64
        dash_html, dash_err = _build_dashboard_html(db_path)
        if dash_html and not dash_err:
            dash_html = dash_html.replace(
                '</style>',
                '.dash-header,.tabs-bar{display:none!important}.layout{min-height:100vh}</style>',
                1
            )
            data["dashboard_b64"] = _b64.b64encode(dash_html.encode('utf-8')).decode('ascii')
        else:
            data["dashboard_b64"] = ""
    except: data["dashboard_b64"] = ""

    # Corrélations — réutiliser la même logique que /api/correlations
    try:
        from datetime import datetime as _dtc, timedelta as _tdc
        import sommeil_db as _sl2
        with hilo_db.get_conn(db_path) as conn:
            poids_rows = conn.execute(
                "SELECT date(mesure_le) AS jour, poids, masse_grasse, masse_musculaire "
                "FROM poids_historique WHERE poids IS NOT NULL ORDER BY jour"
            ).fetchall()
            tension_rows = conn.execute(
                "SELECT date(timestamp) AS jour, "
                "ROUND(AVG(systolic),1) AS sys, ROUND(AVG(diastolic),1) AS dia, "
                "ROUND(AVG(heartrate),1) AS fc "
                "FROM mesures WHERE systolic IS NOT NULL GROUP BY jour ORDER BY jour"
            ).fetchall()
        sl_data2 = _sl2.get_sommeil_data(db_path)
        iah_map = {}
        for s in (sl_data2 or []):
            d = s.get("date")
            if d:
                iah_map[d] = {
                    "iah_ppc":        s.get("iah"),
                    "iah_withings":   s.get("iah_withings"),
                    "duree_ppc":      s.get("duree_min"),
                    "duree_withings": s.get("duree_w_min"),
                }
        poids_map   = {r["jour"]: dict(r) for r in poids_rows}
        tension_map = {r["jour"]: dict(r) for r in tension_rows}
        all_dates   = sorted(set(list(poids_map) + list(tension_map) + list(iah_map)))
        points = []
        for d in all_dates:
            p = poids_map.get(d, {}); t = tension_map.get(d, {}); i = iah_map.get(d, {})
            sys_v = t.get("sys"); dia_v = t.get("dia"); fc_v = t.get("fc")
            if sys_v is None and i.get("iah_ppc") is not None:
                try:
                    lendemain = (_dtc.strptime(d, "%Y-%m-%d") + _tdc(days=1)).strftime("%Y-%m-%d")
                    tl = tension_map.get(lendemain, {})
                    sys_v = tl.get("sys"); dia_v = tl.get("dia"); fc_v = tl.get("fc")
                except Exception: pass
            points.append({"date": d,
                "poids": p.get("poids"), "masse_grasse": p.get("masse_grasse"),
                "masse_musculaire": p.get("masse_musculaire"),
                "sys": sys_v, "dia": dia_v, "fc": fc_v,
                "iah_ppc": i.get("iah_ppc"), "iah_withings": i.get("iah_withings"),
                "duree_ppc": i.get("duree_ppc"), "duree_withings": i.get("duree_withings"),
                "jour_semaine": _dtc.strptime(d, "%Y-%m-%d").weekday() if d else None,
            })
        data["correlations"] = points
    except: data["correlations"] = []

    # Automesures
    try:
        data["am_list"] = hilo_db.am_list_protocoles(db_path)
        actif = hilo_db.am_get_actif(db_path)
        data["am_actif"] = actif if actif else None
    except: data["am_list"] = []; data["am_actif"] = None

    # Corrélations PPC & Tension (pré-calculées pour l'export)
    try:
        from datetime import datetime as _dtppc
        import sqlite3 as _sqppc
        conn_ppc = _sqppc.connect(str(db_path))
        conn_ppc.row_factory = _sqppc.Row
        cur_ppc  = conn_ppc.cursor()

        fenetre_sec = 30 * 60  # 30 min par défaut pour l'export

        cur_ppc.execute("""
            SELECT s.date, s.debut_ts, s.fin_ts, s.iah_calc,
                   s.n_ca, s.n_hypo, s.n_obs, s.n_total
            FROM oscar_sessions s
            WHERE s.debut_ts IS NOT NULL AND s.fin_ts IS NOT NULL
            ORDER BY s.date ASC
        """)
        sessions_ppc = cur_ppc.fetchall()

        nuits_ppc = []
        deltas_ca_ppc = []; deltas_hypo_ppc = []; deltas_obs_ppc = []
        pres_ca_ppc   = []; pres_hypo_ppc   = []; pres_obs_ppc   = []

        for sess in sessions_ppc:
            cur_ppc.execute("""
                SELECT CAST(strftime('%s', timestamp) AS INTEGER) as ts, systolic, diastolic
                FROM mesures WHERE systolic IS NOT NULL
                AND CAST(strftime('%s', timestamp) AS INTEGER) BETWEEN ? AND ?
                ORDER BY timestamp
            """, (sess['debut_ts']-7200, sess['fin_ts']+7200))
            mesures_ppc = list(cur_ppc.fetchall())
            if len(mesures_ppc) < 2: continue

            base_sys = sum(m['systolic'] for m in mesures_ppc) / len(mesures_ppc)
            base_dia = sum(m['diastolic'] for m in mesures_ppc if m['diastolic']) / max(1, len([m for m in mesures_ppc if m['diastolic']]))

            cur_ppc.execute("SELECT ts, type_event FROM oscar_events WHERE date=? ORDER BY ts", (sess['date'],))
            events_ppc = list(cur_ppc.fetchall())
            cur_ppc.execute("SELECT ts, valeur FROM oscar_pressure WHERE date=? ORDER BY ts", (sess['date'],))
            pressions_ppc = list(cur_ppc.fetchall())

            ev_d = {"ClearAirway":[],"Apnea":[],"Hypopnea":[],"Obstructive":[]}
            ev_p = {"ClearAirway":[],"Apnea":[],"Hypopnea":[],"Obstructive":[]}

            for ev in events_ppc:
                t, tp = ev['ts'], ev['type_event']
                avant = [m for m in mesures_ppc if m['ts'] <= t and t-m['ts'] <= fenetre_sec]
                apres = [m for m in mesures_ppc if m['ts'] > t and m['ts']-t <= fenetre_sec]
                if avant and apres and tp in ev_d:
                    ev_d[tp].append(min(apres, key=lambda m:m['ts'])['systolic'] - max(avant, key=lambda m:m['ts'])['systolic'])
                pev = [p['valeur'] for p in pressions_ppc if abs(p['ts']-t) <= 300]
                if pev and tp in ev_p: ev_p[tp].append(sum(pev)/len(pev))

            def _moy(l): return round(sum(l)/len(l),2) if l else None
            vca=ev_d["ClearAirway"]+ev_d["Apnea"]; vh=ev_d["Hypopnea"]; vo=ev_d["Obstructive"]
            pca=ev_p["ClearAirway"]+ev_p["Apnea"]; ph=ev_p["Hypopnea"]; po=ev_p["Obstructive"]
            mca=_moy(vca); mh=_moy(vh); mo=_moy(vo)
            if mca is not None: deltas_ca_ppc.append(mca)
            if mh  is not None: deltas_hypo_ppc.append(mh)
            if mo  is not None: deltas_obs_ppc.append(mo)
            if pca: pres_ca_ppc.extend(pca)
            if ph:  pres_hypo_ppc.extend(ph)
            if po:  pres_obs_ppc.extend(po)
            nuits_ppc.append({"date":sess['date'],"iah":sess['iah_calc'],
                "n_ca":sess['n_ca'] or 0,"n_hypo":sess['n_hypo'] or 0,
                "n_obs":sess['n_obs'] or 0,"n_total":sess['n_total'] or 0,
                "base_sys":round(base_sys,1),"base_dia":round(base_dia,1),
                "delta_ca":mca,"delta_hypo":mh,"delta_obs":mo,
                "pres_ca":_moy(pca),"pres_hypo":_moy(ph),"pres_obs":_moy(po),
                "n_mesures":len(mesures_ppc)})

        def _moy_std(l):
            if not l: return None, None
            m=sum(l)/len(l); return round(m,2), round((sum((x-m)**2 for x in l)/len(l))**.5,2)
        mca2,sca2=_moy_std(deltas_ca_ppc); mh2,sh2=_moy_std(deltas_hypo_ppc); mo2,so2=_moy_std(deltas_obs_ppc)

        data["ppc_tension"] = {
            "fenetre_min": 30, "nuits": nuits_ppc,
            "agregats": {
                "centrale":    {"moy":mca2,"std":sca2,"n":len(deltas_ca_ppc),
                                "pres":round(sum(pres_ca_ppc)/len(pres_ca_ppc),2) if pres_ca_ppc else None},
                "hypopnee":    {"moy":mh2, "std":sh2, "n":len(deltas_hypo_ppc),
                                "pres":round(sum(pres_hypo_ppc)/len(pres_hypo_ppc),2) if pres_hypo_ppc else None},
                "obstructive": {"moy":mo2, "std":so2, "n":len(deltas_obs_ppc),
                                "pres":round(sum(pres_obs_ppc)/len(pres_obs_ppc),2) if pres_obs_ppc else None},
            }
        }
        conn_ppc.close()
    except Exception as _eppc:
        print(f"[Export] PPC-Tension erreur : {_eppc}")
        data["ppc_tension"] = {}

    # Données OSCAR — distribution horaire et sessions nuit
    try:
        import sqlite3 as _sq3, math as _math3
        conn3 = _sq3.connect(str(db_path))
        conn3.row_factory = _sq3.Row
        cur3  = conn3.cursor()
        tables3 = [r[0] for r in cur3.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        # Distribution horaire — toutes périodes
        oscar_horaire = {}
        if "oscar_events" in tables3:
            from datetime import datetime as _dtx, timedelta as _tdx
            for days_k, days_v in [("30","30"),("90","90"),("180","180"),("365","365"),("tout",None)]:
                if days_v:
                    cutoff = (_dtx.now() - _tdx(days=int(days_v))).strftime("%Y-%m-%d")
                    wh, wa = "WHERE date >= ?", [cutoff]
                else:
                    wh, wa = "", []
                rows_h = cur3.execute(
                    "SELECT CASE WHEN heure != '' THEN CAST(substr(heure,1,2) AS INTEGER) "
                    "ELSE CAST(strftime('%H', datetime(ts, 'unixepoch', 'localtime')) AS INTEGER) END as h, "
                    "type_event, COUNT(*) as n "
                    "FROM oscar_events " + wh + " GROUP BY h, type_event ORDER BY h", wa).fetchall()
                n_nuits = cur3.execute("SELECT COUNT(DISTINCT date) FROM oscar_events " + wh, wa).fetchone()[0]
                n_ev    = cur3.execute("SELECT COUNT(*) FROM oscar_events " + wh, wa).fetchone()[0]
                sess_h  = cur3.execute(
                    "SELECT CAST(strftime('%H',datetime(debut_ts,'unixepoch','localtime')) AS INTEGER),"
                    "CAST(strftime('%M',datetime(debut_ts,'unixepoch','localtime')) AS INTEGER),"
                    "CAST(strftime('%H',datetime(fin_ts,'unixepoch','localtime')) AS INTEGER),"
                    "CAST(strftime('%M',datetime(fin_ts,'unixepoch','localtime')) AS INTEGER) "
                    "FROM oscar_sessions WHERE debut_ts IS NOT NULL AND fin_ts IS NOT NULL " +
                    ("AND date >= ?" if wa else ""), wa).fetchall()
                import math as _m3
                def _hc(hh, mm):
                    if not hh: return 23
                    s = sum(_m3.sin(2*_m3.pi*(h+m/60)/24) for h,m in zip(hh,mm))
                    c = sum(_m3.cos(2*_m3.pi*(h+m/60)/24) for h,m in zip(hh,mm))
                    return round((_m3.atan2(s,c)*24/(2*_m3.pi))%24)
                by_h = {}
                for r in rows_h:
                    h,t,n = r[0],r[1],r[2]
                    if h not in by_h: by_h[h]={"h":h,"ca":0,"hypo":0,"obs":0,"total":0}
                    if t=="ClearAirway": by_h[h]["ca"]+=n
                    elif t=="Hypopnea": by_h[h]["hypo"]+=n
                    elif t=="Obstructive": by_h[h]["obs"]+=n
                    elif t=="Apnea": by_h[h]["ca"]+=n
                    by_h[h]["total"]+=n
                data_h=[by_h.get(h,{"h":h,"ca":0,"hypo":0,"obs":0,"total":0}) for h in list(range(15,24))+list(range(0,15))]
                oscar_horaire[days_k]={"data":data_h,"n_nuits":n_nuits,"n_events":n_ev,
                    "h_coucher":_hc([r[0] for r in sess_h],[r[1] for r in sess_h]),
                    "h_reveil": _hc([r[2] for r in sess_h],[r[3] for r in sess_h])}
        data["oscar_horaire"] = oscar_horaire

        # Sessions nuit — fidèle à la route /api/oscar/nuit
        oscar_nuits = {}
        if "oscar_sessions" in tables3:
            from collections import defaultdict as _dfd
            sessions = cur3.execute(
                "SELECT date,session_id,debut_ts,fin_ts,duree_min,iah_calc,n_ca,n_hypo,n_obs,n_total,"
                "pression_moy,pression_p95,pression_min,pression_max FROM oscar_sessions ORDER BY date DESC"
            ).fetchall()
            for sess in sessions:
                d = sess[0]
                session = {
                    "date":sess[0],"session_id":sess[1],"debut_ts":sess[2],"fin_ts":sess[3],
                    "duree_min":sess[4],"iah_calc":sess[5],"n_ca":sess[6],"n_hypo":sess[7],
                    "n_obs":sess[8],"n_total":sess[9],"pression_moy":sess[10],
                    "pression_p95":sess[11],"pression_min":sess[12],"pression_max":sess[13],
                }
                # Événements avec heure et durée
                events = []
                temps_apnee_sec = 0
                if "oscar_events" in tables3:
                    evs = cur3.execute(
                        "SELECT ts,heure,type_event,duree_sec FROM oscar_events WHERE date=? ORDER BY ts",(d,)
                    ).fetchall()
                    for r in evs:
                        dur = r[3]
                        if dur: temps_apnee_sec += dur
                        events.append({"ts":r[0],"heure":r[1],"type":r[2],"duree":dur})
                session["temps_apnee_sec"] = round(temps_apnee_sec)
                # Pression depuis oscar_pressure (sous-échantillonnée par minute)
                pressure = []
                if "oscar_pressure" in tables3 and sess[0]:
                    rows_p = cur3.execute(
                        "SELECT ts,valeur FROM oscar_pressure WHERE date=? ORDER BY ts",(sess[0],)
                    ).fetchall()
                    by_min = _dfd(list)
                    for r in rows_p: by_min[r[0]//60].append(r[1])
                    all_vals = [r[1] for r in rows_p]
                    if all_vals:
                        sv = sorted(all_vals)
                        session["pression_p995"] = round(sv[int(len(sv)*0.995)],2)
                    for mk in sorted(by_min.keys()):
                        vals = by_min[mk]
                        pressure.append({"ts":mk*60,"valeur":round(sum(vals)/len(vals),2)})
                # Tension durant la nuit
                tension_nuit = []
                if sess[2] and sess[3]:
                    rows_t = cur3.execute(
                        "SELECT strftime('%s',timestamp) AS ts_unix, systolic, diastolic, heartrate "
                        "FROM mesures WHERE systolic IS NOT NULL "
                        "AND CAST(strftime('%s',timestamp) AS INTEGER) BETWEEN ? AND ? ORDER BY timestamp",
                        (sess[2]-7200, sess[3]+7200)
                    ).fetchall()
                    tension_nuit = [{"ts":int(r[0]),"sys":r[1],"dia":r[2],"fc":r[3]} for r in rows_t]
                oscar_nuits[d] = {"session":session,"events":events,"pressure":pressure,"tension_nuit":tension_nuit}
        data["oscar_nuits"] = oscar_nuits
        conn3.close()
    except Exception as _eo:
        print(f"[Export] OSCAR erreur : {_eo}")
        data["oscar_horaire"] = {}
        data["oscar_nuits"]   = {}

    # Sorties vélo
    try:
        import sqlite3 as _sq2
        conn2 = _sq2.connect(str(db_path))
        conn2.row_factory = _sq2.Row
        cur2 = conn2.cursor()
        cur2.execute("""
            SELECT id, date, debut_ts, fin_ts, duree_sec, distance_m,
                   hr_moy, elevation_gain,
                   meteo_temp, meteo_ressenti, meteo_vent, meteo_rafales,
                   meteo_pluie, meteo_vent_dir, note, importe_le
            FROM workouts WHERE categorie = 'Vélo'
            ORDER BY date DESC, debut_ts DESC
        """)
        data["workouts_velo"] = [dict(r) for r in cur2.fetchall()]

        # Stats GPS par sortie
        cur2.execute("""
            SELECT workout_id, distance_gps, denivele_gps, vit_moy_gps, n_points
            FROM workouts_gps_stats
        """)
        data["workouts_gps_stats"] = [dict(r) for r in cur2.fetchall()]

        # Corrélations vélo (J, J+1, J+2)
        from datetime import datetime as _dtv, timedelta as _tdv
        cur2.execute("""
            SELECT id, date, duree_sec, distance_m, elevation_gain, hr_moy
            FROM workouts WHERE categorie = 'Vélo' AND date IS NOT NULL
            ORDER BY date ASC
        """)
        sorties_v = cur2.fetchall()
        velo_corr = []
        for sv in sorties_v:
            dt_j1 = (_dtv.strptime(sv['date'], "%Y-%m-%d") + _tdv(days=1)).strftime("%Y-%m-%d")
            dt_j2 = (_dtv.strptime(sv['date'], "%Y-%m-%d") + _tdv(days=2)).strftime("%Y-%m-%d")
            cur2.execute("SELECT AVG(systolic) as sys, AVG(diastolic) as dia FROM mesures WHERE DATE(timestamp)=?", (sv['date'],))
            tj  = cur2.fetchone()
            cur2.execute("SELECT AVG(systolic) as sys FROM mesures WHERE DATE(timestamp)=?", (dt_j1,))
            tj1 = cur2.fetchone()
            cur2.execute("SELECT AVG(systolic) as sys FROM mesures WHERE DATE(timestamp)=?", (dt_j2,))
            tj2 = cur2.fetchone()
            cur2.execute("SELECT iah FROM sommeil_ppc WHERE date=?", (sv['date'],))
            ij  = cur2.fetchone()
            cur2.execute("SELECT iah FROM sommeil_ppc WHERE date=?", (dt_j1,))
            ij1 = cur2.fetchone()
            cur2.execute("SELECT iah FROM sommeil_ppc WHERE date=?", (dt_j2,))
            ij2 = cur2.fetchone()
            cur2.execute("SELECT poids FROM poids_historique WHERE DATE(mesure_le)=? ORDER BY mesure_le DESC LIMIT 1", (dt_j1,))
            pj1 = cur2.fetchone()
            velo_corr.append({
                "date": sv['date'], "duree": sv['duree_sec'], "dist": sv['distance_m'],
                "deniv": sv['elevation_gain'], "fc": sv['hr_moy'],
                "sys":     round(tj['sys'],  1) if tj  and tj['sys']  else None,
                "dia":     round(tj['dia'],  1) if tj  and tj['dia']  else None,
                "sys_j1":  round(tj1['sys'], 1) if tj1 and tj1['sys'] else None,
                "sys_j2":  round(tj2['sys'], 1) if tj2 and tj2['sys'] else None,
                "iah":     round(ij['iah'],  2) if ij  and ij['iah']  else None,
                "iah_j1":  round(ij1['iah'], 2) if ij1 and ij1['iah'] else None,
                "iah_j2":  round(ij2['iah'], 2) if ij2 and ij2['iah'] else None,
                "poids_j1": round(pj1['poids'], 1) if pj1 else None,
            })
        data["velo_correlations"] = velo_corr
        conn2.close()
    except Exception as _ev:
        print(f"[Export] Vélo erreur : {_ev}")
        data["workouts_velo"] = []
        data["workouts_gps_stats"] = []
        data["velo_correlations"] = []

    return data


def _strip_export_html(html, db_path=None):
    """Nettoie le HTML export :
    - Retire Import/Paramètres/Aide nav + panels + JS sync Withings
    - Injecte toutes les données en JSON pour fonctionnement autonome (sans serveur)
    """
    import re, json as _json

    # 1. Boutons nav à retirer
    for tab in ["import", "settings"]:
        html = re.sub(r"<button[^>]*switchTab\('" + tab + r"'[^>]*>.*?</button>",
                      "", html, flags=re.DOTALL)
    html = re.sub(r"<a[^>]*/aide[^>]*>.*?</a>", "", html, flags=re.DOTALL)

    # 2. Panels Import et Paramètres
    html = re.sub(r"<!-- Tab : Import.*?(?=<!-- Tab :)", "", html, flags=re.DOTALL)
    html = re.sub(r"<!-- Tab : Param.*?</div><!-- /tab-settings -->", "", html, flags=re.DOTALL)

    # 3. Bandeau sync Withings
    html = re.sub(r"<!-- Bandeau sync Withings -->.*?<!-- /bandeau -->", "", html, flags=re.DOTALL)

    # 4. Injecter les données JSON si db_path fourni
    if db_path:
        try:
            export_data = _collect_export_data(db_path)
            data_json = _json.dumps(export_data, ensure_ascii=False, default=str)

            # Script qui intercepte tous les fetch /api/ et retourne les données locales
            inject_script = f"""
<script>
// ── Données injectées à l'export ──────────────────────────────────────────
const HILO_EXPORT_DATA = {data_json};
const HILO_IS_EXPORT   = true;

// ── Mode export : iframe dashboard via srcdoc ──────────────────────────────
(function() {{
  const origDesc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'src');
  if (!origDesc) return;
  Object.defineProperty(HTMLIFrameElement.prototype, 'src', {{
    set: function(val) {{
      if (typeof val === 'string' && val.includes('/dashboard')) {{
        try {{
          const b64 = HILO_EXPORT_DATA.dashboard_b64 || '';
          const html = b64 ? decodeURIComponent(escape(atob(b64))) : '<p>Dashboard non disponible</p>';
          this.srcdoc = html;
        }} catch(e) {{ this.srcdoc = '<p>Erreur décodage dashboard</p>'; }}
      }} else {{
        origDesc.set.call(this, val);
      }}
    }},
    get: function() {{ return origDesc.get.call(this); }},
    configurable: true
  }});
}})();

// Désactiver les boutons d'écriture (POST/PUT/DELETE)
document.addEventListener('DOMContentLoaded', () => {{
  // Masquer les boutons d'action non pertinents en lecture seule
  const hideSelectors = [
    '[onclick*="importCSV"]', '[onclick*="importPDF"]',
    '[onclick*="deleteMesure"]', '[onclick*="editMesure"]',
    '[onclick*="dbBackup"]', '[onclick*="dbRestore"]',
    '[onclick*="dbVacuum"]', '[onclick*="dbIntegrity"]',
    '[onclick*="saveProfil"]', '[onclick*="slSaveWithings"]',
    '[onclick*="amCreate"]', '[onclick*="amSaisir"]',
    '[onclick*="amClore"]', '[onclick*="amArchiver"]',
    '[onclick*="exDelete"]', '[onclick*="deletePoids"]',
  ];
  hideSelectors.forEach(sel => {{
    try {{ document.querySelectorAll(sel).forEach(el => el.style.display = 'none'); }} catch(e) {{}}
  }});

  // Masquer l'onglet Saisie dans les Activités
  try {{
    const saisieBtn = document.getElementById('velo-stab-saisie');
    if (saisieBtn) saisieBtn.style.display = 'none';
    const saisiePanel = document.getElementById('velo-panel-saisie');
    if (saisiePanel) saisiePanel.style.display = 'none';
  }} catch(e) {{}}
}});

// Intercepteur fetch : remplace les appels /api/* par des données locales
const _originalFetch = window.fetch;
window.fetch = function(url, opts) {{
  if (typeof url !== "string" || !url.startsWith("/api/")) {{
    return _originalFetch.apply(this, arguments);
  }}
  const base = url.split("?")[0];
  const D = HILO_EXPORT_DATA;

  const resp = (data) => Promise.resolve({{
    ok: true, json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data))
  }});
  const notFound = () => resp({{ ok: false, error: "Export statique" }});

  // Mesures tension
  if (base === "/api/mesures") {{
    const params = new URLSearchParams(url.split("?")[1] || "");
    const page = parseInt(params.get("page") || 1);
    const pp   = parseInt(params.get("per_page") || 50);
    const s    = params.get("date_start") || "";
    const e    = params.get("date_end")   || "";
    let rows   = D.mesures || [];
    if (s) rows = rows.filter(r => r.timestamp >= s);
    if (e) rows = rows.filter(r => r.timestamp <= e + "T23:59:59");
    // Cherche pour chaque mesure un format ts_eu
    rows = rows.map(r => ({{...r,
      ts_eu: r.timestamp ? r.timestamp.slice(8,10)+"/"+r.timestamp.slice(5,7)+"/"+r.timestamp.slice(0,4)+" "+r.timestamp.slice(11,16) : ""
    }}));
    const total = rows.length;
    rows = rows.slice((page-1)*pp, page*pp);
    return resp({{ ok:true, mesures:rows, total, page, per_page:pp }});
  }}
  if (base === "/api/home-stats")      return resp({{ ok:true, stats: D.home_stats, thresholds: D.trend_thresholds }});
  if (base === "/api/profil")          return resp({{ ok:true, profil: D.profil || {{}} }});
  if (base === "/api/traitements")     return resp({{ ok:true, traitements: D.traitements || [] }});
  if (base === "/api/trend-thresholds") return resp({{ ok:true, thresholds: D.trend_thresholds }});
  if (base === "/api/poids")           {{
    const params = new URLSearchParams(url.split("?")[1] || "");
    const ds = params.get("date_start") || "";
    const de = params.get("date_end")   || "";
    let rows = D.poids || [];
    if (ds) rows = rows.filter(r => r.mesure_le >= ds);
    if (de) rows = rows.filter(r => r.mesure_le <= de + "T23:59:59");
    return resp({{ ok:true, historique: rows }});
  }}
  if (base === "/api/sommeil/stats")        return resp({{ ok:true, stats: D.sommeil_stats }});
  if (base === "/api/sommeil/stats-detail") return resp({{ ok:true, ...D.sommeil_stats_detail }});
  if (base === "/api/sommeil/data")  {{
    const params = new URLSearchParams(url.split("?")[1] || "");
    const ds = params.get("date_start") || "";
    const de = params.get("date_end")   || "";
    let rows = D.sommeil_data || [];
    if (ds) rows = rows.filter(r => (r.date||"") >= ds);
    if (de) rows = rows.filter(r => (r.date||"") <= de);
    return resp({{ ok:true, data: rows }});
  }}
  if (base === "/api/am/actif")             return resp({{ ok:true, protocole: D.am_actif || null }});
  if (url.includes("/api/am/") && url.includes("/grille")) return resp({{ ok:true, grille: {{}} }});
  if (url.includes("/api/am/") && url.includes("/saisies")) return resp({{ ok:true, saisies: [] }});
  if (base === "/api/am/list")              return resp({{ ok:true, protocoles: D.am_list || [] }});
  if (base === "/api/db/stats")             return resp({{ ok:true, stats: D.stats }});

  if (base === "/api/correlations")  {{
    const params = new URLSearchParams(url.split("?")[1] || "");
    const ds = params.get("date_start") || "";
    const de = params.get("date_end")   || "";
    let pts = D.correlations || [];
    if (ds) pts = pts.filter(p => p.date >= ds);
    if (de) pts = pts.filter(p => p.date <= de);
    return resp({{ ok:true, points: pts }});
  }}
  // Routes OSCAR
  if (url.includes("/api/oscar/horaire")) {{
    const params = new URLSearchParams(url.split("?")[1] || "");
    const days = params.get("days") || "180";
    const h = (D.oscar_horaire || {{}})[days] || (D.oscar_horaire || {{}})["180"] || {{}};
    return resp({{ ok:true, data: h.data||[], n_nuits: h.n_nuits||0, n_events: h.n_events||0,
                   h_coucher: h.h_coucher||23, h_reveil: h.h_reveil||7 }});
  }}
  if (url.includes("/api/oscar/nuit")) {{
    const params = new URLSearchParams(url.split("?")[1] || "");
    const allDates = Object.keys(D.oscar_nuits||{{}}).sort().reverse();
    const date = params.get("date") || allDates[0] || "";
    const nuit = (D.oscar_nuits||{{}})[date] || {{}};
    const idx  = allDates.indexOf(date);
    const prev = idx < allDates.length - 1 ? allDates[idx+1] : null;
    const next = idx > 0 ? allDates[idx-1] : null;
    return resp({{ ok:true, date: date, prev: prev, next: next,
                   session: nuit.session||null, pressure: nuit.pressure||[],
                   events: nuit.events||[], tension_nuit: nuit.tension_nuit||[] }});
  }}

  // Routes vélo
  if (base === "/api/activites/velo") {{
    return resp({{ ok:true, sorties: D.workouts_velo || [] }});
  }}
  if (url.includes("/api/activites/velo/") && url.includes("/carte")) {{
    const parts = url.split("/");
    const id = parseInt(parts[parts.length - 2]);
    const s = (D.workouts_velo || []).find(r => r.id === id) || {{}};
    const gps = (D.workouts_gps_stats || []).find(r => r.workout_id === id) || {{}};
    return resp({{ ok:true, sortie: {{...s}}, points: [], deniv_gps: gps.denivele_gps || null }});
  }}
  if (url.includes("/api/correlations/ppc-tension")) {{
    const ppcData = D.ppc_tension || {{}};
    return resp({{ ok:true,
      fenetre_min: ppcData.fenetre_min || 30,
      methode: "avant_apres",
      n_nuits: (ppcData.nuits || []).length,
      agregats: ppcData.agregats || {{
        centrale:    {{moy:null,std:null,n:0,pres:null}},
        hypopnee:    {{moy:null,std:null,n:0,pres:null}},
        obstructive: {{moy:null,std:null,n:0,pres:null}}
      }},
      nuits: ppcData.nuits || []
    }});
  }}
  if (base === "/api/correlations/velo") {{
    const rows = D.velo_correlations || [];
    const moy = (key) => {{ const v = rows.filter(r=>r[key]!=null).map(r=>r[key]); return v.length ? parseFloat((v.reduce((a,b)=>a+b,0)/v.length).toFixed(2)) : null; }};
    return resp({{ ok:true, rows,
      moyennes: {{ sys: moy('sys'), dia: moy('dia'), iah: moy('iah'), poids: moy('poids_j1') }},
      globales: {{ sys: null, dia: null, iah: null, poids: null }}
    }});
  }}
  // Toutes les autres routes : retour vide silencieux
  return resp({{ ok: false, error: "Non disponible en export statique" }});
}};
</script>
"""
            # Bandeau lecture seule
            from datetime import datetime as _dt2
            banner = f'''
<div style="background:#1e3a5f;color:#fff;text-align:center;padding:6px 12px;font-size:.78rem;
            position:sticky;top:0;z-index:9999;letter-spacing:.03em">
  📋 Export Hilo {VERSION} — Lecture seule · Généré le {_dt2.now().strftime("%d/%m/%Y %H:%M")}
</div>
'''
            html = html.replace("<body>", "<body>" + banner, 1)
            # Injecter juste avant </head>
            html = html.replace("</head>", inject_script + "</head>", 1)
        except Exception as e:
            print(f"[Export] Avertissement injection données : {{e}}")

    return html


def _build_dashboard_html(db_path):
    """Génère le HTML standalone du dashboard. Retourne (html_str, error)."""
    try:
        profil  = hilo_db.get_profil(db_path)
        mesures = hilo_db.get_mesures(db_path)
        if not mesures:
            return None, "Aucune mesure dans la base"
        records = [{
            "ts":  m["timestamp"], "sys": m["systolic"],
            "dia": m["diastolic"], "fc":  m["heartrate"],
            "h":   int(m["timestamp"][11:13]) if len(m["timestamp"]) > 12 else 0,
        } for m in mesures]
        from datetime import datetime
        today = datetime.now().strftime("%d/%m/%Y %H:%M")
        patient_header = ""
        if profil:
            imc_str = ""
            if profil.get("taille") and profil.get("poids"):
                imc = profil["poids"] / (profil["taille"] / 100) ** 2
                imc_str = f"  ·  IMC {imc:.1f}"
            taille_str = f"  ·  {profil['taille']} cm" if profil.get("taille") else ""
            poids_str  = f"  ·  {profil['poids']} kg"  if profil.get("poids")  else ""
            patient_header = (
                f"{profil['prenom']} {profil['nom']}  ·  "
                f"{profil['sexe_symbol']}  ·  {profil['age']} ans"
                f"{taille_str}{poids_str}{imc_str}  ·  "
                f"Analyse du {today}"
            )
        date_min_iso = mesures[0]["timestamp"][:10]
        date_max_iso = mesures[-1]["timestamp"][:10]
        # Sessions PPC pour filtre Zz
        ppc_sessions = []
        try:
            with hilo_db.get_conn(db_path) as conn:
                exists = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='oscar_sessions'"
                ).fetchone()
                if exists:
                    rows_ppc = conn.execute(
                        "SELECT debut_ts, fin_ts FROM oscar_sessions "
                        "WHERE debut_ts IS NOT NULL AND fin_ts IS NOT NULL"
                    ).fetchall()
                    ppc_sessions = [{"debut": r[0], "fin": r[1]} for r in rows_ppc]
        except Exception:
            pass

        html = dashboard_template.render_dashboard(
            records_json  = json.dumps(records),
            ppc_sessions  = json.dumps(ppc_sessions),
            date_min      = date_min_iso, date_max      = date_max_iso,
            date_min_eu   = format_date_eu(date_min_iso),
            date_max_eu   = format_date_eu(date_max_iso),
            generated     = today,      n_total       = len(records),
            cible_sys     = profil["cible_sys"]  if profil else 130,
            cible_dia     = profil["cible_dia"]  if profil else 80,
            cible_fc      = profil["cible_fc"]   if profil else 60,
            jour_debut    = profil["jour_debut"] if profil else 6,
            jour_fin      = profil["jour_fin"]   if profil else 22,
            patient_header= patient_header,
        )
        return html, None
    except Exception as e:
        return None, str(e)

# ─────────────────────────────────────────────────────────────────────────────
# EXPORT DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/export/full-html", methods=["POST"])
def api_export_full_html():
    """Génère une copie HTML complète de l'app (sans Import/Paramètres/Aide/sync Withings)."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        profil  = hilo_db.get_profil(db_path)
        stats   = enrich_stats(hilo_db.get_stats_db(db_path))
        from flask import render_template as _rt
        modules = hilo_db.get_modules(db_path)
        html = _rt("index.html", profil=profil, stats=stats,
                   db_path=db_path, version=VERSION, warning=None,
                   modules=modules)

        # Supprimer les onglets Import / Parametres / Aide de la nav
        import re
        html = re.sub(r"<button[^>]*switchTab.'import'[^>]*>.*?</button>", '', html, flags=re.DOTALL)
        html = re.sub(r"<button[^>]*switchTab.'settings'[^>]*>.*?</button>", '', html, flags=re.DOTALL)
        html = re.sub(r'<a[^>]*href="/aide"[^>]*>.*?</a>', '', html, flags=re.DOTALL)

        # Retirer les tab-panels Import et Settings
        for panel_id in ['tab-import', 'tab-settings']:
            html = re.sub(
                r'<!-- Tab : ' + panel_id.replace('tab-','').capitalize() + r'.*?(?=<!-- Tab :)',
                '', html, flags=re.DOTALL
            )

        from datetime import datetime as _dt
        ts   = _dt.now().strftime("%Y-%m-%d_%Hh%M")
        dest = Path(db_path).parent / f"hilo_export_{ts}.html"
        dest.write_text(html, encoding="utf-8")
        hilo_db.log_historique(db_path, "EXPORT_HTML", "Export HTML complet", dest.name)
        return jsonify({"ok": True, "name": dest.name, "path": str(dest)})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────


@app.route("/api/ftp/auto-enabled", methods=["POST"])
def api_ftp_auto_enabled():
    """Active/désactive l'auto-export après import."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    hilo_db.set_setting(db_path, "ftp_auto_enabled", d.get("enabled", "0"))
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# AUTOMESURES V7.2.4
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/am/actif")
def api_am_actif():
    """Retourne le protocole EN_COURS avec sa grille, ou null."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    proto = hilo_db.am_get_actif(db_path)
    if not proto:
        return jsonify({"ok": True, "protocole": None})
    grille = hilo_db.am_get_grille(db_path, proto['id'])
    # Sérialiser les clés tuple en string "jour-moment-rang"
    grille_json = {}
    for jour, moments in grille.items():
        grille_json[str(jour)] = {}
        for moment, data in moments.items():
            def _serialize_bras(bras_data):
                if not bras_data:
                    return None
                out = {
                    'n_saisies':  bras_data.get('n_saisies', 0),
                    'complete':   bras_data.get('complete', False),
                    'moy_seance': bras_data.get('moy_seance'),
                    'rangs': {}
                }
                for rang, s in (bras_data.get('rangs') or {}).items():
                    out['rangs'][str(rang)] = dict(s) if s else None
                return out

            cell = _serialize_bras(data)
            # Ajouter bras_s séparément
            cell['bras_s'] = _serialize_bras(data.get('bras_s'))
            grille_json[str(jour)][moment] = cell
    # Convertir les valeurs None/bool/int du proto en types JSON natifs
    proto_clean = {k: (v if not hasattr(v, 'keys') else dict(v)) for k, v in proto.items()}
    return jsonify({"ok": True, "protocole": proto_clean, "grille": grille_json})


@app.route("/api/am/list")
def api_am_list():
    """Liste tous les protocoles."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    protos = hilo_db.am_list_protocoles(db_path)
    # S'assurer que tous les champs sont JSON-sérialisables
    for p in protos:
        for k, v in list(p.items()):
            if v is None or isinstance(v, (int, float, str, bool, list, dict)):
                continue
            p[k] = str(v)
    return jsonify({"ok": True, "protocoles": protos})


@app.route("/api/am/create", methods=["POST"])
def api_am_create():
    """Crée un nouveau protocole. Vérifie qu'aucun n'est EN_COURS."""
    from datetime import date as _today
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    actif = hilo_db.am_get_actif(db_path)
    if actif:
        return jsonify({"ok": False,
                        "error": f"Un protocole est déjà en cours (#{actif['id']} — {actif['label']}). Clôturez-le d'abord."}), 409
    d = request.json or {}
    try:
        pid = hilo_db.am_create_protocole(
            db_path,
            label            = d.get("label", "Protocole automesures"),
            date_debut       = d.get("date_debut", str(_today.today())),
            n_jours          = int(d.get("n_jours", 3)),
            n_mesures_seance      = int(d.get("n_mesures_seance", 3)),
            intervalle_minutes    = int(d.get("intervalle_minutes", 2)),
            bras_prioritaire      = d.get("bras_prioritaire", "G"),
            bras_secondaire_actif = bool(d.get("bras_secondaire_actif", False)),
            moments               = d.get("moments", ["MATIN", "SOIR"]),
            exclusion_rang1  = bool(d.get("exclusion_rang1", True)),
            seuil_completude = int(d.get("seuil_completude", 80)),
            classif_mode     = d.get("classif_mode", "esh"),
            inject_mesures   = bool(d.get("inject_mesures", True)),
        )
        return jsonify({"ok": True, "id": pid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/am/<int:pid>/seance", methods=["POST"])
def api_am_add_seance(pid):
    """Ajoute ou met à jour une mesure dans une séance."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    try:
        # Validation minimale
        sys_v = int(d["systolic"])
        dia_v = int(d["diastolic"])
        if not (50 <= sys_v <= 300) or not (30 <= dia_v <= 200):
            return jsonify({"ok": False, "error": "Valeurs tensionnelles hors plage"}), 400
        moys = hilo_db.am_add_seance(
            db_path,
            protocole_id = pid,
            jour         = int(d["jour"]),
            moment       = d["moment"].upper(),
            rang         = int(d["rang"]),
            systolic     = sys_v,
            diastolic    = dia_v,
            heartrate    = int(d["heartrate"]) if d.get("heartrate") else None,
            timestamp    = d.get("timestamp"),
            mode_saisie  = d.get("mode_saisie", "REEL").upper(),
            note         = d.get("note", ""),
            bras         = d.get("bras", "P"),
        )
        return jsonify({"ok": True, "moyennes": moys})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": f"Données invalides : {e}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/am/<int:pid>/seance/<int:sid>", methods=["DELETE"])
def api_am_delete_seance(pid, sid):
    """Supprime une mesure."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    hilo_db.am_delete_seance(db_path, sid)
    return jsonify({"ok": True})



@app.route("/api/am/<int:pid>/settings", methods=["PATCH"])
def api_am_patch_settings(pid):
    """Modifie les réglages d'un protocole (classif_mode, exclusion_rang1, seuil_completude, inject_mesures, label)."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    allowed = {'classif_mode', 'exclusion_rang1', 'seuil_completude', 'inject_mesures', 'label', 'intervalle_minutes', 'n_jours'}
    updates = {k: v for k, v in d.items() if k in allowed}
    if not updates:
        return jsonify({"ok": False, "error": "Aucun champ valide"}), 400
    try:
        sets   = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [pid]
        import sqlite3 as _sq
        with hilo_db.get_conn(db_path) as conn:
            conn.execute(f"UPDATE am_protocoles SET {sets}, modifie_le=datetime('now') WHERE id=?", values)
        hilo_db.log_historique(db_path, "AUTO_SETTINGS", f"Protocole #{pid} réglages modifiés", str(updates))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/am/<int:pid>/clore", methods=["POST"])
def api_am_clore(pid):
    """Clôt un protocole et calcule les moyennes finales."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        moys  = hilo_db.am_clore_protocole(db_path, pid)
        proto = hilo_db.am_get_protocole(db_path, pid)
        # Injection automatique si demandée
        inject_result = None
        if proto and proto.get("inject_mesures"):
            inject_result = hilo_db.am_inject_into_mesures(db_path, pid)
            _auto_export(db_path)
        return jsonify({"ok": True, "moyennes": moys, "injection": inject_result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/am/<int:pid>/archiver", methods=["POST"])
def api_am_archiver(pid):
    """Archive un protocole terminé."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    hilo_db.am_archiver_protocole(db_path, pid)
    return jsonify({"ok": True})


@app.route("/api/am/<int:pid>", methods=["DELETE"])
def api_am_delete(pid):
    """Supprime un protocole et toutes ses séances."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    hilo_db.am_delete_protocole(db_path, pid)
    return jsonify({"ok": True})


@app.route("/api/am/<int:pid>/rapport")
def api_am_rapport(pid):
    """Génère le HTML du rapport imprimable."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        proto   = hilo_db.am_get_protocole(db_path, pid)
        if not proto:
            return jsonify({"ok": False, "error": "Protocole introuvable"}), 404
        grille  = hilo_db.am_get_grille(db_path, pid)
        profil  = hilo_db.get_profil(db_path)
        from am_rapport import render_rapport
        traitements = hilo_db.get_traitements(db_path)
        # Construire mesures_base : moyenne par jour sur la période du protocole
        mesures_base = {}
        if proto.get('date_debut'):
            import sqlite3 as _sq3
            try:
                with hilo_db.get_conn(db_path) as conn:
                    rows_b = conn.execute("""
                        SELECT DATE(timestamp) as jour,
                               ROUND(AVG(systolic),1)  as sys,
                               ROUND(AVG(diastolic),1) as dia,
                               COUNT(*) as n
                        FROM mesures
                        WHERE DATE(timestamp) BETWEEN ? AND ?
                        GROUP BY DATE(timestamp)
                    """, (proto['date_debut'], proto.get('date_fin') or proto['date_debut'])).fetchall()
                for r in rows_b:
                    mesures_base[r['jour']] = {'sys': r['sys'], 'dia': r['dia'], 'n': r['n']}
            except Exception:
                pass
        # Protocole précédent (N-1) pour comparatif
        proto_prec  = None
        grille_prec = None
        try:
            all_protos = hilo_db.am_list_protocoles(db_path)
            # Trier par date création croissante, trouver celui juste avant pid
            all_protos_asc = sorted(all_protos, key=lambda p: p.get('date_debut',''))
            ids = [p['id'] for p in all_protos_asc]
            if pid in ids:
                idx_cur = ids.index(pid)
                if idx_cur > 0:
                    pid_prec = ids[idx_cur - 1]
                    proto_prec  = hilo_db.am_get_protocole(db_path, pid_prec)
                    grille_prec = hilo_db.am_get_grille(db_path, pid_prec)
        except Exception:
            pass
        html = render_rapport(proto, grille, profil, traitements, mesures_base,
                              proto_prec=proto_prec, grille_prec=grille_prec)
        return Response(html, mimetype="text/html")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────────────────────────────────────────────────────
# AUTO-EXPORT (après import)
# ─────────────────────────────────────────────────────────────────────────────

def _auto_export(db_path):
    """Export local + FTP automatique après mise à jour des données.
    FTP uniquement si ftp_auto_enabled == '1' et config complète."""
    import threading
    def _run():
        try:
            from flask import render_template as _rt
            profil = hilo_db.get_profil(db_path)
            stats  = enrich_stats(hilo_db.get_stats_db(db_path))
            with app.app_context():
                html = _rt("index.html", profil=profil, stats=stats,
                           db_path=db_path, version=VERSION, warning=None,
                           modules=hilo_db.get_modules(db_path))
            html = _strip_export_html(html, db_path=db_path)
            if not html:
                return
            # Export local (toujours)
            from datetime import datetime as _dt
            ts   = _dt.now().strftime("%Y-%m-%d")
            dest = Path(db_path).parent / f"hilo_export_{ts}.html"
            dest.write_text(html, encoding="utf-8")
            hilo_db.log_historique(db_path, "EXPORT_AUTO",
                "Auto-export local", dest.name)
            # Export FTP si activé
            auto = hilo_db.get_setting(db_path, "ftp_auto_enabled", "0")
            if auto != "1":
                return
            host   = hilo_db.get_setting(db_path, "ftp_host",   "")
            login  = hilo_db.get_setting(db_path, "ftp_login",  "")
            pwd    = hilo_db.get_setting(db_path, "ftp_pass",   "")
            chemin = hilo_db.get_setting(db_path, "ftp_chemin", "/")
            if not host:
                return
            import ftplib, io as _io
            ftp = ftplib.FTP()
            ftp.connect(host, 21, timeout=15)
            ftp.login(login, pwd)
            ftp.set_pasv(True)
            ftp.cwd(chemin)
            ftp.storbinary("STOR index.html", _io.BytesIO(html.encode("utf-8")))
            ftp.quit()
            hilo_db.log_historique(db_path, "EXPORT_AUTO",
                f"Auto-export FTP OK → {host}", f"{chemin}/index.html")
        except Exception as e:
            try:
                hilo_db.log_historique(db_path, "EXPORT_AUTO_ERR",
                    "Erreur auto-export", str(e))
            except:
                pass
    threading.Thread(target=_run, daemon=True).start()

@app.route("/api/ftp/config", methods=["GET"])
def api_ftp_config_get():
    """Retourne la config FTP stockée."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    return jsonify({"ok": True, "config": {
        "host":         hilo_db.get_setting(db_path, "ftp_host",         ""),
        "login":        hilo_db.get_setting(db_path, "ftp_login",        ""),
        "pass":         hilo_db.get_setting(db_path, "ftp_pass",         ""),
        "chemin":       hilo_db.get_setting(db_path, "ftp_chemin",       "/"),
        "auto_enabled": hilo_db.get_setting(db_path, "ftp_auto_enabled", "0"),
    }})

@app.route("/api/ftp/config", methods=["POST"])
def api_ftp_config_save():
    """Enregistre la config FTP."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    hilo_db.set_setting(db_path, "ftp_host",   d.get("host",   ""))
    hilo_db.set_setting(db_path, "ftp_login",  d.get("login",  ""))
    hilo_db.set_setting(db_path, "ftp_pass",   d.get("pass",   ""))
    hilo_db.set_setting(db_path, "ftp_chemin", d.get("chemin", "/"))
    hilo_db.log_historique(db_path, "PARAM", "Config FTP mise à jour")
    return jsonify({"ok": True})

@app.route("/api/ftp/test", methods=["POST"])
def api_ftp_test():
    """Test de connexion FTP — reprend test_ftp.py."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    import ftplib, io as _io
    d = request.json or {}
    host   = d.get("host",   hilo_db.get_setting(db_path, "ftp_host",   ""))
    login  = d.get("login",  hilo_db.get_setting(db_path, "ftp_login",  ""))
    pwd    = d.get("pass",   hilo_db.get_setting(db_path, "ftp_pass",   ""))
    chemin = d.get("chemin", hilo_db.get_setting(db_path, "ftp_chemin", "/"))
    steps  = []
    try:
        ftp = ftplib.FTP()
        ftp.connect(host, 21, timeout=10)
        steps.append("✅ Serveur contacté")
        ftp.login(login, pwd)
        steps.append(f"✅ Login OK ({login})")
        ftp.set_pasv(True)
        welcome = ftp.getwelcome()[:60]
        steps.append(f"ℹ️ Serveur : {welcome}")
        try:
            ftp.cwd(chemin)
            steps.append(f"✅ Dossier accessible : {chemin}")
        except ftplib.error_perm:
            steps.append(f"❌ Dossier inaccessible : {chemin}")
            ftp.quit()
            return jsonify({"ok": False, "steps": steps, "error": "Dossier inaccessible"})
        fichiers = ftp.nlst()
        steps.append(f"ℹ️ {len(fichiers)} fichier(s) dans le dossier")
        # Test écriture
        ftp.storbinary("STOR hilo_test.txt", _io.BytesIO(b"Hilo FTP test OK"))
        steps.append("✅ Écriture OK")
        # Test lecture
        if "hilo_test.txt" in ftp.nlst():
            steps.append("✅ Lecture OK")
        # Nettoyage
        ftp.delete("hilo_test.txt")
        steps.append("✅ Suppression OK — connexion 100% opérationnelle")
        ftp.quit()
        hilo_db.log_historique(db_path, "PARAM", f"Test FTP OK — {host}")
        return jsonify({"ok": True, "steps": steps})
    except ftplib.error_perm as e:
        steps.append(f"❌ Erreur permissions : {e}")
        return jsonify({"ok": False, "steps": steps, "error": str(e)})
    except (ConnectionRefusedError, OSError) as e:
        steps.append(f"❌ Connexion refusée — vérifier le nom d'hôte")
        return jsonify({"ok": False, "steps": steps, "error": str(e)})
    except TimeoutError:
        steps.append("❌ Timeout — serveur inaccessible")
        return jsonify({"ok": False, "steps": steps, "error": "Timeout"})
    except Exception as e:
        steps.append(f"❌ Erreur : {type(e).__name__} — {e}")
        return jsonify({"ok": False, "steps": steps, "error": str(e)})

@app.route("/api/export/local", methods=["POST"])
def api_export_local():
    """Exporte une copie complète de l'app (sans Import/Paramètres/Aide/sync Withings)."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        from flask import render_template as _rt
        profil = hilo_db.get_profil(db_path)
        stats  = enrich_stats(hilo_db.get_stats_db(db_path))
        modules = hilo_db.get_modules(db_path)
        html   = _rt("index.html", profil=profil, stats=stats,
                     db_path=db_path, version=VERSION, warning=None,
                     modules=modules)
        html   = _strip_export_html(html, db_path=db_path)
        from datetime import datetime as _dt
        ts   = _dt.now().strftime("%Y-%m-%d_%Hh%M")
        dest = Path(db_path).parent / f"hilo_export_{ts}.html"
        dest.write_text(html, encoding="utf-8")
        hilo_db.log_historique(db_path, "EXPORT_LOCAL",
            "Export HTML complet", str(dest.name))
        hilo_db.set_setting(db_path, "withings_last_backup_export", _dt.now().strftime("%Y-%m-%d %H:%M"))
        return jsonify({"ok": True, "path": str(dest), "name": dest.name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/export/ftp", methods=["POST"])
def api_export_ftp():
    """Génère une copie complète et l'uploade en FTP (sans Import/Paramètres/Aide/sync Withings)."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        from flask import render_template as _rt
        profil = hilo_db.get_profil(db_path)
        stats  = enrich_stats(hilo_db.get_stats_db(db_path))
        modules = hilo_db.get_modules(db_path)
        html   = _rt("index.html", profil=profil, stats=stats,
                     db_path=db_path, version=VERSION, warning=None,
                     modules=modules)
        html   = _strip_export_html(html, db_path=db_path)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Génération HTML : {e}"}), 500
    import ftplib, io as _io
    host   = hilo_db.get_setting(db_path, "ftp_host",   "")
    login  = hilo_db.get_setting(db_path, "ftp_login",  "")
    pwd    = hilo_db.get_setting(db_path, "ftp_pass",   "")
    chemin = hilo_db.get_setting(db_path, "ftp_chemin", "/")
    if not host:
        return jsonify({"ok": False, "error": "Config FTP non renseignée"}), 400
    try:
        ftp = ftplib.FTP()
        ftp.connect(host, 21, timeout=15)
        ftp.login(login, pwd)
        ftp.set_pasv(True)
        ftp.cwd(chemin)
        ftp.storbinary("STOR index.html", _io.BytesIO(html.encode("utf-8")))
        ftp.quit()
        hilo_db.log_historique(db_path, "EXPORT_FTP",
            f"Export complet uploadé sur {host}", f"{chemin}/index.html")
        return jsonify({"ok": True, "url": f"http://{host}{chemin}/index.html"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__} : {e}"}), 500

# ─────────────────────────────────────────────────────────────────────────────
# Poids
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/poids", methods=["GET"])
def api_poids_get():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    date_start = request.args.get("date_start", "")
    date_end   = request.args.get("date_end",   "")
    rows = hilo_db.get_poids_historique(db_path)
    # Filtrer selon la plage demandée (si aucune → tout retourner)
    if date_start:
        rows = [r for r in rows if r.get("mesure_le", "") >= date_start]
    if date_end:
        rows = [r for r in rows if r.get("mesure_le", "") <= date_end + "T23:59:59"]
    return jsonify({"ok": True, "historique": rows})


@app.route("/api/poids", methods=["POST"])
def api_poids_post():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    try:
        poids = float(d["poids"])
        if not (30 <= poids <= 300):
            return jsonify({"ok": False, "error": "Poids hors plage (30–300 kg)"}), 400
        note = d.get("note", "")
        hilo_db.save_poids(db_path, poids, note)
        return jsonify({"ok": True})
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ─────────────────────────────────────────────────────────────────────────────
# Module Sommeil — V8.0.0
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/sommeil/stats")
def api_sommeil_stats():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        return jsonify({"ok": True, "stats": sommeil_db.get_sommeil_stats(db_path)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sommeil/stats-detail")
def api_sommeil_stats_detail():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        return jsonify({"ok": True, **sommeil_db.get_sommeil_stats_detail(db_path)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sommeil/import-oscar", methods=["POST"])
def api_sommeil_import_oscar():
    """Import OSCAR CSV — détecte automatiquement résumé ou détaillé."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    if 'file' not in request.files:
        return jsonify({"ok": False, "error": "Aucun fichier reçu"}), 400
    f = request.files['file']
    if not f.filename.lower().endswith('.csv'):
        return jsonify({"ok": False, "error": "Le fichier doit être un CSV OSCAR"}), 400
    try:
        content = f.read()
        # Détection automatique du format
        fmt = sommeil_db.detect_oscar_format(content)
        if fmt == 'detail':
            result = sommeil_db.import_oscar_detail(db_path, content, f.filename)
            result['format'] = 'detail'
        elif fmt == 'resume':
            result = sommeil_db.import_oscar_csv(db_path, content, f.filename)
            result['format'] = 'resume'
        else:
            return jsonify({"ok": False,
                "error": "Format non reconnu — vérifiez les en-têtes du CSV OSCAR"}), 400
        return jsonify(result)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500



@app.route("/api/oscar/nuit")
def api_oscar_nuit():
    """Timeline d'une nuit : pression + evenements apnees."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configuree"}), 400
    try:
        date = request.args.get("date", "")
        with hilo_db.get_conn(db_path) as conn:
            # Verifier tables
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            if "oscar_sessions" not in tables:
                return jsonify({"ok": False, "error": "Tables OSCAR absentes"}), 400

            # Si pas de date, prendre la derniere nuit
            if not date:
                row = conn.execute(
                    "SELECT date FROM oscar_sessions ORDER BY date DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return jsonify({"ok": False, "error": "Aucune session OSCAR"}), 404
                date = row[0]

            # Session
            sess = conn.execute(
                "SELECT date, session_id, debut_ts, fin_ts, duree_min, "
                "iah_calc, n_ca, n_hypo, n_obs, n_total, "
                "pression_moy, pression_p95, pression_min, pression_max "
                "FROM oscar_sessions WHERE date=?", (date,)
            ).fetchone()
            if not sess:
                return jsonify({"ok": False, "error": "Nuit introuvable"}), 404

            session = {
                "date":         sess[0],
                "session_id":   sess[1],
                "debut_ts":     sess[2],
                "fin_ts":       sess[3],
                "duree_min":    sess[4],
                "iah_calc":     sess[5],
                "n_ca":         sess[6],
                "n_hypo":       sess[7],
                "n_obs":        sess[8],
                "n_total":      sess[9],
                "pression_moy": sess[10],
                "pression_p95": sess[11],
                "pression_min": sess[12],
                "pression_max": sess[13],
            }

            # Evenements apnees
            evts = []
            temps_apnee_sec = 0
            if "oscar_events" in tables:
                rows_e = conn.execute(
                    "SELECT ts, heure, type_event, duree_sec "
                    "FROM oscar_events WHERE date=? ORDER BY ts",
                    (date,)
                ).fetchall()
                for r in rows_e:
                    dur = r[3]
                    if dur: temps_apnee_sec += dur
                    evts.append({
                        "ts":    r[0],
                        "heure": r[1],
                        "type":  r[2],
                        "duree": dur,
                    })
            session["temps_apnee_sec"] = round(temps_apnee_sec)

            # Pression -- sous-echantillonnage : 1 point par minute max
            pressure = []
            if "oscar_pressure" in tables and sess[2] and sess[3]:
                rows_p = conn.execute(
                    "SELECT ts, valeur FROM oscar_pressure "
                    "WHERE date=? ORDER BY ts",
                    (date,)
                ).fetchall()
                # Grouper par minute, garder la moyenne
                from collections import defaultdict
                by_min = defaultdict(list)
                for r in rows_p:
                    minute_key = r[0] // 60
                    by_min[minute_key].append(r[1])
                all_vals = [r[1] for r in rows_p]
                if all_vals:
                    sv = sorted(all_vals)
                    session["pression_p995"] = round(sv[int(len(sv)*0.995)], 2)
                for mk in sorted(by_min.keys()):
                    vals = by_min[mk]
                    pressure.append({
                        "ts":     mk * 60,
                        "valeur": round(sum(vals) / len(vals), 2),
                    })

            # Tension durant la nuit (debut_ts → fin_ts)
            tension_nuit = []
            if sess[2] and sess[3]:
                from datetime import datetime as _dtn
                ts_deb = sess[2]
                ts_fin = sess[3]
                rows_t = conn.execute(
                    "SELECT strftime('%s', timestamp) AS ts_unix, "
                    "systolic, diastolic, heartrate "
                    "FROM mesures "
                    "WHERE systolic IS NOT NULL "
                    "AND CAST(strftime('%s', timestamp) AS INTEGER) BETWEEN ? AND ? "
                    "ORDER BY timestamp",
                    (ts_deb - 7200, ts_fin + 7200)
                ).fetchall()
                for r in rows_t:
                    tension_nuit.append({
                        "ts":  int(r[0]),
                        "sys": r[1],
                        "dia": r[2],
                        "fc":  r[3],
                    })

            # Navigation prev/next
            prev_row = conn.execute(
                "SELECT date FROM oscar_sessions WHERE date<? ORDER BY date DESC LIMIT 1",
                (date,)
            ).fetchone()
            next_row = conn.execute(
                "SELECT date FROM oscar_sessions WHERE date>? ORDER BY date ASC LIMIT 1",
                (date,)
            ).fetchone()

        return jsonify({
            "ok":       True,
            "date":     date,
            "session":  session,
            "events":   evts,
            "pressure": pressure,
            "tension_nuit": tension_nuit,
            "prev":     prev_row[0] if prev_row else None,
            "next":     next_row[0] if next_row else None,
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/oscar/horaire")
def api_oscar_horaire():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        days = request.args.get("days", "180")
        with hilo_db.get_conn(db_path) as conn:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='oscar_events'"
            ).fetchone()
            if not exists:
                return jsonify({"ok": True, "data": [], "n_nuits": 0, "n_events": 0})
            where = ""
            args  = []
            if days and days != "tout":
                from datetime import datetime as _dt2, timedelta as _td2
                cutoff = (_dt2.now() - _td2(days=int(days))).strftime("%Y-%m-%d")
                where  = "WHERE date >= ?"
                args   = [cutoff]
            sql = ("SELECT CASE WHEN heure != '' THEN CAST(substr(heure,1,2) AS INTEGER) "
                   "ELSE CAST(strftime('%H', datetime(ts, 'unixepoch', 'localtime')) AS INTEGER) END as h, "
                   "type_event, COUNT(*) as n "
                   "FROM oscar_events " + where + " GROUP BY h, type_event ORDER BY h")
            rows    = conn.execute(sql, args).fetchall()
            n_nuits = conn.execute("SELECT COUNT(DISTINCT date) FROM oscar_events " + where, args).fetchone()[0]
            n_ev    = conn.execute("SELECT COUNT(*) FROM oscar_events " + where, args).fetchone()[0]
            # Heures moyennes de coucher/réveil — moyenne circulaire
            import math as _math
            heures_rows = conn.execute(
                "SELECT CAST(strftime('%H', datetime(debut_ts,'unixepoch','localtime')) AS INTEGER), "
                "       CAST(strftime('%M', datetime(debut_ts,'unixepoch','localtime')) AS INTEGER), "
                "       CAST(strftime('%H', datetime(fin_ts,  'unixepoch','localtime')) AS INTEGER), "
                "       CAST(strftime('%M', datetime(fin_ts,  'unixepoch','localtime')) AS INTEGER) "
                "FROM oscar_sessions WHERE debut_ts IS NOT NULL AND fin_ts IS NOT NULL " +
                ("AND date >= ?" if args else ""), args
            ).fetchall()
            def _heure_circulaire(vals_h, vals_m):
                # Moyenne circulaire pour éviter le problème 23h+1h=12h
                sin_sum = sum(_math.sin(2*_math.pi*(h+m/60)/24) for h,m in zip(vals_h,vals_m))
                cos_sum = sum(_math.cos(2*_math.pi*(h+m/60)/24) for h,m in zip(vals_h,vals_m))
                angle   = _math.atan2(sin_sum, cos_sum)
                h_moy   = (angle * 24 / (2*_math.pi)) % 24
                return round(h_moy)
            if heures_rows:
                h_coucher = _heure_circulaire([r[0] for r in heures_rows],
                                              [r[1] for r in heures_rows])
                h_reveil  = _heure_circulaire([r[2] for r in heures_rows],
                                              [r[3] for r in heures_rows])
            else:
                h_coucher, h_reveil = 23, 7
        by_h = {}
        for r in rows:
            h = r[0]
            if h not in by_h: by_h[h] = {"h": h, "ca": 0, "hypo": 0, "obs": 0, "total": 0}
            t = r[1]; n = r[2]
            if   t == "ClearAirway":  by_h[h]["ca"]   = n
            elif t == "Hypopnea":     by_h[h]["hypo"] = n
            elif t == "Obstructive":  by_h[h]["obs"]  = n
            elif t == "Apnea":        by_h[h]["ca"]  += n  # NC comptee avec Centrale
            by_h[h]["total"] += n
        data = []
        for h in list(range(15, 24)) + list(range(0, 15)):
            data.append(by_h.get(h, {"h": h, "ca": 0, "hypo": 0, "obs": 0, "total": 0}))
        return jsonify({"ok": True, "data": data, "n_nuits": n_nuits, "n_events": n_ev, "h_coucher": h_coucher, "h_reveil": h_reveil})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500



# ─────────────────────────────────────────────────────────────────────────────
# OSCAR V2 (DB directe)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/oscar/v2/test", methods=["POST"])
def api_oscar_v2_test():
    """Teste la connexion à la DB OSCAR V2."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        data = request.get_json(force=True)
        oscar_path = data.get("oscar_db_path", "").strip()
        if not oscar_path:
            oscar_path = hilo_db.get_setting(db_path, "oscar_db_path", "")
        if not oscar_path:
            return jsonify({"ok": False, "error": "Chemin DB OSCAR non configuré"}), 400
        ok, msg = sommeil_db.test_oscar_v2_connection(oscar_path)
        return jsonify({"ok": ok, "message": msg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/oscar/v2/config", methods=["GET"])
def api_oscar_v2_config_get():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    path = hilo_db.get_setting(db_path, "oscar_db_path", "")
    return jsonify({"ok": True, "oscar_db_path": path})

@app.route("/api/oscar/v2/config", methods=["POST"])
def api_oscar_v2_config_save():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    data = request.get_json(force=True)
    oscar_path = data.get("oscar_db_path", "").strip()
    hilo_db.set_setting(db_path, "oscar_db_path", oscar_path, "Chemin DB OSCAR V2")
    return jsonify({"ok": True})

@app.route("/api/oscar/v2/count", methods=["GET"])
def api_oscar_v2_count():
    """Retourne le nombre de nuits disponibles dans la DB OSCAR V2."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        oscar_path = hilo_db.get_setting(db_path, "oscar_db_path", "")
        if not oscar_path:
            return jsonify({"ok": False, "error": "Chemin DB OSCAR non configuré"}), 400
        import sqlite3 as _sq
        con = _sq.connect(f"file:{oscar_path}?mode=ro", uri=True)
        n_oscar = con.execute("SELECT COUNT(*) FROM daily_summaries WHERE profile_id=1").fetchone()[0]
        n_hilo  = 0
        try:
            with hilo_db.get_conn(db_path) as hcon:
                n_hilo = hcon.execute("SELECT COUNT(*) FROM oscar_sessions").fetchone()[0]
        except:
            pass
        con.close()
        return jsonify({"ok": True, "n_oscar": n_oscar, "n_hilo": n_hilo})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/oscar/v2/import", methods=["POST"])
def api_oscar_v2_import():
    """Importe toutes les nuits depuis la DB OSCAR V2."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        oscar_path = hilo_db.get_setting(db_path, "oscar_db_path", "")
        if not oscar_path:
            return jsonify({"ok": False, "error": "Chemin DB OSCAR V2 non configuré"}), 400
        result = sommeil_db.import_oscar_v2(oscar_path, db_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/oscar/v2/startup-sync", methods=["POST"])
def api_oscar_v2_startup_sync():
    """Synchro OSCAR V2 au démarrage — silencieuse, nouvelles nuits seulement."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"})
    try:
        # Vérifier module sommeil actif
        modules = hilo_db.get_modules(db_path)
        if not modules.get("sommeil", {}).get("actif", 0):
            return jsonify({"ok": False, "error": "Module sommeil désactivé"})
        # Vérifier chemin OSCAR configuré
        oscar_path = hilo_db.get_setting(db_path, "oscar_db_path", "")
        if not oscar_path:
            return jsonify({"ok": False, "error": "OSCAR non configuré"})
        # Import + sync
        result = sommeil_db.import_oscar_v2(oscar_path, db_path)
        if result.get("ok"):
            sync = sommeil_db.sync_oscar_to_ppc(db_path)
            result["sync"] = sync
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/oscar/sync-ppc", methods=["POST"])
def api_oscar_sync_ppc():
    """Synchronise oscar_sessions → sommeil_ppc manuellement."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        result = sommeil_db.sync_oscar_to_ppc(db_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/withings/config", methods=["GET"])
def api_withings_config_get():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    cfg = hilo_db.get_withings_config(db_path)
    # Ne pas exposer les tokens, juste les identifiants et le statut
    return jsonify({
        "ok": True,
        "client_id":       cfg.get("client_id", ""),
        "consumer_secret": cfg.get("consumer_secret", ""),
        "has_tokens":      bool(cfg.get("access_token")),
    })

@app.route("/api/withings/config", methods=["POST"])
def api_withings_config_post():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    client_id       = d.get("client_id", "").strip()
    consumer_secret = d.get("consumer_secret", "").strip()
    if not client_id or not consumer_secret:
        return jsonify({"ok": False, "error": "Client ID et Consumer Secret requis"}), 400
    hilo_db.save_withings_credentials(db_path, client_id, consumer_secret)
    return jsonify({"ok": True})

@app.route("/api/withings/auth_url", methods=["GET"])
def api_withings_auth_url():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    cfg = hilo_db.get_withings_config(db_path)
    if not cfg.get("client_id") or not cfg.get("consumer_secret"):
        return jsonify({"ok": False, "error": "Identifiants Withings non configurés"}), 400
    try:
        from withings_api import WithingsAuth, AuthScope
        auth = WithingsAuth(
            client_id=cfg["client_id"],
            consumer_secret=cfg["consumer_secret"],
            callback_uri="http://localhost/callback",
            scope=(AuthScope.USER_METRICS, AuthScope.USER_ACTIVITY, AuthScope.USER_INFO),
        )
        url = auth.get_authorize_url()
        return jsonify({"ok": True, "url": url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/withings/exchange_code", methods=["POST"])
def api_withings_exchange_code():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    cfg = hilo_db.get_withings_config(db_path)
    d   = request.json or {}
    code = d.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "Code manquant"}), 400
    try:
        from withings_api import WithingsAuth, AuthScope
        auth = WithingsAuth(
            client_id=cfg["client_id"],
            consumer_secret=cfg["consumer_secret"],
            callback_uri="http://localhost/callback",
            scope=(AuthScope.USER_METRICS, AuthScope.USER_ACTIVITY, AuthScope.USER_INFO),
        )
        creds = auth.get_credentials(code)
        hilo_db.save_withings_tokens(db_path, creds.access_token, creds.refresh_token)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

def _refresh_withings_token(db_path):
    """Rafraîchit le token Withings et le sauvegarde.
    Retourne (access_token, error_str) — un seul appel partagé entre les syncs.
    """
    import requests as req
    cfg = hilo_db.get_withings_config(db_path)
    if not cfg.get("refresh_token"):
        return None, "Withings non autorisé"
    try:
        resp = req.post("https://wbsapi.withings.net/v2/oauth2", data={
            "action":        "requesttoken",
            "grant_type":    "refresh_token",
            "client_id":     cfg["client_id"],
            "client_secret": cfg["consumer_secret"],
            "refresh_token": cfg["refresh_token"],
        })
        body = resp.json().get("body", {})
        access_token = body.get("access_token")
        new_refresh  = body.get("refresh_token")
        if not access_token:
            return None, f"Échec refresh token : {resp.json()}"
        hilo_db.save_withings_tokens(db_path, access_token, new_refresh)
        return access_token, None
    except Exception as e:
        return None, f"Erreur réseau (token) : {e}"


def _sync_withings_poids(db_path, access_token=None):
    """Logique de sync Withings réutilisable (démarrage + appel manuel).
    Retourne un dict {ok, importe, doublons, error}.
    """
    import requests as req
    from datetime import datetime
    from collections import defaultdict

    # Utiliser le token partagé si fourni, sinon en obtenir un nouveau
    if access_token is None:
        access_token, err = _refresh_withings_token(db_path)
        if err:
            return {"ok": False, "error": err}

    # Récupérer toutes les mesures avec pagination (limite 300/page)
    all_grps = []
    try:
        offset = 0
        while True:
            resp = req.post("https://wbsapi.withings.net/measure", data={
                "action":       "getmeas",
                "access_token": access_token,
                "startdate":    315532800,  # 01/01/1980 — tout l'historique
                "enddate":      int(datetime.now().timestamp()),
                "offset":       offset,
            })
            data = resp.json()
            if data.get("status") != 0:
                return {"ok": False, "error": f"Erreur API Withings : {data}"}
            body = data.get("body", {})
            grps = body.get("measuregrps", [])
            all_grps.extend(grps)
            if body.get("more") == 1:
                offset += 300
            else:
                break
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau (mesures) : {e}"}

    # Regrouper par date et insérer
    par_date = defaultdict(lambda: {
        "poids": None, "masse_grasse_pct": None,
        "masse_grasse_kg": None, "masse_musculaire": None,
    })
    for grp in all_grps:
        date_str = datetime.fromtimestamp(grp["date"]).strftime("%Y-%m-%d")
        for mesure in grp["measures"]:
            val = round(mesure["value"] * (10 ** mesure["unit"]), 4)
            if mesure["type"] == 1:
                par_date[date_str]["poids"] = round(val, 2)
            elif mesure["type"] == 6:
                par_date[date_str]["masse_grasse_pct"] = round(val, 2)
            elif mesure["type"] == 8:
                par_date[date_str]["masse_grasse_kg"] = round(val, 2)
            elif mesure["type"] == 76:
                par_date[date_str]["masse_musculaire"] = round(val, 2)

    importe = doublons = 0
    for date_str, vals in sorted(par_date.items()):
        if vals["poids"] is None:
            continue
        masse_grasse = None
        if vals["masse_grasse_pct"] is not None:
            masse_grasse = round(vals["masse_grasse_pct"] / 100.0 * vals["poids"], 2)
        elif vals["masse_grasse_kg"] is not None:
            masse_grasse = vals["masse_grasse_kg"]
        if hilo_db.save_poids_withings(
            db_path, date_str, vals["poids"],
            masse_grasse=masse_grasse,
            masse_musculaire=vals["masse_musculaire"]
        ):
            importe += 1
        else:
            doublons += 1

    return {"ok": True, "importe": importe, "doublons": doublons}


@app.route("/api/withings/sync_poids", methods=["POST"])
def api_withings_sync_poids():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    _mod = hilo_db.get_modules(db_path)
    if not _mod.get("poids", {}).get("actif", 1) or not _mod.get("poids", {}).get("poids_api", 1):
        return jsonify({"ok": False, "error": "Module Poids API désactivé"}), 403
    result = _sync_withings_poids(db_path)
    if result.get("ok"):
        from datetime import datetime as _dt
        hilo_db.set_setting(db_path, "withings_last_sync_poids",
            _dt.now().strftime("%Y-%m-%d %H:%M"))
        hilo_db.set_setting(db_path, "withings_last_sync_poids_n",
            str(result.get("importe", 0)))
    status = 200 if result["ok"] else 500
    return jsonify(result), status


@app.route("/api/sommeil/withings", methods=["POST"])
def api_sommeil_withings_save():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    d = request.json or {}
    try:
        date = d["date"]
        iah  = float(d["iah"])
        if iah < 0 or iah > 200:
            return jsonify({"ok": False, "error": "IAH hors plage"}), 400
        return jsonify(sommeil_db.save_withings(db_path, date, iah))
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/sommeil/withings/<int:entry_id>", methods=["DELETE"])
def api_sommeil_withings_delete(entry_id):
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    return jsonify(sommeil_db.delete_withings(db_path, entry_id))


@app.route("/api/sommeil/data")
def api_sommeil_data():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    date_start = request.args.get("date_start")
    date_end   = request.args.get("date_end")
    try:
        data  = sommeil_db.get_sommeil_data(db_path, date_start, date_end)
        stats = sommeil_db.get_sommeil_stats(db_path)
        return jsonify({"ok": True, "data": data, "stats": stats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/sommeil/graphique")
def api_sommeil_graphique():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    try:
        mois = int(request.args.get("mois", 6))
        return jsonify({"ok": True,
                        "points": sommeil_db.get_sommeil_graphique(db_path, mois)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Sync SleepAnalyser Withings
# ─────────────────────────────────────────────────────────────────────────────

def _sync_withings_sleep(db_path, access_token=None):
    """Sync complète SleepAnalyser Withings → sommeil_withings.
    - Pagine toutes les pages (limite API = 300/page)
    - Date décalée -1 jour (API retourne date de fin de nuit)
    - AHI = 0 ou < 0 ignorés (sieste/artefact)
    - Doublons même date : garde la plus grande AHI
    - UPDATE toujours si date existe déjà en base
    Retourne dict {ok, importe, mis_a_jour, ignores, error}
    """
    import requests as req
    from datetime import datetime, timedelta

    # Utiliser le token partagé si fourni, sinon en obtenir un nouveau
    if access_token is None:
        access_token, err = _refresh_withings_token(db_path)
        if err:
            return {"ok": False, "error": err}

    # Récupérer toutes les pages
    all_series = []
    offset     = 0
    try:
        while True:
            r = req.post("https://wbsapi.withings.net/v2/sleep", data={
                "action":       "getsummary",
                "access_token": access_token,
                "startdateymd": "2000-01-01",
                "enddateymd":   datetime.now().strftime("%Y-%m-%d"),
                "data_fields":  "apnea_hypopnea_index,breathing_disturbances_intensity,total_timeinbed",
                "offset":       offset,
            })
            body = r.json()
            if body.get("status") != 0:
                return {"ok": False, "error": f"Erreur API Withings sleep : {body}"}
            b      = body.get("body", {})
            series = b.get("series", [])
            all_series.extend(series)
            if b.get("more") == 1 and len(series) == 300:
                offset += 300
            else:
                break
    except Exception as e:
        return {"ok": False, "error": f"Erreur réseau (sleep) : {e}"}

    # Construire les entrées valides avec décalage -1 jour
    # L'API retourne data soit comme dict {key:val} soit comme liste [{key,value}]
    def _get_data_field(s, field):
        d = s.get("data")
        if isinstance(d, dict):
            return d.get(field)
        elif isinstance(d, list):
            for item in d:
                if item.get("key") == field or item.get("field") == field:
                    v = item.get("value")
                    u = item.get("unit", 0)
                    try:
                        return round(float(v) * (10 ** int(u)), 3) if u else float(v)
                    except (TypeError, ValueError):
                        return v
        return None

    entries = []
    for s in all_series:
        ahi = _get_data_field(s, "apnea_hypopnea_index")
        if ahi is None or ahi <= 0:
            continue
        _sd    = datetime.fromtimestamp(s.get("startdate", 0))
        # Si coucher entre 00:00 et 14:59 → nuit commencée la veille → j-1
        nuit   = (_sd - timedelta(days=1)).strftime("%Y-%m-%d") if _sd.hour < 15 else _sd.strftime("%Y-%m-%d")
        bdi    = _get_data_field(s, "breathing_disturbances_intensity")
        # Durée : total_timeinbed en secondes → minutes, sinon enddate-startdate
        ttib = _get_data_field(s, "total_timeinbed")
        if ttib is not None:
            try:
                duree_min = int(float(ttib) / 60)
            except (TypeError, ValueError):
                duree_min = None
        else:
            try:
                duree_min = int((s.get("enddate", 0) - s.get("startdate", 0)) / 60)
            except Exception:
                duree_min = None
        entries.append({
            "date":         nuit,
            "iah":          ahi,
            "breathing":    bdi,
            "duree_min":    duree_min,
            "startdate_ts": int(s.get("startdate", 0)),
        })

    result = sommeil_db.save_withings_batch(db_path, entries)
    if result.get("ok"):
        # Propager les nouvelles entrées vers sommeil_withings (INSERT OR IGNORE)
        prop = sommeil_db.propagate_api_to_withings(db_path)
        result["ajoutes_withings"] = prop.get("ajoutes", 0)
    return result


@app.route("/api/withings/sync_sleep", methods=["POST"])
def api_withings_sync_sleep():
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    result = _sync_withings_sleep(db_path)
    if result.get("ok"):
        from datetime import datetime as _dt
        hilo_db.set_setting(db_path, "withings_last_sync_sleep",
            _dt.now().strftime("%Y-%m-%d %H:%M"))
        hilo_db.set_setting(db_path, "withings_last_sync_sleep_n",
            str(result.get("importe", 0) + result.get("ajoutes_withings", 0)))
    return jsonify(result), (200 if result["ok"] else 500)




@app.route("/api/withings/status")
def api_withings_status():
    """Retourne l'état des dernières synchronisations Withings."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False}), 400
    def gs(k, default="—"):
        return hilo_db.get_setting(db_path, k, default)
    # Vérifier si token valide
    cfg = None
    try:
        with hilo_db.get_conn(db_path) as conn:
            cfg = conn.execute("SELECT refresh_token FROM withings_config WHERE id=1").fetchone()
    except: pass
    token_ok = bool(cfg and cfg[0])
    # Backup : dernière sauvegarde depuis l'historique
    last_backup = "—"
    try:
        with hilo_db.get_conn(db_path) as conn:
            row = conn.execute(
                "SELECT detail, cree_le FROM hilo_historique WHERE action='BACKUP' ORDER BY cree_le DESC LIMIT 1"
            ).fetchone()
            if row:
                last_backup = f"{row[0]} ({row[1][:16]})"
    except: pass
    return jsonify({
        "ok": True,
        "token_ok":         token_ok,
        "last_sync_poids":  gs("withings_last_sync_poids"),
        "last_sync_poids_n": gs("withings_last_sync_poids_n", "0"),
        "last_sync_sleep":  gs("withings_last_sync_sleep"),
        "last_sync_sleep_n": gs("withings_last_sync_sleep_n", "0"),
        "last_backup":      last_backup,
    })

@app.route("/api/withings/sync_all", methods=["POST"])
def api_withings_sync_all():
    """Sync poids + sleep avec un seul refresh token - evite erreur 601 (Same arguments)."""
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    # Un seul refresh partagé
    access_token, err = _refresh_withings_token(db_path)
    if err:
        return jsonify({"ok": False, "poids": {"ok": False, "error": err},
                        "sleep": {"ok": False, "error": err}}), 400
    r_poids = _sync_withings_poids(db_path, access_token=access_token)
    r_sleep = _sync_withings_sleep(db_path, access_token=access_token)
    ok = r_poids.get("ok") or r_sleep.get("ok")
    return jsonify({"ok": ok, "poids": r_poids, "sleep": r_sleep}), (200 if ok else 500)


# ─────────────────────────────────────────────────────────────────────────────
# Debug Sommeil Withings (SleepAnalyser) — route temporaire
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/withings/debug_sleep", methods=["POST"])
def api_withings_debug_sleep():
    """Route de test : dump brut des données sommeil Withings dans la console Flask.
    Récupère les données via l'API REST directe (action=getsummary) avec meastypes
    incluant l'apnea_hypopnea_index (type 270).
    """
    import requests as req
    from datetime import datetime, timedelta
    import json

    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400
    cfg = hilo_db.get_withings_config(db_path)
    if not cfg.get("refresh_token"):
        return jsonify({"ok": False, "error": "Withings non autorisé"}), 400

    # Rafraîchir le token
    try:
        resp = req.post("https://wbsapi.withings.net/v2/oauth2", data={
            "action":        "requesttoken",
            "grant_type":    "refresh_token",
            "client_id":     cfg["client_id"],
            "client_secret": cfg["consumer_secret"],
            "refresh_token": cfg["refresh_token"],
        })
        body = resp.json().get("body", {})
        access_token = body.get("access_token")
        new_refresh  = body.get("refresh_token")
        if not access_token:
            return jsonify({"ok": False, "error": f"Échec refresh token : {resp.json()}"}), 500
        hilo_db.save_withings_tokens(db_path, access_token, new_refresh)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Erreur réseau (token) : {e}"}), 500

    results = {}

    # ── getsummary avec pagination complète ───────────────────────────────────
    # L'API Withings limite à 300 entrées par page — on pagine jusqu'à tout récupérer
    # On remonte le plus loin possible (startdateymd très ancienne)
    try:
        all_series = []
        offset = 0
        page_size = 300
        start_ymd = "2000-01-01"
        end_ymd   = datetime.now().strftime("%Y-%m-%d")

        while True:
            r1 = req.post("https://wbsapi.withings.net/v2/sleep", data={
                "action":       "getsummary",
                "access_token": access_token,
                "startdateymd": start_ymd,
                "enddateymd":   end_ymd,
                "data_fields":  "apnea_hypopnea_index,breathing_disturbances_intensity,sleep_score",
                "offset":       offset,
            })
            d1 = r1.json()
            if d1.get("status") != 0:
                print(f"[getsummary] Erreur status={d1.get('status')} offset={offset} : {d1}")
                break
            body   = d1.get("body", {})
            series = body.get("series", [])
            all_series.extend(series)
            print(f"[getsummary] Page offset={offset} : {len(series)} entrées récupérées (total: {len(all_series)})")
            # more=1 signifie qu'il reste des pages
            if body.get("more") == 1 and len(series) == page_size:
                offset += page_size
            else:
                break

        sep = "=" * 60
        print("\n" + sep)
        print("DEBUG Withings Sleep — v2/sleep getsummary (toutes pages)")
        print(sep)
        print(f"Total entrées récupérées : {len(all_series)}")

        # Filtrer uniquement les entrées avec AHI (SleepAnalyser)
        def _gdf(s, field):
            d = s.get("data")
            if isinstance(d, dict): return d.get(field)
            elif isinstance(d, list):
                for item in d:
                    if item.get("key") == field or item.get("field") == field:
                        v = item.get("value"); u = item.get("unit", 0)
                        try: return round(float(v)*(10**int(u)),3) if u else float(v)
                        except: return v
            return None
        with_ahi = [s for s in all_series if _gdf(s, "apnea_hypopnea_index") is not None]
        print(f"Entrées avec apnea_hypopnea_index : {len(with_ahi)}")
        print(f"Entrées sans AHI (montre/téléphone) : {len(all_series) - len(with_ahi)}")
        print(sep)

        # Décalage -1 jour : l'API retourne la date de FIN de nuit
        # ex: "2023-03-04" = nuit du 3 au 4 mars → on stocke "2023-03-03"
        from datetime import timedelta as _td
        def _nuit_date(s):
            _sd = datetime.fromtimestamp(s.get("startdate", 0))
            return (_sd - timedelta(days=1)).strftime("%Y-%m-%d") if _sd.hour < 15 else _sd.strftime("%Y-%m-%d")

        # Filtrer AHI invalides (None, -1, négatifs)
        valid_ahi = [s for s in with_ahi
                     if _gdf(s, "apnea_hypopnea_index") is not None
                     and _gdf(s, "apnea_hypopnea_index") >= 0]

        print(f"Entrées AHI valides (>= 0) : {len(valid_ahi)}")
        print(f"Entrées AHI invalides (=-1) : {len(with_ahi) - len(valid_ahi)}")

        print("\n-- 10 nuits les plus recentes — detail startdate vs enddate --")
        recent = sorted(valid_ahi, key=lambda x: x.get("startdate", 0), reverse=True)
        for i, s in enumerate(recent[:10]):
            sd = s.get("startdate", 0)
            ed = s.get("enddate",   0)
            ahi = _gdf(s, "apnea_hypopnea_index")
            d_start      = datetime.fromtimestamp(sd).strftime("%Y-%m-%d %H:%M")
            d_end        = datetime.fromtimestamp(ed).strftime("%Y-%m-%d %H:%M") if ed else "?"
            d_start_date = datetime.fromtimestamp(sd).strftime("%Y-%m-%d")
            d_end_date   = datetime.fromtimestamp(ed).strftime("%Y-%m-%d") if ed else "?"
            d_start_m1   = (datetime.fromtimestamp(sd) - timedelta(days=1)).strftime("%Y-%m-%d")
            d_end_m1     = (datetime.fromtimestamp(ed) - timedelta(days=1)).strftime("%Y-%m-%d") if ed else "?"
            print(f"  [{i+1}] AHI={ahi}")
            print(f"         startdate : {d_start}  → date={d_start_date}  -1j={d_start_m1}")
            print(f"         enddate   : {d_end}  → date={d_end_date}  -1j={d_end_m1}")

        print("\n-- 5 premières entrées SANS AHI (pour info) --")
        without_ahi = [s for s in all_series if _gdf(s, "apnea_hypopnea_index") is None]
        for i, s in enumerate(without_ahi[:5]):
            dt    = datetime.fromtimestamp(s.get("startdate", 0)).strftime("%Y-%m-%d")
            score = _gdf(s, "sleep_score")
            model = s.get("model_id") or s.get("model") or "?"
            print(f"  [{i+1}] {dt} | sleep_score={score} | model_id={model}")

        # ── Export TXT ────────────────────────────────────────────────────────
        import os
        txt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_sleep_ahi.txt")
        with open(txt_path, "w", encoding="utf-8") as tf:
            tf.write("date_nuit\tahi\tbreathing_disturbances\tsleep_score\n")
            for s in sorted(valid_ahi, key=lambda x: x.get("startdate", 0)):
                nuit  = _nuit_date(s)
                ahi   = _gdf(s, "apnea_hypopnea_index")
                bdi   = _gdf(s, "breathing_disturbances_intensity") or ""
                score = _gdf(s, "sleep_score") or ""  
                tf.write(f"{nuit}\t{ahi}\t{bdi}\t{score}\n")
        print(f"\n✅ Fichier TXT exporté : {txt_path}")
        print(f"   {len(valid_ahi)} lignes (date_nuit / ahi / breathing / sleep_score)")

        results["getsummary"] = {
            "status": 0,
            "total": len(all_series),
            "with_ahi": len(with_ahi),
            "valid_ahi": len(valid_ahi),
            "without_ahi": len(without_ahi),
            "txt_path": txt_path,
            "sample_ahi": valid_ahi[:3],
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        results["getsummary"] = {"error": str(e)}

    sep = "=" * 60
    print(sep)
    print("DEBUG terminé — vérifiez les valeurs ci-dessus dans la console.")
    print(sep + "\n")

    return jsonify({"ok": True, "results": results,
                    "message": "Données dumpées dans la console Flask — vérifiez le terminal."})


# ─────────────────────────────────────────────────────────────────────────────
# Expert — tables supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/expert/poids")
def api_expert_poids():
    db_path = get_db_path()
    if not db_path: return jsonify({"ok": False}), 400
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    search   = request.args.get("search", "").strip()
    with hilo_db.get_conn(db_path) as conn:
        where = "WHERE date(mesure_le) LIKE ?" if search else ""
        args  = [f"%{search}%"] if search else []
        total = conn.execute(f"SELECT COUNT(*) FROM poids_historique {where}", args).fetchone()[0]
        rows  = conn.execute(
            f"SELECT * FROM poids_historique {where} ORDER BY mesure_le DESC LIMIT ? OFFSET ?",
            args + [per_page, (page-1)*per_page]
        ).fetchall()
    return jsonify({"ok": True, "total": total, "rows": [dict(r) for r in rows],
                    "page": page, "per_page": per_page})


@app.route("/api/expert/poids/<int:row_id>", methods=["DELETE"])
def api_expert_poids_delete(row_id):
    db_path = get_db_path()
    if not db_path: return jsonify({"ok": False}), 400
    with hilo_db.get_conn(db_path) as conn:
        conn.execute("DELETE FROM poids_historique WHERE id=?", (row_id,))
    return jsonify({"ok": True})


@app.route("/api/expert/sommeil_withings")
def api_expert_sommeil_withings():
    db_path = get_db_path()
    if not db_path: return jsonify({"ok": False}), 400
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    search   = request.args.get("search", "").strip()
    with hilo_db.get_conn(db_path) as conn:
        where = "WHERE date LIKE ?" if search else ""
        args  = [f"%{search}%"] if search else []
        total = conn.execute(f"SELECT COUNT(*) FROM sommeil_withings {where}", args).fetchone()[0]
        rows  = conn.execute(
            f"SELECT * FROM sommeil_withings {where} ORDER BY date DESC LIMIT ? OFFSET ?",
            args + [per_page, (page-1)*per_page]
        ).fetchall()
    return jsonify({"ok": True, "total": total, "rows": [dict(r) for r in rows],
                    "page": page, "per_page": per_page})


@app.route("/api/expert/sommeil_withings/<int:row_id>", methods=["DELETE"])
def api_expert_sommeil_withings_delete(row_id):
    db_path = get_db_path()
    if not db_path: return jsonify({"ok": False}), 400
    with hilo_db.get_conn(db_path) as conn:
        conn.execute("DELETE FROM sommeil_withings WHERE id=?", (row_id,))
    return jsonify({"ok": True})


@app.route("/api/expert/sommeil_withings_api")
def api_expert_sommeil_withings_api():
    db_path = get_db_path()
    if not db_path: return jsonify({"ok": False}), 400
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    search   = request.args.get("search", "").strip()
    with hilo_db.get_conn(db_path) as conn:
        where = "WHERE date LIKE ?" if search else ""
        args  = [f"%{search}%"] if search else []
        total = conn.execute(f"SELECT COUNT(*) FROM sommeil_withings_api {where}", args).fetchone()[0]
        rows  = conn.execute(
            f"SELECT * FROM sommeil_withings_api {where} ORDER BY date DESC LIMIT ? OFFSET ?",
            args + [per_page, (page-1)*per_page]
        ).fetchall()
    return jsonify({"ok": True, "total": total, "rows": [dict(r) for r in rows],
                    "page": page, "per_page": per_page})


@app.route("/api/expert/sommeil_withings_api/<int:row_id>", methods=["DELETE"])
def api_expert_sommeil_withings_api_delete(row_id):
    db_path = get_db_path()
    if not db_path: return jsonify({"ok": False}), 400
    with hilo_db.get_conn(db_path) as conn:
        conn.execute("DELETE FROM sommeil_withings_api WHERE id=?", (row_id,))
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# Corrélations
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/correlations/ppc-tension")
def api_correlations_ppc_tension():
    """Corrélations entre événements PPC et tension nocturne — comparaison avant/après."""
    import sqlite3 as _sq

    db = get_db_path()
    if not db:
        return jsonify({"ok": False, "error": "Base non configurée"})

    fenetre_min = int(request.args.get("fenetre", 90))  # fenêtre avant ET après en minutes

    try:
        conn = _sq.connect(str(db))
        conn.row_factory = _sq.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT s.date, s.debut_ts, s.fin_ts, s.iah_calc,
                   s.n_ca, s.n_hypo, s.n_obs, s.n_total
            FROM oscar_sessions s
            WHERE s.debut_ts IS NOT NULL AND s.fin_ts IS NOT NULL
            ORDER BY s.date ASC
        """)
        sessions = cur.fetchall()

        resultats_nuits = []
        deltas_ca   = []
        deltas_hypo = []
        deltas_obs  = []

        fenetre_sec = fenetre_min * 60

        for sess in sessions:
            debut_ts = sess['debut_ts']
            fin_ts   = sess['fin_ts']
            date     = sess['date']

            # Mesures tension de la nuit (avec marge UTC)
            cur.execute("""
                SELECT CAST(strftime('%s', timestamp) AS INTEGER) as ts,
                       systolic, diastolic
                FROM mesures
                WHERE systolic IS NOT NULL
                  AND CAST(strftime('%s', timestamp) AS INTEGER) BETWEEN ? AND ?
                ORDER BY timestamp
            """, (debut_ts - 7200, fin_ts + 7200))
            mesures = list(cur.fetchall())

            if len(mesures) < 2:
                continue

            base_sys = sum(m['systolic'] for m in mesures) / len(mesures)
            base_dia = sum(m['diastolic'] for m in mesures if m['diastolic']) / max(1, len([m for m in mesures if m['diastolic']]))

            # Événements de la nuit
            cur.execute("""
                SELECT ts, type_event FROM oscar_events
                WHERE date = ? ORDER BY ts
            """, (date,))
            events = list(cur.fetchall())

            # Pression par événement (fenêtre ±5 min autour du timestamp)
            cur.execute("""
                SELECT ts, valeur FROM oscar_pressure
                WHERE date = ? ORDER BY ts
            """, (date,))
            pressions = list(cur.fetchall())

            if not events:
                resultats_nuits.append({
                    "date": date, "iah": sess['iah_calc'],
                    "n_ca": sess['n_ca'] or 0, "n_hypo": sess['n_hypo'] or 0,
                    "n_obs": sess['n_obs'] or 0, "n_total": sess['n_total'] or 0,
                    "base_sys": round(base_sys, 1), "base_dia": round(base_dia, 1),
                    "delta_ca": None, "delta_hypo": None, "delta_obs": None,
                    "n_mesures": len(mesures),
                })
                continue

            # Pour chaque événement : mesure AVANT et APRÈS dans la fenêtre
            ev_deltas    = {"ClearAirway": [], "Apnea": [], "Hypopnea": [], "Obstructive": []}
            ev_pressions = {"ClearAirway": [], "Apnea": [], "Hypopnea": [], "Obstructive": []}
            fenetre_pres = 300  # ±5 min en secondes

            for ev in events:
                ev_ts   = ev['ts']
                ev_type = ev['type_event']

                # Pression ±5 min autour de l'événement
                pres_ev = [p['valeur'] for p in pressions
                           if abs(p['ts'] - ev_ts) <= fenetre_pres]
                if pres_ev and ev_type in ev_pressions:
                    ev_pressions[ev_type].append(sum(pres_ev) / len(pres_ev))

                # Mesure la plus proche AVANT l'événement
                avant = [m for m in mesures if m['ts'] <= ev_ts and ev_ts - m['ts'] <= fenetre_sec]
                # Mesure la plus proche APRÈS l'événement
                apres = [m for m in mesures if m['ts'] > ev_ts and m['ts'] - ev_ts <= fenetre_sec]

                if avant and apres:
                    m_avant = max(avant, key=lambda m: m['ts'])
                    m_apres = min(apres, key=lambda m: m['ts'])
                    delta = m_apres['systolic'] - m_avant['systolic']
                    if ev_type in ev_deltas:
                        ev_deltas[ev_type].append(delta)

            vals_ca   = ev_deltas["ClearAirway"] + ev_deltas["Apnea"]
            vals_hypo = ev_deltas["Hypopnea"]
            vals_obs  = ev_deltas["Obstructive"]

            pres_ca   = ev_pressions["ClearAirway"] + ev_pressions["Apnea"]
            pres_hypo = ev_pressions["Hypopnea"]
            pres_obs  = ev_pressions["Obstructive"]

            moy_ca   = round(sum(vals_ca)   / len(vals_ca),   2) if vals_ca   else None
            moy_hypo = round(sum(vals_hypo) / len(vals_hypo), 2) if vals_hypo else None
            moy_obs  = round(sum(vals_obs)  / len(vals_obs),  2) if vals_obs  else None

            pres_moy_ca   = round(sum(pres_ca)  / len(pres_ca),   2) if pres_ca   else None
            pres_moy_hypo = round(sum(pres_hypo)/ len(pres_hypo), 2) if pres_hypo else None
            pres_moy_obs  = round(sum(pres_obs) / len(pres_obs),  2) if pres_obs  else None

            if moy_ca   is not None: deltas_ca.append(moy_ca)
            if moy_hypo is not None: deltas_hypo.append(moy_hypo)
            if moy_obs  is not None: deltas_obs.append(moy_obs)

            resultats_nuits.append({
                "date": date, "iah": sess['iah_calc'],
                "n_ca": sess['n_ca'] or 0, "n_hypo": sess['n_hypo'] or 0,
                "n_obs": sess['n_obs'] or 0, "n_total": sess['n_total'] or 0,
                "base_sys": round(base_sys, 1), "base_dia": round(base_dia, 1),
                "delta_ca":   moy_ca,
                "delta_hypo": moy_hypo,
                "delta_obs":  moy_obs,
                "pres_ca":    pres_moy_ca,
                "pres_hypo":  pres_moy_hypo,
                "pres_obs":   pres_moy_obs,
                "n_mesures": len(mesures),
            })

        # Agrégats pression
        all_pres_ca   = [r['pres_ca']   for r in resultats_nuits if r.get('pres_ca')   is not None]
        all_pres_hypo = [r['pres_hypo'] for r in resultats_nuits if r.get('pres_hypo') is not None]
        all_pres_obs  = [r['pres_obs']  for r in resultats_nuits if r.get('pres_obs')  is not None]

        def moy_std(lst):
            if not lst: return None, None
            m = sum(lst) / len(lst)
            std = (sum((x-m)**2 for x in lst) / len(lst)) ** 0.5
            return round(m, 2), round(std, 2)

        moy_ca,   std_ca   = moy_std(deltas_ca)
        moy_hypo, std_hypo = moy_std(deltas_hypo)
        moy_obs,  std_obs  = moy_std(deltas_obs)

        conn.close()
        return jsonify({
            "ok": True,
            "fenetre_min": fenetre_min,
            "methode": "avant_apres",
            "n_nuits": len(resultats_nuits),
            "agregats": {
                "centrale":    {"moy": moy_ca,   "std": std_ca,   "n": len(deltas_ca),
                                "pres": round(sum(all_pres_ca)/len(all_pres_ca),2) if all_pres_ca else None},
                "hypopnee":    {"moy": moy_hypo, "std": std_hypo, "n": len(deltas_hypo),
                                "pres": round(sum(all_pres_hypo)/len(all_pres_hypo),2) if all_pres_hypo else None},
                "obstructive": {"moy": moy_obs,  "std": std_obs,  "n": len(deltas_obs),
                                "pres": round(sum(all_pres_obs)/len(all_pres_obs),2) if all_pres_obs else None},
            },
            "nuits": resultats_nuits,
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    try:
        conn = _sq.connect(str(db))
        conn.row_factory = _sq.Row
        cur = conn.cursor()

        # Toutes les sessions PPC avec tension disponible
        cur.execute("""
            SELECT s.date, s.debut_ts, s.fin_ts, s.iah_calc,
                   s.n_ca, s.n_hypo, s.n_obs, s.n_total
            FROM oscar_sessions s
            WHERE s.debut_ts IS NOT NULL AND s.fin_ts IS NOT NULL
            ORDER BY s.date ASC
        """)
        sessions = cur.fetchall()

        resultats_nuits = []
        deltas_ca   = []
        deltas_hypo = []
        deltas_obs  = []

        for sess in sessions:
            debut_ts = sess['debut_ts']
            fin_ts   = sess['fin_ts']
            date     = sess['date']

            # Mesures tension durant la nuit (avec marge UTC ±2h)
            cur.execute("""
                SELECT CAST(strftime('%s', timestamp) AS INTEGER) as ts,
                       systolic, diastolic
                FROM mesures
                WHERE systolic IS NOT NULL
                  AND CAST(strftime('%s', timestamp) AS INTEGER) BETWEEN ? AND ?
                ORDER BY timestamp
            """, (debut_ts - 7200, fin_ts + 7200))
            mesures = cur.fetchall()

            if len(mesures) < 2:
                continue  # Pas assez de mesures tension cette nuit

            # Tension de base = moyenne de toutes les mesures de la nuit
            base_sys = sum(m['systolic'] for m in mesures) / len(mesures)
            base_dia = sum(m['diastolic'] for m in mesures if m['diastolic']) / len(mesures)

            # Événements de la nuit
            cur.execute("""
                SELECT ts, type_event FROM oscar_events
                WHERE date = ? ORDER BY ts
            """, (date,))
            events = cur.fetchall()

            if not events:
                # Nuit sans événements — utile pour la corrélation IAH/tension
                resultats_nuits.append({
                    "date": date,
                    "iah": sess['iah_calc'],
                    "n_ca": sess['n_ca'] or 0,
                    "n_hypo": sess['n_hypo'] or 0,
                    "n_obs": sess['n_obs'] or 0,
                    "n_total": sess['n_total'] or 0,
                    "base_sys": round(base_sys, 1),
                    "base_dia": round(base_dia, 1),
                    "delta_ca": None,
                    "delta_hypo": None,
                    "delta_obs": None,
                    "n_mesures": len(mesures),
                })
                continue

            # Pour chaque événement, trouver la mesure tension la plus proche après
            fenetre_sec = fenetre_min * 60
            ev_deltas = {"ClearAirway": [], "Apnea": [], "Hypopnea": [], "Obstructive": []}

            for ev in events:
                ev_ts   = ev['ts']
                ev_type = ev['type_event']
                # Chercher la mesure tension dans la fenêtre [ev_ts, ev_ts + fenetre]
                candidates = [m for m in mesures
                              if ev_ts <= m['ts'] <= ev_ts + fenetre_sec]
                if candidates:
                    # Prendre la plus proche
                    closest = min(candidates, key=lambda m: m['ts'] - ev_ts)
                    delta = closest['systolic'] - base_sys
                    if ev_type in ev_deltas:
                        ev_deltas[ev_type].append(delta)

            # Fusionner ClearAirway + Apnea → Centrale
            vals_ca   = ev_deltas["ClearAirway"] + ev_deltas["Apnea"]
            vals_hypo = ev_deltas["Hypopnea"]
            vals_obs  = ev_deltas["Obstructive"]

            moy_ca   = round(sum(vals_ca)   / len(vals_ca),   2) if vals_ca   else None
            moy_hypo = round(sum(vals_hypo) / len(vals_hypo), 2) if vals_hypo else None
            moy_obs  = round(sum(vals_obs)  / len(vals_obs),  2) if vals_obs  else None

            if moy_ca   is not None: deltas_ca.append(moy_ca)
            if moy_hypo is not None: deltas_hypo.append(moy_hypo)
            if moy_obs  is not None: deltas_obs.append(moy_obs)

            resultats_nuits.append({
                "date": date,
                "iah": sess['iah_calc'],
                "n_ca": sess['n_ca'] or 0,
                "n_hypo": sess['n_hypo'] or 0,
                "n_obs": sess['n_obs'] or 0,
                "n_total": sess['n_total'] or 0,
                "base_sys": round(base_sys, 1),
                "base_dia": round(base_dia, 1),
                "delta_ca":   moy_ca,
                "delta_hypo": moy_hypo,
                "delta_obs":  moy_obs,
                "pres_ca":    pres_moy_ca,
                "pres_hypo":  pres_moy_hypo,
                "pres_obs":   pres_moy_obs,
                "n_mesures": len(mesures),
            })

        # Agrégats pression
        all_pres_ca   = [r['pres_ca']   for r in resultats_nuits if r.get('pres_ca')   is not None]
        all_pres_hypo = [r['pres_hypo'] for r in resultats_nuits if r.get('pres_hypo') is not None]
        all_pres_obs  = [r['pres_obs']  for r in resultats_nuits if r.get('pres_obs')  is not None]

        def moy_std(lst):
            if not lst: return None, None
            m = sum(lst) / len(lst)
            std = (sum((x-m)**2 for x in lst) / len(lst)) ** 0.5
            return round(m, 2), round(std, 2)

        moy_ca,   std_ca   = moy_std(deltas_ca)
        moy_hypo, std_hypo = moy_std(deltas_hypo)
        moy_obs,  std_obs  = moy_std(deltas_obs)

        conn.close()
        return jsonify({
            "ok": True,
            "fenetre_min": fenetre_min,
            "n_nuits": len(resultats_nuits),
            "agregats": {
                "centrale":    {"moy": moy_ca,   "std": std_ca,   "n": len(deltas_ca),
                                "pres": round(sum(all_pres_ca)/len(all_pres_ca),2) if all_pres_ca else None},
                "hypopnee":    {"moy": moy_hypo, "std": std_hypo, "n": len(deltas_hypo),
                                "pres": round(sum(all_pres_hypo)/len(all_pres_hypo),2) if all_pres_hypo else None},
                "obstructive": {"moy": moy_obs,  "std": std_obs,  "n": len(deltas_obs),
                                "pres": round(sum(all_pres_obs)/len(all_pres_obs),2) if all_pres_obs else None},
            },
            "nuits": resultats_nuits,
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/correlations/velo")
def api_correlations_velo():
    """Corrélations sorties vélo vs tension/IAH/poids à J, J+1, J+2."""
    import sqlite3 as _sq
    from datetime import datetime as _dt, timedelta as _td

    db = get_db_path()
    if not db:
        return jsonify({"ok": False, "error": "Base non configurée"})

    delai = int(request.args.get("delai", 0))

    try:
        conn = _sq.connect(str(db))
        conn.row_factory = _sq.Row
        cur  = conn.cursor()

        # Toutes les sorties vélo
        cur.execute("""
            SELECT id, date, duree_sec, distance_m, elevation_gain, hr_moy
            FROM workouts
            WHERE categorie = 'Vélo' AND date IS NOT NULL
            ORDER BY date ASC
        """)
        sorties = cur.fetchall()

        # Moyennes globales tension et IAH (hors jours vélo)
        cur.execute("SELECT AVG(systolic) as sys, AVG(diastolic) as dia FROM mesures")
        glob_tension = cur.fetchone()
        cur.execute("SELECT AVG(iah) as iah FROM sommeil_ppc WHERE iah IS NOT NULL")
        glob_iah = cur.fetchone()
        cur.execute("SELECT AVG(poids) as poids FROM poids_historique")
        glob_poids = cur.fetchone()

        globales = {
            "sys":   round(glob_tension['sys'],  1) if glob_tension['sys']  else None,
            "dia":   round(glob_tension['dia'],  1) if glob_tension['dia']  else None,
            "iah":   round(glob_iah['iah'],      2) if glob_iah['iah']      else None,
            "poids": round(glob_poids['poids'],  1) if glob_poids['poids']  else None,
        }

        rows = []
        for s in sorties:
            date_sortie = s['date']
            # Date cible selon délai
            dt_cible = (_dt.strptime(date_sortie, "%Y-%m-%d") + _td(days=delai)).strftime("%Y-%m-%d")
            dt_j1    = (_dt.strptime(date_sortie, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")
            dt_j2    = (_dt.strptime(date_sortie, "%Y-%m-%d") + _td(days=2)).strftime("%Y-%m-%d")

            # Tension jour cible
            cur.execute("""
                SELECT AVG(systolic) as sys, AVG(diastolic) as dia
                FROM mesures WHERE DATE(timestamp) = ?
            """, (dt_cible,))
            t = cur.fetchone()

            # Tension J+1 et J+2
            cur.execute("SELECT AVG(systolic) as sys FROM mesures WHERE DATE(timestamp) = ?", (dt_j1,))
            t_j1 = cur.fetchone()
            cur.execute("SELECT AVG(systolic) as sys FROM mesures WHERE DATE(timestamp) = ?", (dt_j2,))
            t_j2 = cur.fetchone()

            # IAH jour cible
            cur.execute("SELECT iah FROM sommeil_ppc WHERE date = ?", (dt_cible,))
            i = cur.fetchone()
            cur.execute("SELECT iah FROM sommeil_ppc WHERE date = ?", (dt_j1,))
            i_j1 = cur.fetchone()
            cur.execute("SELECT iah FROM sommeil_ppc WHERE date = ?", (dt_j2,))
            i_j2 = cur.fetchone()

            # Poids J+1
            cur.execute("""
                SELECT poids FROM poids_historique
                WHERE DATE(mesure_le) = ? ORDER BY mesure_le DESC LIMIT 1
            """, (dt_j1,))
            p_j1 = cur.fetchone()

            row = {
                "date":      date_sortie,
                "duree":     s['duree_sec'],
                "dist":      s['distance_m'],
                "deniv":     s['elevation_gain'],
                "fc":        s['hr_moy'],
                "sys":       round(t['sys'],  1) if t and t['sys']  else None,
                "dia":       round(t['dia'],  1) if t and t['dia']  else None,
                "sys_j1":    round(t_j1['sys'], 1) if t_j1 and t_j1['sys'] else None,
                "sys_j2":    round(t_j2['sys'], 1) if t_j2 and t_j2['sys'] else None,
                "iah":       round(i['iah'],  2) if i and i['iah']   else None,
                "iah_j1":    round(i_j1['iah'], 2) if i_j1 and i_j1['iah'] else None,
                "iah_j2":    round(i_j2['iah'], 2) if i_j2 and i_j2['iah'] else None,
                "poids_j1":  round(p_j1['poids'], 1) if p_j1 else None,
            }
            rows.append(row)

        # Moyennes sur les jours avec données
        def moy_rows(key):
            vals = [r[key] for r in rows if r[key] is not None]
            return round(sum(vals)/len(vals), 2) if vals else None

        moyennes = {
            "sys":   moy_rows("sys"),
            "dia":   moy_rows("dia"),
            "iah":   moy_rows("iah"),
            "poids": moy_rows("poids_j1"),
        }

        conn.close()
        return jsonify({"ok": True, "rows": rows, "moyennes": moyennes, "globales": globales})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/correlations")
def api_correlations():
    """Retourne les données croisées poids / tension / IAH par date."""
    from datetime import datetime
    db_path = get_db_path()
    if not db_path:
        return jsonify({"ok": False, "error": "Base non configurée"}), 400

    date_start = request.args.get("date_start")
    date_end   = request.args.get("date_end")

    try:
        with hilo_db.get_conn(db_path) as conn:
            # ── Poids : une ligne par jour ────────────────────────────────
            w_where = ""
            w_args  = []
            if date_start: w_where += " AND date(mesure_le) >= ?"; w_args.append(date_start)
            if date_end:   w_where += " AND date(mesure_le) <= ?"; w_args.append(date_end)
            poids_rows = conn.execute(
                f"SELECT date(mesure_le) AS jour, poids, masse_grasse, masse_musculaire "
                f"FROM poids_historique WHERE poids IS NOT NULL {w_where} "
                f"ORDER BY jour",
                w_args
            ).fetchall()

            # ── Tension : moyenne par jour ────────────────────────────────
            t_where = ""
            t_args  = []
            if date_start: t_where += " AND date(timestamp) >= ?"; t_args.append(date_start)
            if date_end:   t_where += " AND date(timestamp) <= ?"; t_args.append(date_end)
            tension_rows = conn.execute(
                f"SELECT date(timestamp) AS jour, "
                f"ROUND(AVG(systolic),1) AS sys, ROUND(AVG(diastolic),1) AS dia, "
                f"ROUND(AVG(heartrate),1) AS fc "
                f"FROM mesures WHERE systolic IS NOT NULL {t_where} "
                f"GROUP BY jour ORDER BY jour",
                t_args
            ).fetchall()

        # ── IAH + durée PPC/Withings par date ────────────────────────────
        sommeil_data = sommeil_db.get_sommeil_data(db_path, date_start, date_end)
        iah_map = {}
        for s in sommeil_data:
            d = s.get("date")
            if d:
                iah_map[d] = {
                    "iah_ppc":        s.get("iah"),
                    "iah_withings":   s.get("iah_withings"),
                    "duree_ppc":      s.get("duree_min"),
                    "duree_withings": s.get("duree_w_min"),
                }

        # ── Oscar sessions : heure coucher/réveil, durée réelle, nb apnées ──
        oscar_map = {}
        try:
            with hilo_db.get_conn(db_path) as conn:
                os_where = ""
                os_args  = []
                if date_start: os_where += " AND date >= ?"; os_args.append(date_start)
                if date_end:   os_where += " AND date <= ?"; os_args.append(date_end)
                exists = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='oscar_sessions'"
                ).fetchone()
                if exists:
                    os_rows = conn.execute(
                        f"SELECT date, debut_ts, fin_ts, duree_min, "
                        f"n_ca, n_hypo, n_obs, n_total, "
                        f"pression_moy, pression_p95 "
                        f"FROM oscar_sessions WHERE debut_ts IS NOT NULL {os_where}",
                        os_args
                    ).fetchall()
                    import math as _math
                    for r in os_rows:
                        from datetime import datetime as _dtl
                        h_c = _dtl.fromtimestamp(r["debut_ts"]).hour +                               _dtl.fromtimestamp(r["debut_ts"]).minute / 60
                        h_r = _dtl.fromtimestamp(r["fin_ts"]).hour +                               _dtl.fromtimestamp(r["fin_ts"]).minute / 60
                        oscar_map[r["date"]] = {
                            "h_coucher":     round(h_c, 1),
                            "h_reveil":      round(h_r, 1),
                            "n_centrales":   r["n_ca"],
                            "n_hypopnees":   r["n_hypo"],
                            "n_obstructives":r["n_obs"],
                            "pression_moy":  r["pression_moy"],
                            "pression_p95":  r["pression_p95"],
                        }
        except Exception:
            pass

        # ── Index par date ────────────────────────────────────────────────
        from datetime import datetime as _dt, timedelta as _td
        poids_map   = {r["jour"]: dict(r) for r in poids_rows}
        tension_map = {r["jour"]: dict(r) for r in tension_rows}

        # Union de toutes les dates
        all_dates = sorted(set(list(poids_map) + list(tension_map) + list(iah_map)))

        points = []
        for d in all_dates:
            p = poids_map.get(d, {})
            t = tension_map.get(d, {})
            i = iah_map.get(d, {})
            if not any([p, t, i]):
                continue
            # Tension du jour courant
            sys_v = t.get("sys")
            dia_v = t.get("dia")
            fc_v  = t.get("fc")
            # Si pas de tension ce jour, chercher le lendemain
            # (nuit PPC → tension du matin suivant)
            if sys_v is None and i.get("iah_ppc") is not None:
                try:
                    lendemain = (_dt.strptime(d, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")
                    tl = tension_map.get(lendemain, {})
                    sys_v = tl.get("sys")
                    dia_v = tl.get("dia")
                    fc_v  = tl.get("fc")
                except Exception:
                    pass
            o = oscar_map.get(d, {})
            points.append({
                "date":            d,
                "poids":           p.get("poids"),
                "masse_grasse":    p.get("masse_grasse"),
                "masse_musculaire":p.get("masse_musculaire"),
                "sys":             sys_v,
                "dia":             dia_v,
                "fc":              fc_v,
                "iah_ppc":         i.get("iah_ppc"),
                "iah_withings":    i.get("iah_withings"),
                "duree_ppc":       i.get("duree_ppc"),
                "duree_withings":  i.get("duree_withings"),
                "jour_semaine":    _dt.strptime(d, "%Y-%m-%d").weekday() if d else None,
                # Données OSCAR enrichies
                "h_coucher":       o.get("h_coucher"),
                "h_reveil":        o.get("h_reveil"),
                "n_centrales":     o.get("n_centrales"),
                "n_hypopnees":     o.get("n_hypopnees"),
                "n_obstructives":  o.get("n_obstructives"),
                "pression_moy":    o.get("pression_moy"),
                "pression_p95":    o.get("pression_p95"),
            })

        return jsonify({"ok": True, "points": points})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Arrêt propre du serveur
# ─────────────────────────────────────────────────────────────────────────────

import threading as _threading
import time as _time

_last_heartbeat   = _time.time()
_heartbeat_timer  = None
_HEARTBEAT_DELAY  = 120  # secondes sans heartbeat avant extinction (2 minutes)
_meteo_velo_sync  = {"status": None, "msg": None}  # résultat sync météo vélo

def _schedule_shutdown():
    """Lance un timer qui éteint Flask si le heartbeat s'arrête."""
    global _heartbeat_timer
    if _heartbeat_timer:
        _heartbeat_timer.cancel()
    _heartbeat_timer = _threading.Timer(_HEARTBEAT_DELAY, _do_shutdown)
    _heartbeat_timer.daemon = True
    _heartbeat_timer.start()

def _do_shutdown():
    import os, signal, platform
    print("\n[Hilo] Navigateur ferme — arret du serveur.")
    if platform.system() == "Windows":
        os._exit(0)
    else:
        os.kill(os.getpid(), signal.SIGTERM)

# ─────────────────────────────────────────────────────────────────────────────
# Activités Vélo
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/activites/meteo", methods=["POST"])
def api_activites_meteo():
    """Récupère la météo Open-Meteo pour une plage horaire donnée."""
    import requests as _req
    from datetime import datetime as _dt, timedelta as _td

    body = request.get_json() or {}
    date        = body.get("date", "")          # YYYY-MM-DD
    heure_debut = body.get("heure_debut", "")   # HH:MM
    duree_str   = body.get("duree", "")         # HH:MM
    workout_id  = body.get("workout_id", None)  # ID sortie pour centroïde GPS
    auto_mode   = body.get("_auto", False)       # Mode auto : récupérer date/heure depuis DB

    # Mode auto : récupérer date, heure et durée depuis la DB via workout_id
    if auto_mode and workout_id:
        try:
            _db = get_db_path()
            if _db:
                from datetime import datetime as _dta
                import sqlite3 as _sq3a
                with _sq3a.connect(_db) as _ca:
                    row = _ca.execute(
                        "SELECT date, debut_ts, fin_ts FROM workouts WHERE id=?", (workout_id,)
                    ).fetchone()
                if row:
                    date = row[0]
                    _dt_deb = _dta.fromtimestamp(row[1])
                    _dt_fin = _dta.fromtimestamp(row[2])
                    heure_debut = _dt_deb.strftime("%H:%M")
                    _dur_sec = row[2] - row[1]
                    hh_auto = _dur_sec // 3600
                    mm_auto = (_dur_sec % 3600) // 60
                    ss_auto = _dur_sec % 60
                    duree_str = f"{hh_auto}:{mm_auto:02d}:{ss_auto:02d}"
        except Exception as _ea:
            return jsonify({"ok": False, "error": f"Erreur récupération sortie : {_ea}"})

    if not date or not heure_debut or not duree_str:
        return jsonify({"ok": False, "error": "Paramètres manquants"})

    try:
        hh_d, mm_d = heure_debut.split(":")
        debut_h = int(hh_d) + int(mm_d) / 60

        parts_r = duree_str.split(":")
        hh_r, mm_r = parts_r[0], parts_r[1]
        ss_r = parts_r[2] if len(parts_r) >= 3 else "0"
        duree_h = int(hh_r) + int(mm_r) / 60 + int(ss_r) / 3600
    except Exception:
        return jsonify({"ok": False, "error": "Format heure invalide"})

    # Calculer le centroïde GPS si workout_id fourni
    lat_meteo = 48.487222  # Troyes par défaut
    lon_meteo = 4.563611
    source_coords = "Troyes (défaut)"
    if workout_id:
        try:
            _db = get_db_path()
            if _db:
                import sqlite3 as _sq3, math as _math
                with _sq3.connect(_db) as _c:
                    pts = _c.execute(
                        "SELECT lat, lon FROM workouts_gps WHERE workout_id=?", (workout_id,)
                    ).fetchall()
                if pts:
                    lat_meteo = round(sum(p[0] for p in pts) / len(pts), 6)
                    lon_meteo = round(sum(p[1] for p in pts) / len(pts), 6)
                    source_coords = f"Centroïde GPS ({len(pts)} pts)"
        except Exception:
            pass  # Fallback sur Troyes si erreur

    try:
        resp = _req.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude":  lat_meteo,
            "longitude": lon_meteo,
            "start_date": date,
            "end_date":   date,
            "hourly": "temperature_2m,apparent_temperature,windspeed_10m,windgusts_10m,precipitation,winddirection_10m",
            "timezone": "Europe/Paris",
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    hourly    = data.get("hourly", {})
    times     = hourly.get("time", [])
    temps     = hourly.get("temperature_2m", [])
    ressentis = hourly.get("apparent_temperature", [])
    vents     = hourly.get("windspeed_10m", [])
    rafales   = hourly.get("windgusts_10m", [])
    pluies    = hourly.get("precipitation", [])
    dirs      = hourly.get("winddirection_10m", [])

    # Heures couvertes par la sortie
    heures_sortie = set()
    h = debut_h
    fin = debut_h + duree_h
    while h < fin:
        heures_sortie.add(int(h))
        h += 1
    if not heures_sortie:
        heures_sortie.add(int(debut_h))

    vals = {"temp": [], "ressenti": [], "vent": [], "rafales": [], "pluie": [], "dir": []}
    for i, t in enumerate(times):
        heure_t = int(t.split("T")[1].split(":")[0])
        if heure_t in heures_sortie:
            if i < len(temps)     and temps[i]     is not None: vals["temp"].append(temps[i])
            if i < len(ressentis) and ressentis[i] is not None: vals["ressenti"].append(ressentis[i])
            if i < len(vents)     and vents[i]     is not None: vals["vent"].append(vents[i])
            if i < len(rafales)   and rafales[i]   is not None: vals["rafales"].append(rafales[i])
            if i < len(pluies)    and pluies[i]    is not None: vals["pluie"].append(pluies[i])
            if i < len(dirs)      and dirs[i]       is not None: vals["dir"].append(dirs[i])

    def moy(lst): return round(sum(lst) / len(lst), 1) if lst else None

    def deg_vers_cardinal(deg):
        if deg is None: return None
        deg = deg % 360
        dirs = [
            (0,"N"),(22.5,"NNE"),(45,"NE"),(67.5,"ENE"),
            (90,"E"),(112.5,"ESE"),(135,"SE"),(157.5,"SSE"),
            (180,"S"),(202.5,"SSO"),(225,"SO"),(247.5,"OSO"),
            (270,"O"),(292.5,"ONO"),(315,"NO"),(337.5,"NNO"),(360,"N"),
        ]
        cardinal = "N"
        for seuil, nom in dirs:
            if deg >= seuil: cardinal = nom
        return cardinal

    import math as _math_vent
    if vals["dir"]:
        sin_s = sum(_math_vent.sin(_math_vent.radians(d)) for d in vals["dir"])
        cos_s = sum(_math_vent.cos(_math_vent.radians(d)) for d in vals["dir"])
        moy_dir = round(_math_vent.degrees(_math_vent.atan2(sin_s, cos_s)) % 360, 1)
    else:
        moy_dir = None
    meteo = {
        "temp":    moy(vals["temp"]),
        "ressenti":moy(vals["ressenti"]),
        "vent":    moy(vals["vent"]),
        "rafales": round(max(vals["rafales"]), 1) if vals["rafales"] else None,
        "pluie":   round(sum(vals["pluie"]), 1) if vals["pluie"] else 0.0,
        "vent_dir": deg_vers_cardinal(moy_dir),
        "vent_dir_deg": moy_dir,
    }
    return jsonify({"ok": True, "meteo": meteo, "source_coords": source_coords})


@app.route("/api/activites/velo", methods=["GET"])
def api_activites_velo_get():
    """Retourne la liste des sorties vélo."""
    db = get_db_path()
    if not db:
        return jsonify({"ok": False, "error": "Base non configurée"})
    try:
        import sqlite3 as _sq
        conn = _sq.connect(str(db))
        conn.row_factory = _sq.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, date, debut_ts, fin_ts, duree_sec, distance_m,
                   hr_moy, elevation_gain,
                   meteo_temp, meteo_ressenti, meteo_vent, meteo_rafales, meteo_pluie, meteo_vent_dir, meteo_vent_deg,
                   note, importe_le
            FROM workouts
            WHERE categorie = 'Vélo'
            ORDER BY date DESC, debut_ts DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "sorties": rows})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/activites/velo", methods=["POST"])
def api_activites_velo_post():
    """Enregistre une nouvelle sortie vélo."""
    from datetime import datetime as _dt
    import sqlite3 as _sq

    body = request.get_json() or {}
    date       = body.get("date", "")        # YYYY-MM-DD
    heure_deb  = body.get("heure_debut", "") # HH:MM
    duree_str  = body.get("duree", "")       # HH:MM
    distance   = body.get("distance", None)
    meteo      = body.get("meteo", None)

    if not date or not heure_deb or not duree_str:
        return jsonify({"ok": False, "error": "Paramètres manquants"})

    try:
        hh_d, mm_d = heure_deb.split(":")
        hh_r, mm_r = duree_str.split(":")[:2]
        ss_r = duree_str.split(":")[2] if duree_str.count(":") >= 2 else "0"
        duree_sec  = int(hh_r) * 3600 + int(mm_r) * 60 + int(ss_r)

        debut_dt = _dt.strptime(f"{date} {hh_d}:{mm_d}", "%Y-%m-%d %H:%M")
        from datetime import timedelta as _td
        fin_dt   = debut_dt + _td(seconds=duree_sec)
        debut_ts = int(debut_dt.timestamp())
        fin_ts   = int(fin_dt.timestamp())
    except Exception as e:
        return jsonify({"ok": False, "error": f"Format invalide : {e}"})

    distance_m = float(str(distance).replace(",", ".")) * 1000 if distance else None
    fc         = float(body.get("fc")) if body.get("fc") else None
    denivele   = float(body.get("denivele")) if body.get("denivele") else None

    db = get_db_path()
    if not db:
        return jsonify({"ok": False, "error": "Base non configurée"})

    try:
        conn = _sq.connect(str(db))
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO workouts
              (date, withings_id, categorie, debut_ts, fin_ts, duree_sec, distance_m,
               hr_moy, elevation_gain,
               meteo_temp, meteo_ressenti, meteo_vent, meteo_rafales, meteo_pluie, meteo_vent_dir, meteo_vent_deg,
               note, importe_le)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            date, None, "Vélo", debut_ts, fin_ts, duree_sec, distance_m,
            fc, denivele,
            meteo.get("temp")      if meteo else None,
            meteo.get("ressenti")  if meteo else None,
            meteo.get("vent")      if meteo else None,
            meteo.get("rafales")   if meteo else None,
            meteo.get("pluie")     if meteo else None,
            meteo.get("vent_dir")     if meteo else None,
            meteo.get("vent_dir_deg") if meteo else None,
            body.get("note", ""),
            _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/activites/gps/heatmap")
def api_activites_gps_heatmap():
    """Retourne tous les points GPS pour la heatmap."""
    import sqlite3 as _sq
    db = get_db_path()
    if not db:
        return jsonify({"ok": False, "error": "Base non configurée"})
    try:
        conn = _sq.connect(str(db))
        cur  = conn.cursor()
        # Sous-échantillonner : 1 point sur 5 pour alléger
        cur.execute("""
            SELECT lat, lon
            FROM workouts_gps
            WHERE workout_id IS NOT NULL
              AND lat IS NOT NULL AND lon IS NOT NULL
              AND (rowid % 5 = 0)
            ORDER BY ts
        """)
        rows = cur.fetchall()

        # Compter les sorties distinctes
        cur.execute("""
            SELECT COUNT(DISTINCT workout_id)
            FROM workouts_gps
            WHERE workout_id IS NOT NULL
        """)
        n_sorties = cur.fetchone()[0]
        conn.close()

        if not rows:
            return jsonify({"ok": True, "points": [], "n_points": 0, "n_sorties": 0})

        # Calculer la densité par cellule (grille ~50m)
        from collections import defaultdict
        import math as _math
        grid = defaultdict(int)
        for lat, lon in rows:
            # Arrondir à ~50m (4 décimales ≈ 11m, 3 décimales ≈ 111m)
            key = (round(lat, 4), round(lon, 4))
            grid[key] += 1

        if not grid:
            return jsonify({"ok": True, "points": [], "n_points": 0, "n_sorties": 0})

        # Normalisation avec racine carrée pour mieux étaler les contrastes
        max_val = max(grid.values())
        points = [[k[0], k[1], _math.sqrt(v / max_val)] for k, v in grid.items()]

        # Bounds
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

        return jsonify({
            "ok":            True,
            "points":        points,
            "n_points":      len(rows),
            "n_sorties":     n_sorties,
            "max_intensity": 1.0,
            "bounds":        bounds,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/activites/velo/<int:sortie_id>/carte")
def api_activites_velo_carte(sortie_id):
    """Retourne les données d'une sortie + trace GPS pour la carte."""
    import sqlite3 as _sq
    db = get_db_path()
    if not db:
        return jsonify({"ok": False, "error": "Base non configurée"})
    try:
        conn = _sq.connect(str(db))
        conn.row_factory = _sq.Row
        cur = conn.cursor()

        # Données de la sortie
        cur.execute("""
            SELECT w.*, g.distance_gps, g.denivele_gps, g.n_points
            FROM workouts w
            LEFT JOIN workouts_gps_stats g ON g.workout_id = w.id
            WHERE w.id = ?
        """, (sortie_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Sortie introuvable"})

        sortie = dict(row)

        # Points GPS avec distance cumulée
        cur.execute("""
            SELECT ts, lat, lon, alt
            FROM workouts_gps
            WHERE workout_id = ?
            ORDER BY ts ASC
        """, (sortie_id,))
        pts_raw = cur.fetchall()
        conn.close()

        # Calculer distance cumulée pour le profil
        import math as _math
        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000
            p = _math.pi / 180
            a = (0.5 - _math.cos((lat2-lat1)*p)/2
                 + _math.cos(lat1*p)*_math.cos(lat2*p)*(1-_math.cos((lon2-lon1)*p))/2)
            return 2*R*_math.asin(_math.sqrt(a))

        points = []
        dist_cum = 0.0
        prev = None
        for pt in pts_raw:
            if prev:
                d = haversine(prev['lat'], prev['lon'], pt['lat'], pt['lon'])
                if d < 200:
                    dist_cum += d
            points.append({
                "ts":       pt['ts'],
                "lat":      pt['lat'],
                "lon":      pt['lon'],
                "alt":      pt['alt'],
                "dist_cum": round(dist_cum, 1)
            })
            prev = pt

        return jsonify({
            "ok":       True,
            "sortie":   sortie,
            "points":   points,
            "deniv_gps": sortie.get('denivele_gps'),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/activites/velo/<int:sortie_id>", methods=["DELETE"])
def api_activites_velo_delete(sortie_id):
    """Supprime une sortie vélo."""
    import sqlite3 as _sq
    db = get_db_path()
    if not db:
        return jsonify({"ok": False, "error": "Base non configurée"})
    try:
        conn = _sq.connect(str(db))
        conn.execute("DELETE FROM workouts WHERE id=? AND categorie='Vélo'", (sortie_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/gps/import", methods=["POST"])
def api_gps_import():
    """Import des fichiers GPS Withings (latitude, longitude, altitude)."""
    import sqlite3 as _sq
    import csv as _csv
    import io as _io
    import re as _re
    from datetime import datetime as _dt, timezone as _tz

    db = get_db_path()
    if not db:
        return jsonify({"ok": False, "error": "Base non configurée"})

    if 'lat' not in request.files or 'lon' not in request.files or 'alt' not in request.files:
        return jsonify({"ok": False, "error": "Les 3 fichiers sont requis (lat, lon, alt)"})

    def parse_csv(file):
        """Parse un CSV Withings GPS → liste de (ts_unix, valeur)"""
        content = file.read().decode('utf-8')
        reader = _csv.DictReader(_io.StringIO(content))
        rows = []
        for row in reader:
            try:
                # Extraire la valeur du format [valeur]
                val_str = row['value'].strip().strip('[]')
                val = float(val_str)
                # Parser le timestamp ISO avec timezone
                ts_str = row['start'].strip()
                # Convertir en timestamp unix
                ts_str_clean = _re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', ts_str)
                try:
                    dt = _dt.strptime(ts_str_clean, "%Y-%m-%dT%H:%M:%S%z")
                except ValueError:
                    dt = _dt.strptime(ts_str_clean, "%Y-%m-%dT%H:%M:%S")
                    dt = dt.replace(tzinfo=_tz.utc)
                rows.append((int(dt.timestamp()), val))
            except Exception:
                continue
        return rows

    try:
        lat_data = parse_csv(request.files['lat'])
        lon_data = parse_csv(request.files['lon'])
        alt_data = parse_csv(request.files['alt'])
    except Exception as e:
        return jsonify({"ok": False, "error": f"Erreur lecture CSV : {e}"})

    # Construire un dict ts → valeurs
    lat_dict = {ts: v for ts, v in lat_data}
    lon_dict = {ts: v for ts, v in lon_data}
    alt_dict = {ts: v for ts, v in alt_data}

    # Points complets (lat + lon obligatoires, alt optionnel)
    all_ts = sorted(set(lat_dict.keys()) & set(lon_dict.keys()))

    now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _sq.connect(str(db))
    cur  = conn.cursor()

    # Insérer les nouveaux points GPS sans écraser les existants
    # (INSERT OR IGNORE pour éviter les doublons sur ts)
    batch = []
    for ts in all_ts:
        lat = lat_dict[ts]
        lon = lon_dict[ts]
        alt = alt_dict.get(ts)
        batch.append((None, ts, lat, lon, alt, now_str))

    cur.executemany("""
        INSERT OR IGNORE INTO workouts_gps (workout_id, ts, lat, lon, alt, importe_le)
        VALUES (?,?,?,?,?,?)
    """, batch)
    n_points = cur.rowcount  # points réellement ajoutés

    # Récupérer les sorties vélo pour calculer les stats
    cur.execute("""
        SELECT id, date, debut_ts, fin_ts, duree_sec
        FROM workouts
        WHERE categorie = 'Vélo' AND debut_ts IS NOT NULL AND fin_ts IS NOT NULL
        ORDER BY debut_ts
    """)
    sorties = cur.fetchall()

    import math as _math

    def haversine(lat1, lon1, lat2, lon2):
        """Distance en mètres entre deux points GPS."""
        R = 6371000
        p = _math.pi / 180
        a = (0.5 - _math.cos((lat2-lat1)*p)/2
             + _math.cos(lat1*p) * _math.cos(lat2*p) * (1-_math.cos((lon2-lon1)*p))/2)
        return 2 * R * _math.asin(_math.sqrt(a))

    n_sorties  = 0
    n_stats    = 0
    sorties_info = []  # liste des sorties traitées avec date/id pour météo auto

    for sid, date, debut_ts, fin_ts, duree_sec in sorties:
        # Marge de 5 min de chaque côté
        marge = 300
        pts = [(ts, lat_dict[ts], lon_dict[ts], alt_dict.get(ts))
               for ts in all_ts
               if debut_ts - marge <= ts <= fin_ts + marge]

        if len(pts) < 2:
            continue

        n_sorties += 1
        sorties_info.append({"id": sid, "date": date})

        # Lier les points GPS à cette sortie
        ts_set = tuple(ts for ts, *_ in pts)
        cur.execute(
            f"UPDATE workouts_gps SET workout_id=? WHERE ts IN ({','.join('?'*len(ts_set))})",
            (sid, *ts_set)
        )

        # Calculer distance
        dist_total = 0.0
        prev = pts[0]
        for curr in pts[1:]:
            d = haversine(prev[1], prev[2], curr[1], curr[2])
            dt_sec = max(curr[0] - prev[0], 1)
            if d / dt_sec < 200:
                dist_total += d
            prev = curr

        # Lissage altitude : moyenne glissante sur 20 points
        window = 20
        alts_brutes = [p[3] for p in pts]
        alts = []
        for i in range(len(alts_brutes)):
            voisins = [alts_brutes[j] for j in range(max(0,i-window//2), min(len(alts_brutes),i+window//2+1)) if alts_brutes[j] is not None]
            alts.append(sum(voisins)/len(voisins) if voisins else None)

        # Dénivelé+ par méthode min/max locaux, seuil 2m
        deniv_plus = 0.0
        seuil = 2.0
        alt_min = None
        alt_prev = None

        for alt in alts:
            if alt is None:
                continue
            if alt_prev is None:
                alt_prev = alt
                alt_min = alt
                continue
            if alt >= alt_prev:
                pass
            else:
                gain = alt_prev - alt_min
                if gain >= seuil:
                    deniv_plus += gain
                alt_min = alt
            alt_prev = alt

        # Dernière montée éventuelle
        if alt_prev is not None and alt_min is not None:
            gain = alt_prev - alt_min
            if gain >= seuil:
                deniv_plus += gain

        vit_moy = (dist_total / 1000) / (duree_sec / 3600) if duree_sec > 0 else None

        cur.execute("""
            INSERT INTO workouts_gps_stats
              (workout_id, date, debut_ts, fin_ts, n_points,
               distance_gps, denivele_gps, vit_moy_gps, calcule_le)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (sid, date, debut_ts, fin_ts, len(pts),
              round(dist_total, 1), round(deniv_plus, 1),
              round(vit_moy, 2) if vit_moy else None, now_str))
        n_stats += 1

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "n_points":    n_points,
        "n_sorties":   n_sorties,
        "n_stats":     n_stats,
        "sorties_info": sorties_info,
    })


@app.route("/api/shutdown-warning")
def api_shutdown_warning():
    import time as _t
    remaining = _HEARTBEAT_DELAY - (_t.time() - _last_heartbeat)
    return jsonify({"warning": remaining < 30, "remaining": round(remaining, 1)})


@app.route("/api/heartbeat", methods=["GET", "POST"])
def api_heartbeat():
    global _last_heartbeat, _heartbeat_timer
    _last_heartbeat = _time.time()
    if _heartbeat_timer:
        _heartbeat_timer.cancel()
    _schedule_shutdown()
    return jsonify({"ok": True})

@app.route("/api/shutdown", methods=["GET", "POST"])
def api_shutdown():
    def _stop():
        _time.sleep(0.3)
        _do_shutdown()
    _threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"ok": True, "message": "Arrêt en cours…"})


# ─────────────────────────────────────────────────────────────────────────────
# Lancement
# ─────────────────────────────────────────────────────────────────────────────
def _sync_meteo_velo(db_path):
    """
    Au démarrage : complète automatiquement la météo des sorties vélo
    dont les données sont manquantes et dont la date est > 2 jours (archives dispo).
    """
    global _meteo_velo_sync
    import sqlite3 as _sq
    import requests as _req
    import time as _time
    from datetime import datetime as _dt, timedelta as _td

    conn = _sq.connect(str(db_path))
    conn.row_factory = _sq.Row
    cur  = conn.cursor()

    # Toutes les sorties vélo sans météo et avec GPS
    cur.execute("""
        SELECT w.id, w.date, w.debut_ts, w.duree_sec
        FROM workouts w
        WHERE w.categorie = 'Vélo'
          AND w.debut_ts IS NOT NULL
          AND w.duree_sec IS NOT NULL
          AND w.meteo_temp IS NULL
          AND EXISTS (SELECT 1 FROM workouts_gps g WHERE g.workout_id = w.id LIMIT 1)
        ORDER BY w.date DESC
    """)
    sorties = cur.fetchall()

    if not sorties:
        print("[Démarrage] Météo vélo : toutes les sorties sont à jour")
        _meteo_velo_sync = {"status": "ok", "msg": "✅ Météo vélo à jour"}
        conn.close()
        return

    print(f"[Démarrage] Météo vélo : {len(sorties)} sortie(s) sans météo à compléter")

    def deg_vers_cardinal(deg):
        if deg is None: return None
        deg = deg % 360
        dirs = [
            (0,"N"),(22.5,"NNE"),(45,"NE"),(67.5,"ENE"),
            (90,"E"),(112.5,"ESE"),(135,"SE"),(157.5,"SSE"),
            (180,"S"),(202.5,"SSO"),(225,"SO"),(247.5,"OSO"),
            (270,"O"),(292.5,"ONO"),(315,"NO"),(337.5,"NNO"),(360,"N"),
        ]
        cardinal = "N"
        for seuil, nom in dirs:
            if deg >= seuil: cardinal = nom
        return cardinal

    maj = 0
    pas_encore_dispo = 0
    for s in sorties:
        dt       = _dt.fromtimestamp(s['debut_ts'])
        date_iso = dt.strftime("%Y-%m-%d")
        debut_h  = dt.hour + dt.minute / 60
        duree_h  = s['duree_sec'] / 3600

        # Heures couvertes
        heures = set()
        h = debut_h
        while h < debut_h + duree_h:
            heures.add(int(h))
            h += 1
        if not heures:
            heures.add(int(debut_h))

        try:
            # Centroïde GPS pour cette sortie
            _pts_gps = cur.execute(
                "SELECT lat, lon FROM workouts_gps WHERE workout_id=?", (s['id'],)
            ).fetchall()
            if _pts_gps:
                _lat = round(sum(p[0] for p in _pts_gps) / len(_pts_gps), 6)
                _lon = round(sum(p[1] for p in _pts_gps) / len(_pts_gps), 6)
            else:
                _lat, _lon = 48.487222, 4.563611  # Troyes par défaut

            resp = _req.get("https://archive-api.open-meteo.com/v1/archive", params={
                "latitude": _lat, "longitude": _lon,
                "start_date": date_iso, "end_date": date_iso,
                "hourly": "temperature_2m,apparent_temperature,windspeed_10m,windgusts_10m,precipitation,winddirection_10m",
                "timezone": "Europe/Paris",
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            hourly = data.get("hourly", {})
            times  = hourly.get("time", [])

            def extraire(key):
                vals = hourly.get(key, [])
                return [vals[i] for i, t in enumerate(times)
                        if int(t.split("T")[1].split(":")[0]) in heures
                        and i < len(vals) and vals[i] is not None]

            t_  = extraire("temperature_2m")
            r_  = extraire("apparent_temperature")
            v_  = extraire("windspeed_10m")
            g_  = extraire("windgusts_10m")
            p_  = extraire("precipitation")
            d_  = extraire("winddirection_10m")

            def moy(lst): return round(sum(lst)/len(lst), 1) if lst else None

            # Si toutes les valeurs sont nulles, données pas encore dispo sur le serveur
            if not t_ and not v_:
                print(f"[Démarrage] Météo vélo : ID {s['id']} {s['date']} ⏳ pas encore disponible")
                pas_encore_dispo += 1
                _time.sleep(0.3)
                continue

            moy_dir = moy(d_)
            cur.execute("""
                UPDATE workouts SET
                    meteo_temp     = ?,
                    meteo_ressenti = ?,
                    meteo_vent     = ?,
                    meteo_rafales  = ?,
                    meteo_pluie    = ?,
                    meteo_vent_dir = ?,
                    meteo_vent_deg = ?
                WHERE id = ?
            """, (
                moy(t_), moy(r_), moy(v_),
                round(max(g_), 1) if g_ else None,
                round(sum(p_), 1) if p_ else 0.0,
                deg_vers_cardinal(moy_dir),
                moy_dir,
                s['id']
            ))
            print(f"[Démarrage] Météo vélo : ID {s['id']} {s['date']} ✅")
            maj += 1
            _time.sleep(0.3)
        except Exception as e:
            print(f"[Démarrage] Météo vélo : ID {s['id']} {s['date']} ❌ {e}")

    conn.commit()
    conn.close()
    print(f"[Démarrage] Météo vélo : {maj}/{len(sorties)} mise(s) à jour, {pas_encore_dispo} en attente serveur")

    msg_parts = []
    if maj > 0:
        msg_parts.append(f"✅ {maj} sortie(s) météo synchronisée(s)")
    if pas_encore_dispo > 0:
        msg_parts.append(f"⏳ {pas_encore_dispo} sortie(s) — météo pas encore disponible sur le serveur")

    if msg_parts:
        _meteo_velo_sync = {
            "status": "updated" if maj > 0 else "pending",
            "msg": " · ".join(msg_parts)
        }
    else:
        _meteo_velo_sync = {"status": "ok", "msg": "✅ Météo vélo à jour"}


if __name__ == "__main__":
    # Démarrer le timer heartbeat — 30s de grâce pour ouvrir le navigateur
    _heartbeat_timer = _threading.Timer(90, _schedule_shutdown)  # 90s de grâce au démarrage
    _heartbeat_timer.daemon = True
    _heartbeat_timer.start()

    # Initialiser/migrer la DB existante au démarrage
    _db = get_db_path()
    if _db and Path(_db).exists():
        try:
            hilo_db.init_db(_db)
        except Exception as _e:
            print(f"[Démarrage] init_db : {_e}")
        # Appel explicite de migrate_db pour les bases déjà existantes
        try:
            import sqlite3 as _sqlite3
            with _sqlite3.connect(str(_db)) as _conn:
                _conn.row_factory = _sqlite3.Row
                hilo_db.migrate_db(_conn)
        except Exception as _e:
            print(f"[Démarrage] migrate_db : {_e}")
        # Sync automatique Withings (poids + sleep) — un seul refresh token
        try:
            _tok, _err = _refresh_withings_token(_db)
            if _tok:
                _rp = _sync_withings_poids(_db, access_token=_tok)
                _rs = _sync_withings_sleep(_db, access_token=_tok)
                if _rp.get("ok"):
                    print(f"[Démarrage] Withings poids : {_rp['importe']} importé(s), {_rp['doublons']} doublon(s)")
                else:
                    print(f"[Démarrage] Withings poids : {_rp.get('error')}")
                if _rs.get("ok"):
                    print(f"[Démarrage] Withings sleep : {_rs['importe']} importé(s), {_rs['mis_a_jour']} maj, {_rs['ignores']} ignoré(s)")
                else:
                    print(f"[Démarrage] Withings sleep : {_rs.get('error')}")
            else:
                print(f"[Démarrage] Withings ignoré : {_err}")
        except Exception as _e:
            print(f"[Démarrage] Withings erreur : {_e}")

        # Mise à jour automatique météo des sorties vélo sans données
        try:
            print("[Démarrage] Météo vélo : vérification en cours...")
            _sync_meteo_velo(_db)
        except Exception as _e:
            print(f"[Démarrage] Météo vélo erreur : {_e}")

    port = int(os.environ.get("HILO_PORT", 5050))
    app.run(host="127.0.0.1", port=port, debug=False)
