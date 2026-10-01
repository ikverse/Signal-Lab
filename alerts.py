"""Phone notifications and spoken alerts through Termux:API. On the PC they print instead.

Every alert is also written to the database, so the Alerts screen shows the same list the
phone was told, whether or not notifications were switched on.
"""

import shutil
import subprocess

import config
import store


def _termux(cmd):
    return shutil.which(cmd) is not None


def notify(conn, kind, title, body, symbol=None, tf=None, link=None, speak=None, settings=None):
    """Record the alert, then show it (and optionally say it) if the settings allow."""
    store.add_alert(conn, kind, title, body, symbol, tf, link)
    s = settings or store.get_settings(conn)
    if not s.get("alerts_on", True):
        return
    url = f"http://{config.SERVER_HOST}:{config.SERVER_PORT}/{link or ''}"
    if _termux("termux-notification"):
        subprocess.run(
            ["termux-notification", "--title", title, "--content", body,
             "--group", "signal-lab", "--id", f"{kind}-{symbol or ''}",
             "--action", f"termux-open-url {url}"],
            timeout=20, check=False,
        )
    else:
        print(f"[alert] {title} — {body}", flush=True)
    if speak and s.get("speak_on", True):
        if _termux("termux-tts-speak"):
            subprocess.Popen(["termux-tts-speak", speak])
        else:
            print(f"[speak] {speak}", flush=True)
