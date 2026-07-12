"""
launch_hilo.py — Point d'entrée principal de Hilo V7.0
Lance Flask sur localhost:5050 et ouvre Chrome/Safari automatiquement
"""

import sys
import os
import time
import threading
import webbrowser
from pathlib import Path

# ── Port configurable ─────────────────────────────────────────────────────────
PORT = 5050
URL  = f"http://127.0.0.1:{PORT}"
VERSION = "V9.0.7"

# ── Debug chemin ─────────────────────────────────────────────────────────────
print(f"[Hilo] Fichier    : {os.path.abspath(__file__)}")
print(f"[Hilo] Dossier    : {os.path.dirname(os.path.abspath(__file__))}")
print(f"[Hilo] Python     : {sys.executable}")


def open_browser():
    """Ouvre immédiatement la page splash locale, qui redirige vers Flask quand prêt."""
    import subprocess, platform
    from pathlib import Path

    # Sous PyInstaller (_MEIPASS), les templates sont extraits dans un dossier temporaire
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    splash = base / "templates" / "splash.html"
    splash_url = splash.as_uri()  # file:///...

    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", "Google Chrome", splash_url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif platform.system() == "Windows":
            # Sur Windows : ouvrir avec le navigateur par défaut
            os.startfile(splash_url)
        else:
            webbrowser.open(splash_url)
    except Exception:
        webbrowser.open(splash_url)

def is_flask_running():
    """Vérifie si Flask tourne déjà sur le port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', PORT)) == 0

def kill_existing_flask():
    """Tue le processus Flask existant sur le port."""
    import subprocess, platform
    try:
        if platform.system() == 'Darwin':
            result = subprocess.run(
                ['lsof', '-ti', f'tcp:{PORT}'],
                capture_output=True, text=True
            )
            pids = result.stdout.strip().split()
            for pid in pids:
                subprocess.run(['kill', '-9', pid], capture_output=True)
            time.sleep(1.5)
            print(f"[Hilo] Ancien serveur (PID {', '.join(pids)}) arrete.")
        elif platform.system() == 'Windows':
            # Windows : netstat + taskkill
            result = subprocess.run(
                f'netstat -ano | findstr :{PORT}',
                shell=True, capture_output=True, text=True
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if parts and parts[-1].isdigit():
                    subprocess.run(['taskkill', '/F', '/PID', parts[-1]],
                                   capture_output=True)
            time.sleep(1.5)
            print(f"[Hilo] Ancien serveur arrete (port {PORT}).")
        else:
            subprocess.run(f'fuser -k {PORT}/tcp', shell=True, capture_output=True)
            time.sleep(1)
    except Exception as e:
        print(f"[Hilo] Impossible d'arreter l'ancien serveur : {e}")

def main():
    # Sous PyInstaller, rediriger stdout/stderr vers null (pas de log fichier)
    if getattr(sys, 'frozen', False):
        try:
            import io
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
        except Exception:
            pass

    # Assure que le répertoire courant est celui du script (important sous Thonny/Windows)
    script_dir = Path(__file__).parent.resolve()
    os.chdir(script_dir)

    # Assure que les modules locaux sont trouvables (important pour PyInstaller)
    base = Path(getattr(sys, '_MEIPASS', script_dir))
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    os.environ["HILO_PORT"]    = str(PORT)
    os.environ["HILO_VERSION"] = VERSION

    # ── Vérifier si Flask tourne déjà ────────────────────────────────────────
    if is_flask_running():
        print(f"[Hilo] Un serveur tourne déjà sur le port {PORT}.")
        # Si lancé depuis un terminal interactif : demander
        # Sinon (Automator, double-clic) : tuer et relancer automatiquement
        if sys.stdin and sys.stdin.isatty():
            response = input("  [k] Arrêter et relancer  [o] Ouvrir dans le navigateur  [q] Quitter : ").strip().lower()
            if response == 'o':
                open_browser()
                print("[Hilo] Navigateur ouvert sur l'instance existante.")
                return
            elif response == 'q':
                print("[Hilo] Annulé.")
                return
            # 'k' ou autre → tuer et relancer
        else:
            print("[Hilo] Mode automatique — arrêt de l'ancienne instance.")
        kill_existing_flask()
        print("[Hilo] Relancement…")

    # Ouvrir le navigateur en arrière-plan
    t = threading.Thread(target=open_browser, daemon=True)
    t.start()

    # Lancer Flask (bloquant)
    from app import app, get_db_path, _sync_meteo_velo
    print(f"🩺 Hilo {VERSION} — http://127.0.0.1:{PORT}")
    print("   Fermez cette fenêtre pour quitter l'application.")

    # Sync météo vélo au démarrage
    try:
        _db = get_db_path()
        if _db:
            print("[Démarrage] Météo vélo : vérification en cours...")
            _sync_meteo_velo(_db)
    except Exception as _e:
        print(f"[Démarrage] Météo vélo erreur : {_e}")

    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
