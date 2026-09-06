"""
hilo_core.py — Logique extraction PDF + gestion hilo.csv
Sans aucune dépendance Tkinter/UI — utilisable par Flask ou CLI
"""

import pdfplumber
import pandas as pd
from datetime import datetime
import re
from pathlib import Path
import os

# ── Parsing dates françaises ──────────────────────────────────────────────────
MOIS_MAP = {
    "janvier":"01","février":"02","fevrier":"02","mars":"03","avril":"04",
    "mai":"05","juin":"06","juillet":"07","août":"08","aout":"08",
    "septembre":"09","octobre":"10","novembre":"11","décembre":"12","decembre":"12"
}

def parse_date_fr(day, month, year, hour, minute):
    mois  = MOIS_MAP.get(month.lower(), "01")
    annee = "20" + year if len(year) == 2 else year
    return f"{annee}-{mois}-{day.zfill(2)}T{hour}:{minute}"

def parse_line_zones(line):
    line = line.strip()
    rows = []
    pattern = re.compile(r'(\d{1,2}) (\w+), (\d{2}) (\d{2}):(\d{2}) (\d+) (\d+) (\d+)')
    for m in pattern.findall(line):
        day, month, year, hour, minute, sys_val, dia, fc = m
        rows.append([parse_date_fr(day, month, year, hour, minute), sys_val, dia, fc])
    return rows

# ── Extraction PDF ────────────────────────────────────────────────────────────
def extract_pdf(pdf_path):
    """Retourne (parsed_rows, full_text, n_pages)"""
    parsed_rows, full_text = [], ""
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            full_text += text + "\n"
            for line in text.split("\n"):
                if re.search(r'\d{1,2} \w+, \d{2} \d{2}:\d{2}', line):
                    parsed_rows.extend(parse_line_zones(line))
    return parsed_rows, full_text, n_pages

def rows_to_df(parsed_rows):
    df = pd.DataFrame(parsed_rows, columns=["timestamp","systolic","diastolic","heartrate"])
    return df.sort_values("timestamp").reset_index(drop=True)

# ── Gestion hilo.csv ──────────────────────────────────────────────────────────
def inject_into_hilo(df_import, hilo_path):
    """
    Injecte df_import dans hilo.csv.
    Retourne dict: {status, created, added, already, total}
    """
    hilo_path = Path(hilo_path)
    try:
        if not hilo_path.exists():
            df_import.to_csv(hilo_path, index=False)
            return {"status":"created", "created":True,
                    "added":len(df_import), "already":0, "total":len(df_import)}

        df_central  = pd.read_csv(hilo_path)
        existing_ts = set(df_central["timestamp"].astype(str))
        df_to_add   = df_import[~df_import["timestamp"].astype(str).isin(existing_ts)]

        if df_to_add.empty:
            return {"status":"already", "created":False,
                    "added":0, "already":len(df_import), "total":len(df_central)}

        df_result = pd.concat([df_central, df_to_add], ignore_index=True)
        df_result = df_result.sort_values("timestamp").reset_index(drop=True)
        df_result.to_csv(hilo_path, index=False)
        return {"status":"updated", "created":False,
                "added":len(df_to_add), "already":len(df_import)-len(df_to_add),
                "total":len(df_result)}
    except Exception as e:
        return {"status":"error", "error":str(e)}

def save_csv_extract(parsed_rows, output_dir):
    """Sauvegarde un CSV d'extraction classique, retourne le path."""
    now = datetime.now()
    name = f"Extract_Hilo_{now.strftime('%Y-%m-%d_%Hh%M')}.csv"
    path = Path(output_dir) / name
    rows_to_df(parsed_rows).to_csv(path, index=False)
    return str(path)

def save_txt_debug(full_text, output_dir):
    """Sauvegarde le texte brut extrait du PDF."""
    now = datetime.now()
    name = f"Extract_Hilo_{now.strftime('%Y-%m-%d_%Hh%M')}_debug.txt"
    path = Path(output_dir) / name
    path.write_text(full_text, encoding="utf-8")
    return str(path)

# ── Chargement hilo.csv pour le dashboard ────────────────────────────────────
def load_hilo(hilo_path):
    """
    Charge hilo.csv et retourne (records_list, meta_dict) prêts pour le dashboard.
    records_list : liste de dicts {ts, sys, dia, fc, h}
    meta_dict    : {date_min, date_max, n_total, generated}
    """
    df = pd.read_csv(hilo_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    for col in ["systolic","diastolic","heartrate"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["systolic","diastolic","heartrate"])

    records = []
    for _, row in df.iterrows():
        records.append({
            "ts":  row["timestamp"].strftime("%Y-%m-%dT%H:%M"),
            "sys": int(row["systolic"]),
            "dia": int(row["diastolic"]),
            "fc":  int(row["heartrate"]),
            "h":   row["timestamp"].hour,
        })

    meta = {
        "date_min":  df["timestamp"].min().strftime("%Y-%m-%d"),
        "date_max":  df["timestamp"].max().strftime("%Y-%m-%d"),
        "n_total":   len(df),
        "generated": datetime.now().strftime("%d/%m/%Y à %H:%M"),
    }
    return records, meta

# ── Scan dossier PDFs ─────────────────────────────────────────────────────────
def find_pdfs(folder_path):
    """Retourne la liste de tous les PDFs dans un dossier (récursif)."""
    return [
        Path(root) / f
        for root, _, files in os.walk(folder_path)
        for f in files if f.lower().endswith(".pdf")
    ]
