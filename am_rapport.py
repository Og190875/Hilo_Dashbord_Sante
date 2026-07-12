"""
am_rapport.py — Hilo (version lue via HILO_VERSION)
Rapport imprimable — un tableau par moment, jours en colonnes,
sys/dia en sous-colonnes, traitements, poids/IMC.
"""
import os
from datetime import date as _date, timedelta as _td

_ESH = {
    'optimale': {'r':53,  'g':122,'b':125,'label':'Optimale'},
    'normale':  {'r':139, 'g':194,'b':66, 'label':'Normale'},
    'elevee':   {'r':243, 'g':179,'b':83, 'label':'Élevée'},
    'hta1':     {'r':238, 'g':132,'b':51, 'label':'HTA Stade 1'},
    'hta2':     {'r':218, 'g':60, 'b':37, 'label':'HTA Stade 2'},
    'hta3':     {'r':167, 'g':34, 'b':41, 'label':'HTA Stade 3'},
}
MOMENT_CFG = {
    'MATIN': {'label':'🌅 Matin', 'bg':'#0369a1','light':'#e0f2fe','mid':'#bae6fd'},
    'SOIR':  {'label':'🌆 Soir',  'bg':'#7c3aed','light':'#ede9fe','mid':'#ddd6fe'},
    'NUIT':  {'label':'🌙 Nuit',  'bg':'#1e293b','light':'#f1f5f9','mid':'#e2e8f0'},
}
MOIS_FR  = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre']
JOURS_FR = ['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche']


def _worst_key(s, d):
    sev = ['optimale','normale','elevee','hta1','hta2','hta3']
    def ks(v): return 'optimale' if v<120 else 'normale' if v<130 else 'elevee' if v<140 else 'hta1' if v<160 else 'hta2' if v<180 else 'hta3'
    def kd(v): return 'optimale' if v<80  else 'normale' if v<85  else 'elevee' if v<90  else 'hta1' if v<100 else 'hta2' if v<110 else 'hta3'
    a, b = ks(s), kd(d)
    return a if sev.index(a) >= sev.index(b) else b

def _esh_color(k):  c=_ESH[k]; return f"rgb({c['r']},{c['g']},{c['b']})"
def _esh_light(k):  c=_ESH[k]; return f"rgba({c['r']},{c['g']},{c['b']},.15)"
def _esh_label(k):  return _ESH[k]['label']

def _cc(s, d, classif, profil):
    """Couleur globale (pire des deux) — conservee pour compatibilite."""
    if str(classif).lower()=='cible' and profil:
        cs,cd = profil.get('cible_sys',130), profil.get('cible_dia',80)
        return ('#16a34a','rgba(22,163,74,.12)') if s<=cs and d<=cd else ('#dc2626','rgba(220,38,38,.12)')
    k = _worst_key(s,d)
    return (_esh_color(k), _esh_light(k))

def _cc_split(s, d, classif, profil):
    """Couleurs séparées pour sys et dia, fond partagé sur le pire des deux.
    Retourne (tc_sys, tl_sys, tc_dia, tl_dia).
    Règle :
      - tc_sys : vert si sys <= cible_sys, rouge sinon
      - tc_dia : vert si dia <= cible_dia, rouge sinon
      - tl_sys = tl_dia : fond rouge si l'un des deux dépasse, vert sinon
    """
    if str(classif).lower()=='cible' and profil:
        cs = profil.get('cible_sys', 130)
        cd = profil.get('cible_dia', 80)
        sys_ok = (s is not None and s <= cs)
        dia_ok = (d is not None and d <= cd)
        tc_s = '#16a34a' if sys_ok else '#dc2626'
        tc_d = '#16a34a' if dia_ok else '#dc2626'
        # Fond partagé : rouge dès que l'un des deux dépasse
        tl = 'rgba(22,163,74,.12)' if (sys_ok and dia_ok) else 'rgba(220,38,38,.12)'
        return tc_s, tl, tc_d, tl
    # Mode ESH : couleur selon la pire des deux (comportement inchangé)
    k = _worst_key(s, d)
    col = _esh_color(k); lt = _esh_light(k)
    return col, lt, col, lt

def _fmt_date_long(iso):
    try:
        d = _date.fromisoformat(iso[:10])
        return f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month-1]} {d.year}"
    except: return iso or '—'

def _fmt_date_court(iso):
    """2025-08-29 -> 29 Aoû 2025"""
    MOIS_C = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']
    try:
        d = _date.fromisoformat(str(iso)[:10])
        return f"{d.day:02d} {MOIS_C[d.month-1]} {d.year}"
    except: return iso or '—'

def _fmt_heure(ts):
    try: return str(ts)[11:16]
    except: return ''

def _fmt_date_court(iso):
    """2025-08-29 -> 29 Aoû 2025"""
    MOIS_COURT = ['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc']
    try:
        d = _date.fromisoformat(str(iso)[:10])
        return f"{d.day:02d} {MOIS_COURT[d.month-1]} {d.year}"
    except: return str(iso) if iso else '—'

def _jour_label(date_debut_obj, jour):
    if date_debut_obj:
        d = date_debut_obj + _td(days=jour-1)
        return f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month-1]} {d.year}"
    return f"Jour {jour}"



def _render_comparatif(proto_prec, grille_prec):
    """Génère le bloc HTML comparatif avec le protocole précédent."""
    if not proto_prec or not grille_prec:
        return ''

    # Résultats finaux stockés dans le protocole (même source que la synthèse du rapport)
    sys_p = proto_prec.get('moy_sys')
    dia_p = proto_prec.get('moy_dia')
    fc_p  = proto_prec.get('moy_fc')
    # has_sec basé sur la présence des valeurs (pas seulement le flag)
    sys_s = proto_prec.get('moy_sys_s') or None
    dia_s = proto_prec.get('moy_dia_s') or None
    fc_s  = proto_prec.get('moy_fc_s')  or None
    has_sec = bool(sys_s and dia_s)

    if sys_p is None:
        return ''

    label_prec = proto_prec.get('label', f"Protocole #{proto_prec.get('id','')}")
    date_debut_prec = _fmt_date_long(proto_prec.get('date_debut', ''))
    # Recalculer la vraie date de fin : date_debut + n_jours - 1
    try:
        _d = _date.fromisoformat(proto_prec.get('date_debut','')[:10])
        _n = int(proto_prec.get('n_jours', 3))
        date_fin_prec = _fmt_date_long((_d + _td(days=_n-1)).isoformat())
    except Exception:
        date_fin_prec = _fmt_date_long(proto_prec.get('date_fin', ''))
    date_prec = f'{date_debut_prec} → {date_fin_prec}' if date_fin_prec else date_debut_prec

    def _cell_prec(val, val_s=None, unit='mmHg'):
        if val is None:
            return '<td style="text-align:center;padding:8px 12px;color:#94a3b8">—</td>'
        sec = f' <span style="font-size:.82rem;font-weight:400;color:#7c3aed">({val_s})</span>' if val_s is not None else ''
        txt = f'<div><span style="font-size:1.3rem;font-weight:800;color:#475569">{val}</span>{sec}</div>'
        txt += f'<div style="font-size:.6rem;color:#94a3b8">{unit}</div>'
        return f'<td style="text-align:center;padding:8px 12px;background:#f8fafc">{txt}</td>'

    sec_note = f' · bras secondaire entre ()' if has_sec else ''

    return f"""
<div style="margin-top:18px;page-break-inside:avoid">
  <div style="font-size:.78rem;font-weight:700;color:#475569;text-transform:uppercase;
              letter-spacing:.06em;border-bottom:2px solid #e2e8f0;padding-bottom:5px;margin-bottom:10px">
    📊 Comparaison avec le protocole précédent{sec_note}
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:.82rem">
    <thead>
      <tr style="background:#f1f5f9">
        <th style="padding:7px 12px;text-align:left;font-weight:600;color:#475569">Protocole</th>
        <th style="padding:7px 12px;text-align:center;font-weight:600;color:#475569">Systolique</th>
        <th style="padding:7px 12px;text-align:center;font-weight:600;color:#475569">Diastolique</th>
        <th style="padding:7px 12px;text-align:center;font-weight:600;color:#475569">FC moy.</th>

      </tr>
    </thead>
    <tbody>
      <tr style="border-bottom:1px solid #e2e8f0">
        <td style="padding:8px 12px;color:#64748b;font-size:.78rem">
          <div style="font-weight:600">{label_prec}</div>
          <div style="font-size:.68rem;color:#94a3b8">{date_prec}</div>
        </td>
        {_cell_prec(sys_p, sys_s if has_sec else None)}
        {_cell_prec(dia_p, dia_s if has_sec else None)}
        {_cell_prec(fc_p,  fc_s  if has_sec else None, 'bpm')}

      </tr>
    </tbody>
  </table>
</div>"""

def render_rapport(proto, grille, profil, traitements=None, mesures_base=None, proto_prec=None, grille_prec=None):
    import os
    from datetime import datetime
    generated     = datetime.now().strftime("%d/%m/%Y %H:%M")
    hilo_version  = os.environ.get("HILO_VERSION", "V8.6.9")
    classif     = str(proto.get('classif_mode','esh')).lower()
    moments     = proto.get('moments', ['MATIN','SOIR'])
    n_rangs     = proto.get('n_mesures_seance', 3)
    exclu_r1    = bool(proto.get('exclusion_rang1', 1))
    bras_prio   = proto.get('bras_prioritaire', 'G')
    bras_sec_actif = bool(proto.get('bras_secondaire_actif', 0))
    bras_prio_label = 'Gauche' if bras_prio == 'G' else 'Droit'
    bras_sec_label  = 'Droit'  if bras_prio == 'G' else 'Gauche'
    mesures_base    = mesures_base or {}
    n_jours     = proto.get('n_jours', 3)
    intervalle  = proto.get('intervalle_minutes', 2)
    moy_sys     = proto.get('moy_sys')
    moy_dia     = proto.get('moy_dia')
    moy_fc      = proto.get('moy_fc')
    traitements = traitements or []

    try:    dobj = _date.fromisoformat(proto.get('date_debut',''))
    except: dobj = None
    date_debut_obj = dobj  # alias utilisé dans les sections moyennes

    # ── Patient ────────────────────────────────────────────────────────────────
    p = profil or {}
    nom = f"{p.get('prenom','')} {p.get('nom','')}".strip() or '—'
    age_str = ''
    if p.get('naissance'):
        try:
            nb = _date.fromisoformat(p['naissance'])
            age_str = str((_date.today()-nb).days//365) + ' ans'
        except: pass
    sexe_str = '♂ Homme' if p.get('sexe')=='M' else '♀ Femme' if p.get('sexe')=='F' else '—'
    taille = p.get('taille'); poids = p.get('poids')
    imc_str = ''
    if taille and poids and taille>0:
        imc = round(poids/(taille/100)**2, 1)
        cat = 'Insuffisance pondérale' if imc<18.5 else 'Normal' if imc<25 else 'Surpoids' if imc<30 else 'Obésité'
        imc_str = f"{imc} ({cat})"
    cible_sys = p.get('cible_sys',130); cible_dia = p.get('cible_dia',80)

    # ── Résultat global ────────────────────────────────────────────────────────
    moy_sys_s = proto.get('moy_sys_s')
    moy_dia_s = proto.get('moy_dia_s')
    if moy_sys and moy_dia:
        gc,glight = _cc(moy_sys, moy_dia, classif, profil)  # fond global (pire des deux)
        gc_sys, _, gc_dia, _ = _cc_split(moy_sys, moy_dia, classif, profil)  # couleurs texte indep.
        gl = ('Dans la cible' if gc=='#16a34a' else 'Hors cible') if classif=='cible' else _esh_label(_worst_key(moy_sys,moy_dia))
    else:
        gc,glight,gl = '#94a3b8','#f1f5f9','Données insuffisantes'
        gc_sys = gc_dia = '#94a3b8'
    # Bras S
    if moy_sys_s and moy_dia_s:
        gc_s,_ = _cc(moy_sys_s, moy_dia_s, classif, profil)
        gl_s = ('Dans la cible' if gc_s=='#16a34a' else 'Hors cible') if classif=='cible' else _esh_label(_worst_key(moy_sys_s,moy_dia_s))
    else:
        gc_s,gl_s = None, None

    ecart_s = round(moy_sys-cible_sys,1) if moy_sys else None
    ecart_d = round(moy_dia-cible_dia,1) if moy_dia else None
    ecart_s_str = (f"{'+'if ecart_s>0 else ''}{ecart_s} vs cible {cible_sys}") if ecart_s is not None else ''
    ecart_d_str = (f"{'+'if ecart_d>0 else ''}{ecart_d} vs cible {cible_dia}") if ecart_d is not None else ''

    # ── Section patient ────────────────────────────────────────────────────────
    traite_actifs = [t for t in traitements if not t.get('date_fin')] or traitements[:5]
    trows = ''
    for t in traite_actifs:
        trows += (
            f'<tr>'
            f'<td style="padding:3px 8px;font-weight:600;color:#1e3a5f">{t.get("medicament","—")}</td>'
            f'<td style="padding:3px 8px;color:#475569">{t.get("dosage","—")}</td>'
            f'<td style="padding:3px 8px;color:#64748b">{t.get("moment","—")}</td>'
            f'<td style="padding:3px 8px;color:#64748b">{_fmt_date_court(t.get("date_debut","")) if t.get("date_debut") else "—"}</td>'
            f'</tr>'
        )
    if not trows:
        trows = '<tr><td colspan="4" style="padding:4px 8px;color:#94a3b8;font-style:italic">Aucun traitement renseigné</td></tr>'

    patient_html = (
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px">'
        # identité
        '<div style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden">'
        '<div style="background:#1e3a5f;color:#fff;padding:5px 12px;font-weight:700;font-size:.8rem">👤 Patient</div>'
        '<div style="padding:8px 12px">'
        f'<div style="font-size:.95rem;font-weight:700;color:#1e3a5f;margin-bottom:5px">{nom}</div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:3px;font-size:.75rem;color:#475569">'
        f'<div><span style="color:#94a3b8">Âge :</span> {age_str or "—"}</div>'
        f'<div><span style="color:#94a3b8">Sexe :</span> {sexe_str}</div>'
        f'<div><span style="color:#94a3b8">Taille :</span> {str(taille)+" cm" if taille else "—"}</div>'
        f'<div><span style="color:#94a3b8">Poids :</span> {str(poids)+" kg" if poids else "—"}</div>'
        f'<div><span style="color:#94a3b8">IMC :</span> {imc_str or "—"}</div>'
        f'<div><span style="color:#94a3b8">Cible :</span> {cible_sys}/{cible_dia} mmHg</div>'
        '</div></div></div>'
        # traitements
        '<div style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden">'
        '<div style="background:#1e3a5f;color:#fff;padding:5px 12px;font-weight:700;font-size:.8rem">💊 Traitements en cours</div>'
        '<table style="width:100%;border-collapse:collapse;font-size:.73rem">'
        '<thead><tr style="background:#f8fafc">'
        '<th style="padding:3px 8px;text-align:left;color:#64748b">Médicament(s)</th>'
        '<th style="padding:3px 8px;text-align:left;color:#64748b">Dosage</th>'
        '<th style="padding:3px 8px;text-align:left;color:#64748b">Moment</th>'
        '<th style="padding:3px 8px;text-align:left;color:#64748b">Depuis</th>'
        '</tr></thead>'
        f'<tbody>{trows}</tbody>'
        '</table></div>'
        '</div>'
    )

    # ══════════════════════════════════════════════════════════════════════════
    # Tableaux par moment
    # ══════════════════════════════════════════════════════════════════════════
    all_jour_sys   = {j:[] for j in range(1,n_jours+1)}
    all_jour_dia   = {j:[] for j in range(1,n_jours+1)}
    all_jour_sys_s = {j:[] for j in range(1,n_jours+1)}
    all_jour_dia_s = {j:[] for j in range(1,n_jours+1)}

    moment_tables = ''
    for moment in moments:
        mc  = MOMENT_CFG.get(moment, MOMENT_CFG['MATIN'])
        bg  = mc['bg']
        lgt = mc['light']

        # En-tête : une colonne par jour (colspan 2 = sys/dia) + colonne moy moment
        hdr_jours = ''
        hdr_sysd  = ''
        for jour in range(1, n_jours+1):
            jl = _jour_label(dobj, jour)
            hdr_jours += (
                f'<th colspan="2" style="background:{bg};color:#fff;padding:5px 10px;'
                f'text-align:center;border:1px solid rgba(255,255,255,.2);'
                f'border-right:3px solid rgba(255,255,255,.5);font-size:.75rem">{jl}</th>'
            )
            hdr_sysd += (
                f'<th style="background:{bg};filter:brightness(.75);color:#dde;padding:3px 6px;'
                f'text-align:center;border:1px solid rgba(255,255,255,.1);font-size:.68rem">Sys</th>'
                f'<th style="background:{bg};filter:brightness(.75);color:#dde;padding:3px 6px;'
                f'text-align:center;border:1px solid rgba(255,255,255,.1);'
                f'border-right:3px solid rgba(255,255,255,.4);font-size:.68rem">Dia</th>'
            )
        hdr_jours += (
            '<th colspan="2" style="background:#15803d;color:#fff;padding:5px 10px;'
            'text-align:center;border:1px solid rgba(255,255,255,.2);font-size:.75rem">'
            + 'Moyenne ' + mc['label'].split()[-1] + '</th>'
        )
        hdr_sysd += (
            '<th style="background:#166534;color:#dde;padding:3px 6px;text-align:center;font-size:.68rem">Sys</th>'
            '<th style="background:#166534;color:#dde;padding:3px 6px;text-align:center;font-size:.68rem">Dia</th>'
        )

        # Ligne heure/note
        heure_row = (
            '<tr><td style="padding:4px 8px;color:#64748b;font-size:.7rem;background:#f8fafc;font-style:italic">Heure / Note</td>'
        )
        for jour in range(1, n_jours+1):
            cell  = (grille.get(jour) or grille.get(str(jour)) or {}).get(moment, {})
            rangs = cell.get('rangs', {})
            r1    = rangs.get(1) or rangs.get('1')
            heure = _fmt_heure(r1.get('timestamp','')) if r1 else '—'
            note  = (r1.get('note','') or '') if r1 else ''
            txt   = heure + (' · ' + note if note else '')
            heure_row += (
                f'<td colspan="2" style="padding:3px 8px;text-align:center;font-size:.7rem;'
                f'color:#475569;font-style:italic;background:#f8fafc;border:1px solid #e2e8f0;border-right:2px solid #94a3b8">{txt}</td>'
            )
        heure_row += '<td colspan="2" style="background:#dcfce7;border:1px solid #bbf7d0"></td></tr>'

        # Lignes rangs
        rang_rows = ''
        for rang in range(1, n_rangs+1):
            is_exclu = exclu_r1 and rang==1
            row_bg   = '#f0f0f0' if is_exclu else lgt
            exclu_lbl = ' (exclu)' if is_exclu else ''
            rang_rows += (
                f'<tr><td style="padding:4px 8px;color:#475569;font-size:.73rem;background:{row_bg}">'
                f'Mesure {rang}{exclu_lbl}</td>'
            )
            for jour in range(1, n_jours+1):
                cell   = (grille.get(jour) or grille.get(str(jour)) or {}).get(moment, {})
                rangs  = cell.get('rangs', {})
                rangs_s= (cell.get('bras_s') or {}).get('rangs', {})
                s      = rangs.get(rang) or rangs.get(str(rang))
                ss     = rangs_s.get(rang) or rangs_s.get(str(rang)) if rangs_s else None
                if s:
                    sv, dv = s['systolic'], s['diastolic']
                    tc_sys, tl_sys, tc_dia, tl_dia = _cc_split(sv, dv, classif, profil)
                    st_s = ('color:#94a3b8;text-decoration:line-through' if is_exclu
                            else f'color:{tc_sys};font-weight:700')
                    st_d = ('color:#94a3b8;text-decoration:line-through' if is_exclu
                            else f'color:{tc_dia};font-weight:700')
                    # Bras S en () inline : (sys_s) dans col Sys, (dia_s) dans col Dia
                    s_sys_txt = s_dia_txt = ''
                    if ss and not is_exclu:
                        tcs_sys, _, tcs_dia, _ = _cc_split(ss['systolic'], ss['diastolic'], classif, profil)
                        tcs = tcs_sys  # sys couleur bras S
                        s_sys_txt = (f' <span style="font-size:.68rem;color:{tcs};font-style:italic">'
                                     f'({ss["systolic"]})</span>')
                        s_dia_txt = (f' <span style="font-size:.68rem;color:{tcs};font-style:italic">'
                                     f'({ss["diastolic"]})</span>')
                    rang_rows += (
                        f'<td style="padding:4px 6px;text-align:center;{st_s};background:{row_bg};'
                        f'font-size:.8rem;border:1px solid #e2e8f0">{sv}{s_sys_txt}</td>'
                        f'<td style="padding:4px 6px;text-align:center;{st_d};background:{row_bg};'
                        f'font-size:.8rem;border:1px solid #e2e8f0;border-right:3px solid #cbd5e1">{dv}{s_dia_txt}</td>'
                    )
                else:
                    rang_rows += (
                        f'<td colspan="2" style="text-align:center;color:#cbd5e1;background:{row_bg};'
                        f'border:1px solid #e2e8f0;border-right:2px solid #94a3b8">—</td>'
                    )
            rang_rows += '<td colspan="2" style="background:#dcfce7;border:1px solid #bbf7d0"></td></tr>'

        # Ligne moyenne séance + moyenne moment
        moy_vals_s = []; moy_vals_d = []
        moy_vals_ss = []; moy_vals_sd = []  # bras S
        moy_row = (
            f'<tr><td style="padding:5px 8px;font-weight:700;color:#fff;background:{bg};font-size:.75rem">Moyenne</td>'
        )
        for jour in range(1, n_jours+1):
            cell   = (grille.get(jour) or grille.get(str(jour)) or {}).get(moment, {})
            moy    = cell.get('moy_seance')
            bras_s_cell = cell.get('bras_s') or {}
            moy_s  = bras_s_cell.get('moy_seance')
            if moy and cell.get('complete'):
                tc_sys, tl_sys, tc_dia, tl_dia = _cc_split(moy['sys'], moy['dia'], classif, profil)
                tc, tl = tc_sys, tl_sys  # compat lignes suivantes
                moy_vals_s.append(moy['sys']); moy_vals_d.append(moy['dia'])
                all_jour_sys[jour].append(moy['sys']); all_jour_dia[jour].append(moy['dia'])
                s_sys_m = s_dia_m = ''
                if moy_s and bras_s_cell.get('complete'):
                    tcs_sys, _, tcs_dia, _ = _cc_split(moy_s['sys'], moy_s['dia'], classif, profil)
                    tcs = tcs_sys
                    moy_vals_ss.append(moy_s['sys']); moy_vals_sd.append(moy_s['dia'])
                    all_jour_sys_s[jour].append(moy_s['sys'])
                    all_jour_dia_s[jour].append(moy_s['dia'])
                    s_sys_m = (f' <span style="font-size:.68rem;color:{tcs};font-style:italic">'
                               f'({moy_s["sys"]})</span>')
                    s_dia_m = (f' <span style="font-size:.68rem;color:{tcs};font-style:italic">'
                               f'({moy_s["dia"]})</span>')
                moy_row += (
                    f'<td style="padding:5px 6px;text-align:center;font-weight:700;color:{tc_sys};'
                    f'background:{tl};border:1px solid #e2e8f0;font-size:.82rem">{moy["sys"]}{s_sys_m}</td>'
                    f'<td style="padding:5px 6px;text-align:center;font-weight:700;color:{tc_dia};'
                    f'background:{tl};border:1px solid #e2e8f0;'
                    f'border-right:3px solid #cbd5e1;font-size:.82rem">{moy["dia"]}{s_dia_m}</td>'
                )
            elif cell.get('n_saisies', 0) > 0:
                ns = cell['n_saisies']
                moy_row += (
                    f'<td colspan="2" style="text-align:center;color:#f97316;font-size:.75rem;'
                    f'background:#fff7ed;border:1px solid #e2e8f0">{ns}/{n_rangs}</td>'
                )
            else:
                moy_row += '<td colspan="2" style="text-align:center;color:#94a3b8;border:1px solid #e2e8f0">—</td>'

        # Cellule moyenne moment (bras P + bras S entre ())
        if moy_vals_s:
            ms = round(sum(moy_vals_s)/len(moy_vals_s), 1)
            md = round(sum(moy_vals_d)/len(moy_vals_d), 1)
            tc_sys, tl_sys, tc_dia, tl_dia = _cc_split(ms, md, classif, profil)
            tc = tc_sys  # compat
            s_sys_mm = s_dia_mm = ''
            if moy_vals_ss and len(moy_vals_ss) == len(moy_vals_s):
                mss = round(sum(moy_vals_ss)/len(moy_vals_ss), 1)
                msd = round(sum(moy_vals_sd)/len(moy_vals_sd), 1)
                tcs_sys, _, tcs_dia, _ = _cc_split(mss, msd, classif, profil)
                tcs = tcs_sys
                s_sys_mm = (f' <span style="font-size:.7rem;color:{tcs};font-style:italic">({mss})</span>')
                s_dia_mm = (f' <span style="font-size:.7rem;color:{tcs};font-style:italic">({msd})</span>')
            moy_row += (
                f'<td style="padding:6px 10px;text-align:center;font-weight:800;color:{tc_sys};'
                f'background:#dcfce7;font-size:1.05rem;border:1px solid #bbf7d0">{ms}{s_sys_mm}</td>'
                f'<td style="padding:6px 10px;text-align:center;font-weight:800;color:{tc_dia};'
                f'background:#dcfce7;font-size:1.05rem;border:1px solid #bbf7d0">{md}{s_dia_mm}</td>'
            )
        else:
            moy_row += '<td colspan="2" style="text-align:center;color:#94a3b8;background:#dcfce7">—</td>'
        moy_row += '</tr>'
        moment_tables += (
            '<div style="margin-bottom:20px;border-radius:8px;overflow:hidden;border:2px solid ' + bg + ';box-shadow:0 2px 8px rgba(0,0,0,.07)">'
            '<table style="width:100%;border-collapse:collapse">'
            '<thead>'
            f'<tr><th rowspan="2" style="background:{bg};color:#fff;padding:8px 12px;'
            f'text-align:left;font-size:.9rem;vertical-align:middle;white-space:nowrap">{mc["label"]}</th>'
            f'{hdr_jours}</tr>'
            f'<tr>{hdr_sysd}</tr>'
            '</thead>'
            f'<tbody>{heure_row}{rang_rows}{moy_row}</tbody>'
            '</table></div>'
        )

    # ── Ligne Moyenne du Jour ──────────────────────────────────────────────────
    jour_cells = ''
    for jour in range(1, n_jours+1):
        if all_jour_sys[jour]:
            js = round(sum(all_jour_sys[jour])/len(all_jour_sys[jour]),1)
            jd = round(sum(all_jour_dia[jour])/len(all_jour_dia[jour]),1)
            tc_sys, tl_sys, tc_dia, tl_dia = _cc_split(js, jd, classif, profil)
            jour_cells += (
                f'<td style="padding:7px 12px;text-align:center;font-weight:700;color:{tc_sys};'
                f'background:{tl_sys};font-size:.88rem;border:1px solid #e2e8f0">{js}</td>'
                f'<td style="padding:7px 12px;text-align:center;font-weight:700;color:{tc_dia};'
                f'background:{tl_dia};font-size:.88rem;border:1px solid #e2e8f0;border-right:2px solid #94a3b8">{jd}</td>'
            )
        else:
            jour_cells += '<td colspan="2" style="text-align:center;color:#94a3b8;border:1px solid #e2e8f0">—</td>'

    # ── Section Moyennes par jour : double source ─────────────────────────────
    # Source 1 : automesure (bras P)
    # Source 2 : mesures_base = dict { 'YYYY-MM-DD': {sys, dia, n} }
    jour_rows = ''
    for jour in range(1, n_jours+1):
        d_obj = date_debut_obj + _td(days=jour-1) if date_debut_obj else None
        date_key = d_obj.isoformat() if d_obj else ''
        jour_label_full = f"{JOURS_FR[d_obj.weekday()]} {d_obj.day} {MOIS_FR[d_obj.month-1]} {d_obj.year}" if d_obj else f'Jour {jour}'

        # Automesure bras P + bras S en ()
        if all_jour_sys[jour]:
            js = round(sum(all_jour_sys[jour])/len(all_jour_sys[jour]), 1)
            jd = round(sum(all_jour_dia[jour])/len(all_jour_dia[jour]), 1)
            tc_sys, tl_sys, tc_dia, tl_dia = _cc_split(js, jd, classif, profil)
            tc, tl = tc_sys, tl_sys  # compat
            # Bras S pour ce jour
            _js_s = _jd_s = None
            if all_jour_sys_s[jour]:
                _js_s = round(sum(all_jour_sys_s[jour])/len(all_jour_sys_s[jour]), 1)
                _jd_s = round(sum(all_jour_dia_s[jour])/len(all_jour_dia_s[jour]), 1)
                tcs_sys, _, tcs_dia, _ = _cc_split(_js_s, _jd_s, classif, profil)
                tcs = tcs_sys
                _s_sys_j = f' <span style="font-size:.75rem;color:{tcs};font-style:italic">({_js_s})</span>'
                _s_dia_j = f' <span style="font-size:.75rem;color:{tcs};font-style:italic">({_jd_s})</span>'
            else:
                _s_sys_j = _s_dia_j = ''
            am_cell = (
                f'<td style="padding:7px 12px;text-align:center;font-weight:700;color:{tc_sys};background:{tl_sys};'
                f'font-size:.88rem;border:1px solid #e2e8f0">{js}{_s_sys_j}</td>'
                f'<td style="padding:7px 12px;text-align:center;font-weight:700;color:{tc_dia};background:{tl_dia};'
                f'font-size:.88rem;border:1px solid #e2e8f0;border-right:3px solid #cbd5e1">{jd}{_s_dia_j}</td>'
            )
        else:
            am_cell = '<td colspan="2" style="text-align:center;color:#94a3b8;border:1px solid #e2e8f0;border-right:3px solid #cbd5e1">—</td>'

        # Base générale
        base_day = mesures_base.get(date_key, {}) if mesures_base else {}
        if base_day and base_day.get('sys'):
            bs = round(base_day['sys'], 1)
            bd = round(base_day['dia'], 1)
            bn = base_day.get('n', '?')
            tc2_sys, tl2_sys, tc2_dia, tl2_dia = _cc_split(bs, bd, classif, profil)
            tc2, tl2 = tc2_sys, tl2_sys  # compat
            base_cell = (
                f'<td style="padding:7px 12px;text-align:center;font-weight:700;color:{tc2_sys};background:{tl2_sys};'
                f'font-size:.88rem;border:1px solid #e2e8f0">{bs}</td>'
                f'<td style="padding:7px 12px;text-align:center;font-weight:700;color:{tc2_dia};background:{tl2_dia};'
                f'font-size:.88rem;border:1px solid #e2e8f0">{bd}</td>'
                f'<td style="padding:7px 12px;text-align:center;font-size:.72rem;color:#64748b;border:1px solid #e2e8f0">{bn} mes.</td>'
            )
        else:
            base_cell = '<td colspan="3" style="text-align:center;color:#94a3b8;font-size:.75rem;border:1px solid #e2e8f0;font-style:italic">Aucune mesure</td>'

        bg_row = '#fff' if jour%2 else '#f8fafc'
        jour_rows += (
            f'<tr style="background:{bg_row}">'
            f'<td style="padding:7px 12px;font-weight:600;color:#1e3a5f;white-space:nowrap;font-size:.8rem;border:1px solid #e2e8f0">{jour_label_full}</td>'
            f'{am_cell}{base_cell}'
            '</tr>'
        )

    jour_moy_html = (
        '<div style="margin-bottom:16px;border-radius:8px;overflow:hidden;border:2px solid #475569">'
        '<table style="width:100%;border-collapse:collapse;font-size:.8rem">'
        '<thead><tr>'
        '<th style="background:#475569;color:#fff;padding:7px 12px;text-align:left">Date</th>'
        '<th colspan="2" style="background:#1e3a5f;color:#fff;padding:7px 12px;text-align:center;border-right:3px solid rgba(255,255,255,.3)">★ Automesure (bras ' + bras_prio_label + ')</th>'
        '<th colspan="3" style="background:#475569;color:#e2e8f0;padding:7px 12px;text-align:center">Suivi continu (toutes mesures)</th>'
        '</tr>'
        '<tr>'
        '<th style="background:#64748b;color:#e2e8f0;padding:4px 12px;font-size:.7rem"></th>'
        '<th style="background:#2d4a6f;color:#dde;padding:4px 8px;text-align:center;font-size:.7rem">Sys</th>'
        '<th style="background:#2d4a6f;color:#dde;padding:4px 8px;text-align:center;font-size:.7rem;border-right:3px solid rgba(255,255,255,.2)">Dia</th>'
        '<th style="background:#64748b;color:#dde;padding:4px 8px;text-align:center;font-size:.7rem">Sys</th>'
        '<th style="background:#64748b;color:#dde;padding:4px 8px;text-align:center;font-size:.7rem">Dia</th>'
        '<th style="background:#64748b;color:#dde;padding:4px 8px;text-align:center;font-size:.7rem">N</th>'
        '</tr></thead>'
        f'<tbody>{jour_rows}</tbody>'
        '</table></div>'
    )

    # Fallback moy_sys_s : calculer depuis grille accumulée si pas encore en base
    if not moy_sys_s:
        _all_s = [v for lst in all_jour_sys_s.values() for v in lst]
        _all_d = [v for lst in all_jour_dia_s.values() for v in lst]
        if _all_s:
            moy_sys_s = round(sum(_all_s)/len(_all_s), 1)
            moy_dia_s = round(sum(_all_d)/len(_all_d), 1)
            # Recalculer gc_s/gl_s avec les nouvelles valeurs
            if moy_sys_s and moy_dia_s:
                gc_s, _ = _cc(moy_sys_s, moy_dia_s, classif, profil)
                gl_s = ('Dans la cible' if gc_s=='#16a34a' else 'Hors cible') if classif=='cible' else _esh_label(_worst_key(moy_sys_s, moy_dia_s))

    # ── Synthèse ───────────────────────────────────────────────────────────────
    ec_s = (f"{'+'if ecart_s>0 else ''}{ecart_s} vs cible {cible_sys}") if ecart_s is not None else ''
    ec_d = (f"{'+'if ecart_d>0 else ''}{ecart_d} vs cible {cible_dia}") if ecart_d is not None else ''

    # Bras S en () pour la synthèse
    _s_sys_txt = (f'<span style="font-size:.9rem;color:{gc_s};font-style:italic"> ({moy_sys_s})</span>' if gc_s else '')
    _s_dia_txt = (f'<span style="font-size:.9rem;color:{gc_s};font-style:italic"> ({moy_dia_s})</span>' if gc_s else '')
    _s_cl_txt  = (f'<div style="font-size:.68rem;color:{gc_s};font-style:italic;margin-top:2px">({gl_s})</div>' if gl_s else '')
    _s_ec_s_txt= (f'<div style="font-size:.6rem;color:{gc_s};font-style:italic">({round(moy_sys_s-cible_sys,1):+g} vs cible)</div>'
                  if gc_s and moy_sys_s else '')
    _s_ec_d_txt= (f'<div style="font-size:.6rem;color:{gc_s};font-style:italic">({round(moy_dia_s-cible_dia,1):+g} vs cible)</div>'
                  if gc_s and moy_dia_s else '')

    synthese_html = (
        f'<div style="border-radius:10px;overflow:hidden;border:2px solid {gc};margin-bottom:14px">'
        '<table style="width:100%;border-collapse:collapse">'
        '<tr>'
        f'<td style="padding:10px 16px;background:{glight};font-weight:700;color:#1e3a5f;font-size:.85rem;width:180px">Moyenne des mesures</td>'
        f'<td style="padding:10px 16px;background:{glight};text-align:center;width:130px">'
        f'<div style="display:flex;align-items:baseline;justify-content:center;gap:6px"><span style="font-size:1.7rem;font-weight:800;color:{gc_sys}">{moy_sys or "—"}</span>{_s_sys_txt}</div>'
        '<div style="font-size:.62rem;color:#94a3b8">Systolique mmHg</div>'
        + (f'<div style="font-size:.62rem;color:{gc_sys}">{ec_s}</div>' if ec_s else '')
        + _s_ec_s_txt +
        '</td>'
        f'<td style="padding:10px 16px;background:{glight};text-align:center;width:130px">'
        f'<div style="display:flex;align-items:baseline;justify-content:center;gap:6px"><span style="font-size:1.7rem;font-weight:800;color:{gc_dia}">{moy_dia or "—"}</span>{_s_dia_txt}</div>'
        '<div style="font-size:.62rem;color:#94a3b8">Diastolique mmHg</div>'
        + (f'<div style="font-size:.62rem;color:{gc_dia}">{ec_d}</div>' if ec_d else '')
        + _s_ec_d_txt +
        '</td>'
        f'<td style="padding:10px 16px;background:{glight};text-align:center;width:110px">'
        f'<div style="font-size:1.2rem;font-weight:700;color:#1e3a5f">{moy_fc or "—"}</div>'
        '<div style="font-size:.62rem;color:#94a3b8">FC moy. bpm</div>'
        '</td>'
        f'<td style="padding:10px 16px;background:{glight};text-align:center">'
        f'<div style="display:inline-block;padding:6px 16px;border-radius:20px;background:{gc};color:#fff;font-weight:700;font-size:.82rem">{gl}</div>'
        + _s_cl_txt +
        f'<div style="font-size:.66rem;color:#64748b;margin-top:4px">Complétude : {proto.get("taux_completude","—")}%</div>'
        '</td>'
        + (f'<td style="padding:10px 16px;background:{glight};text-align:center;border-left:1px solid #e2e8f0"><div style="font-size:.7rem;color:#94a3b8;margin-bottom:4px">Suivi continu</div><div style="font-size:1.1rem;font-weight:700;color:{gc_s}">{moy_sys_s}&nbsp;/&nbsp;{moy_dia_s}</div><div style="font-size:.62rem;color:#94a3b8">mmHg</div></td>' if moy_sys_s and moy_dia_s else '<td style="background:{glight}"></td>') +
        '</tr></table></div>'
    )

    # ── Infos protocole ────────────────────────────────────────────────────────
    # Toujours recalculer date_fin = date_debut + n_jours - 1 (date_fin stockée = date de clôture)
    if date_debut_obj:
        _date_fin_str = (date_debut_obj + _td(days=n_jours - 1)).isoformat()
    else:
        _date_fin_str = proto.get('date_fin') or ''
    pills = (
        f'<span class="pill">📅 {_fmt_date_long(proto.get("date_debut",""))} → {_fmt_date_long(_date_fin_str) if _date_fin_str else "—"}</span>'
        f'<span class="pill">{n_jours} jours</span>'
        + ''.join(f'<span class="pill">{MOMENT_CFG.get(m,{}).get("label",m)}</span>' for m in moments) +
        f'<span class="pill">{n_rangs} mesures · {intervalle} min</span>'
        f'<span class="pill">R1 {"exclue" if exclu_r1 else "incluse"}</span>'
        f'<span class="pill">Classif. {"cible" if classif=="cible" else "ESH"}</span>'
    )

    comparatif_html = _render_comparatif(proto_prec, grille_prec)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Rapport — {nom}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Outfit:wght@400;500;600;700&display=swap');
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Outfit',sans-serif;font-size:13px;color:#334155;background:#fff;padding:18px 24px}}
  @media print{{body{{padding:0;font-size:11px}}.no-print{{display:none!important}}}}
  #dynamicPageStyle{{display:none}}
  .btn-print{{display:inline-flex;align-items:center;gap:6px;padding:7px 18px;background:#2563eb;
    color:#fff;border:none;border-radius:6px;cursor:pointer;font-family:'Outfit',sans-serif;
    font-size:.82rem;font-weight:600;margin-bottom:12px}}
  .rpt-header{{display:flex;justify-content:space-between;align-items:flex-start;
    border-bottom:3px solid #2563eb;padding-bottom:10px;margin-bottom:12px}}
  .rpt-title{{font-family:'Playfair Display',serif;font-size:1.2rem;color:#1e3a5f}}
  .info-pills{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:12px}}
  .pill{{background:#f1f5f9;padding:2px 8px;border-radius:4px;font-size:.68rem;color:#64748b}}
  .rpt-footer{{border-top:1px solid #e2e8f0;padding-top:7px;margin-top:7px;
    display:flex;justify-content:space-between;font-size:.6rem;color:#94a3b8}}
</style>
</head>
<body>
<style id="dynamicPageStyle">@page{{margin:8mm;size:A4 portrait}}</style>
<style id="fitPageStyle"></style>
<div class="no-print" style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap">
  <button class="btn-print" onclick="doPrint()">🖨️ Imprimer / PDF</button>
  <div style="display:flex;gap:6px;align-items:center">
    <span style="font-size:.75rem;color:#64748b;font-weight:600">Orientation :</span>
    <button id="btnPortrait" onclick="setOrient('portrait')"
      style="padding:4px 12px;font-size:.75rem;border-radius:5px;border:2px solid #2563eb;
             background:#2563eb;color:#fff;cursor:pointer;font-family:'Outfit',sans-serif;font-weight:600">
      Portrait
    </button>
    <button id="btnPaysage" onclick="setOrient('landscape')"
      style="padding:4px 12px;font-size:.75rem;border-radius:5px;border:2px solid #e2e8f0;
             background:#fff;color:#64748b;cursor:pointer;font-family:'Outfit',sans-serif;font-weight:600">
      Paysage
    </button>
    <span style="font-size:.75rem;color:#64748b;font-weight:600;margin-left:6px">Zoom :</span>
    <button id="btnFitW" onclick="setFit('width')"
      style="padding:4px 12px;font-size:.75rem;border-radius:5px;border:2px solid #e2e8f0;
             background:#fff;color:#64748b;cursor:pointer;font-family:'Outfit',sans-serif;font-weight:600"
      title="Ajuster la largeur à la page">
      ↔ Largeur
    </button>
    <button id="btnFitP" onclick="setFit('page')"
      style="padding:4px 12px;font-size:.75rem;border-radius:5px;border:2px solid #e2e8f0;
             background:#fff;color:#64748b;cursor:pointer;font-family:'Outfit',sans-serif;font-weight:600"
      title="Ajuster tout le contenu en une page">
      ⛶ 1 page
    </button>
    <button id="btnFitNone" onclick="setFit('none')"
      style="padding:4px 12px;font-size:.75rem;border-radius:5px;border:2px solid #e2e8f0;
             background:#fff;color:#64748b;cursor:pointer;font-family:'Outfit',sans-serif;font-weight:600"
      title="Taille réelle">
      1:1
    </button>
  </div>
</div>
<script>
  var _orient = 'portrait';
  var _fit = 'none';

  function _btnStyle(id, active) {{
    var el = document.getElementById(id);
    el.style.background  = active ? '#2563eb' : '#fff';
    el.style.color       = active ? '#fff'    : '#64748b';
    el.style.borderColor = active ? '#2563eb' : '#e2e8f0';
  }}

  function setOrient(o) {{
    _orient = o;
    document.getElementById('dynamicPageStyle').textContent =
      '@page{{margin:8mm;size:A4 ' + o + '}}';
    _btnStyle('btnPortrait', o==='portrait');
    _btnStyle('btnPaysage',  o==='landscape');
  }}

  function setFit(mode) {{
    _fit = mode;
    _btnStyle('btnFitW',    mode==='width');
    _btnStyle('btnFitP',    mode==='page');
    _btnStyle('btnFitNone', mode==='none');
    var s = document.getElementById('fitPageStyle');
    if (mode === 'width') {{
      // Ajuster la largeur : scale sur body
      s.textContent = '@media print{{ body{{ transform-origin:top left; width:100%; }} }}';
    }} else if (mode === 'page') {{
      // Zoom CSS natif + suppression page blanche
      s.textContent = '@media print{{ ' +
        'html{{ zoom:0.62; height:100%; }} ' +
        'body{{ font-size:9px!important; height:100%; overflow:hidden; }} ' +
        '@page{{ margin:6mm; size:A4 ' + _orient + '; }} ' +
        '* {{ page-break-inside:avoid!important; page-break-after:avoid!important; page-break-before:avoid!important; }} ' +
        '}}';
    }} else {{
      s.textContent = '';
    }}
  }}

  function doPrint() {{ window.print(); }}
</script>
<div class="rpt-header">
  <div>
    <div class="rpt-title">Rapport d'Automesures Tensionnelles</div>
    <div style="font-size:.82rem;color:#64748b;margin-top:3px;font-weight:600">{proto.get('label','')}</div>
  </div>
  <div style="text-align:right;font-size:.7rem;color:#64748b;line-height:1.8">Généré le {generated}<br>Hilo {hilo_version}</div>
</div>
{patient_html}
<hr style="border:none;border-top:2px solid #e2e8f0;margin:4px 0 10px 0">
<div class="info-pills">{pills}</div>
{moment_tables}
<hr style="border:none;border-top:3px solid #475569;margin:4px 0 12px 0">
{jour_moy_html}
<hr style="border:none;border-top:3px solid ' + gc + ';margin:4px 0 12px 0">
{synthese_html}
{comparatif_html}
<div class="rpt-footer">
  <span>Généré par Hilo {hilo_version} — à titre informatif, non substitutif d'un avis médical.</span>
  <span>{generated}</span>
</div>
</body>
</html>"""
