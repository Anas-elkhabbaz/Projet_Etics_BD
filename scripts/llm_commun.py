"""
Projet ETICS - fonctions communes aux etapes LLM (05 et 06).

Le modele se choisit avec la variable d'environnement ETICS_LLM_MODEL (defaut : gpt-4.1-mini).
La cle est lue dans OPENAI_API_KEY, comme pour l'etape 03.
"""
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BD = ROOT / "bd"
MODEL = os.environ.get("ETICS_LLM_MODEL", "gpt-4.1-mini")


def client():
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY absente. PowerShell : $env:OPENAI_API_KEY = \"sk-...\"")
    from openai import OpenAI
    return OpenAI()


def ask_json(cli, system, user):
    """Appelle le LLM et renvoie sa reponse en JSON (reprise automatique en cas d'erreur)."""
    for attempt in range(5):
        try:
            resp = cli.chat.completions.create(
                model=MODEL, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            wait = 2 ** attempt
            print(f"  erreur LLM ({type(e).__name__}: {e}) - nouvel essai dans {wait}s")
            time.sleep(wait)
    raise RuntimeError("LLM indisponible apres 5 essais")


def append_csv(rows, path, columns):
    """Ajoute des lignes a un CSV (reprise possible si le script est interrompu)."""
    if rows:
        pd.DataFrame(rows, columns=columns).to_csv(path, mode="a", index=False, encoding="utf-8",
                                                   header=not path.exists())


def done_ids(path, column):
    return set(pd.read_csv(path)[column]) if path.exists() else set()
