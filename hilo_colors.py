"""
hilo_colors.py — Hilo V8.5.0
Référentiel couleurs officiel Hilo/Aktiia — source unique
NE PAS MODIFIER sauf si Aktiia change sa charte officielle
"""

# ── Classification tensionnelle ───────────────────────────────────────────────
CLASSIFICATION = {
    'optimale' : {'r': 53,  'g': 122, 'b': 125, 'label': 'Optimale'},
    'normale'  : {'r': 139, 'g': 194, 'b': 66,  'label': 'Normale'},
    'elevee'   : {'r': 243, 'g': 179, 'b': 83,  'label': 'Élevée'},
    'hta1'     : {'r': 238, 'g': 132, 'b': 51,  'label': 'HTA Stade 1'},
    'hta2'     : {'r': 218, 'g': 60,  'b': 37,  'label': 'HTA Stade 2'},
    'hta3'     : {'r': 167, 'g': 34,  'b': 41,  'label': 'HTA Stade 3'},
}

# ── Cible (Target) — binaire ───────────────────────────────────────────────────
TARGET = {
    'ok'  : {'r': 139, 'g': 194, 'b': 66,  'label': 'Dans la cible'},
    'nok' : {'r': 218, 'g': 60,  'b': 37,  'label': 'Hors cible'},
}

# ── Bornes de classification ───────────────────────────────────────────────────
# Retourne la clé de classification selon sys et dia
def get_classification(sys, dia):
    """Retourne la clé de classification selon les valeurs sys/dia."""
    if sys < 120 and dia < 80:
        return 'optimale'
    elif sys < 130 and dia < 85:
        return 'normale'
    elif sys < 140 and dia < 90:
        return 'elevee'
    elif sys < 160 and dia < 100:
        return 'hta1'
    elif sys < 180 and dia < 110:
        return 'hta2'
    else:
        return 'hta3'

# ── Helpers CSS ───────────────────────────────────────────────────────────────
def rgb(key, alpha=1.0, category='classification'):
    """Retourne une couleur CSS rgb() ou rgba() depuis la clé."""
    d = CLASSIFICATION if category == 'classification' else TARGET
    c = d.get(key, CLASSIFICATION['optimale'])
    if alpha < 1.0:
        return f"rgba({c['r']},{c['g']},{c['b']},{alpha})"
    return f"rgb({c['r']},{c['g']},{c['b']})"

def css_vars():
    """Retourne les variables CSS pour injection dans les templates."""
    lines = []
    for key, c in CLASSIFICATION.items():
        lines.append(f"--color-{key}: rgb({c['r']},{c['g']},{c['b']});")
    lines.append(f"--color-target-ok:  rgb({TARGET['ok']['r']},{TARGET['ok']['g']},{TARGET['ok']['b']});")
    lines.append(f"--color-target-nok: rgb({TARGET['nok']['r']},{TARGET['nok']['g']},{TARGET['nok']['b']});")
    return "\n".join(lines)

def js_colors():
    """Retourne un objet JS avec toutes les couleurs pour le dashboard."""
    items = []
    for key, c in CLASSIFICATION.items():
        r, g, b = c['r'], c['g'], c['b']
        items.append(f"  {key}: 'rgb({r},{g},{b})'")
    r, g, b = TARGET['ok']['r'], TARGET['ok']['g'], TARGET['ok']['b']
    items.append(f"  target_ok: 'rgb({r},{g},{b})'")
    r, g, b = TARGET['nok']['r'], TARGET['nok']['g'], TARGET['nok']['b']
    items.append(f"  target_nok: 'rgb({r},{g},{b})'")
    return "const HILO_COLORS = {\n" + ",\n".join(items) + "\n};"
