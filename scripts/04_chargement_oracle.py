"""
Projet ETICS (P02, Sujet 3) - Etape 4 : chargement de la BD structuree dans Oracle (schema ETICS).

Entree : les CSV de bd/ (02_extraction_bd.py, et 03_moderation_toxicite.py s'il a tourne)
Sortie : oracle/02_donnees.sql (INSERT generes) + tables remplies dans Oracle, PDB FREEPDB1, schema ETICS

Le script execute avec SQL*Plus, en connexion locale "/ as sysdba" (authentification Windows) :
  oracle/00_utilisateur.sql   cree le schema ETICS s'il n'existe pas
  oracle/01_schema.sql        (re)cree les tables avec cles primaires, etrangeres et contraintes CHECK
  oracle/02_donnees.sql       insere les lignes (genere ici a partir des CSV)

Sans acces "/ as sysdba", ouvrir les trois fichiers dans SQL Developer (connexion SYSTEM sur FREEPDB1)
et les executer dans l'ordre avec F5.

Usage : python scripts/04_chargement_oracle.py              (depuis le dossier "Projet BD Etics")
        python scripts/04_chargement_oracle.py --sans-execution   (genere seulement 02_donnees.sql)
"""
import argparse
import math
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BD = ROOT / "bd"
ORA = ROOT / "oracle"
PDB = "FREEPDB1"

# Ordre parent -> enfant, impose par les cles etrangeres
TABLES = ["documents", "locuteurs", "repliques", "decisions", "problemes_qualite",
          "moderation_repliques", "toxicite_documents"]
DATE_COLUMNS = {"date_collecte"}
CLOB_CHUNK = 500      # caracteres par morceau de CLOB (une ligne SQL*Plus reste courte)
COMMIT_EVERY = 1000


def literal(value, column):
    """Valeur Python -> litteral SQL Oracle."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NULL"
    if isinstance(value, bool) or str(value) in ("True", "False"):
        return "1" if str(value) == "True" else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\r", " ").replace("\n", " ")
    if column in DATE_COLUMNS:
        return f"TO_DATE('{text}', 'YYYY-MM-DD')"
    if len(text) <= CLOB_CHUNK:
        return "'" + text.replace("'", "''") + "'"
    parts = [text[i:i + CLOB_CHUNK].replace("'", "''") for i in range(0, len(text), CLOB_CHUNK)]
    return "\n   TO_CLOB('" + "')\n|| TO_CLOB('".join(parts) + "')"


def generate_inserts():
    lines = ["-- Genere par scripts/04_chargement_oracle.py a partir des CSV de bd/ : ne pas modifier a la main.",
             "SET DEFINE OFF", "SET SQLBLANKLINES ON", "SET FEEDBACK OFF", ""]
    counts = {}
    for table in TABLES:
        path = BD / f"{table}.csv"
        if not path.exists():
            continue                      # tables de toxicite absentes tant que 03 n'a pas tourne
        df = pd.read_csv(path)
        if table == "moderation_repliques":
            df = df.drop_duplicates("replique_id", keep="last")
        cols = ", ".join(df.columns)
        for i, row in enumerate(df.itertuples(index=False), 1):
            values = ", ".join(literal(v, c) for v, c in zip(row, df.columns))
            lines.append(f"INSERT INTO etics.{table} ({cols}) VALUES ({values});")
            if i % COMMIT_EVERY == 0:
                lines.append("COMMIT;")
        lines += ["COMMIT;", ""]
        counts[table] = len(df)
    (ORA / "02_donnees.sql").write_text("\n".join(lines), encoding="utf-8")
    return counts


def run_sqlplus(counts):
    checks = "\n".join(f"SELECT '{t}: ' || COUNT(*) FROM etics.{t};" for t in counts)
    script = f"""WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
ALTER SESSION SET CONTAINER = {PDB};
@00_utilisateur.sql
@01_schema.sql
@02_donnees.sql
SET HEADING OFF PAGESIZE 0 FEEDBACK OFF
{checks}
EXIT
"""
    env = {**os.environ, "NLS_LANG": "AMERICAN_AMERICA.AL32UTF8", "ORACLE_SID": os.environ.get("ORACLE_SID", "FREE")}
    proc = subprocess.run(["sqlplus", "-L", "-S", "/ as sysdba"], input=script, text=True, encoding="utf-8",
                          cwd=ORA, env=env, capture_output=True)
    print(proc.stdout.strip())
    if proc.returncode != 0:
        sys.exit(f"SQL*Plus a echoue (code {proc.returncode}) : {proc.stderr.strip()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sans-execution", action="store_true", help="generer 02_donnees.sql sans lancer SQL*Plus")
    args = ap.parse_args()

    counts = generate_inserts()
    print("oracle/02_donnees.sql genere :", counts)
    if not args.sans_execution:
        run_sqlplus(counts)
        print(f"\nBD chargee dans Oracle : PDB {PDB}, schema ETICS")


if __name__ == "__main__":
    main()
