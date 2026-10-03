"""
Projet ETICS (P02, Sujet 3) - Etape 3 : evaluation de la toxicite avec omni-moderation-latest (OpenAI).

Entree : bd/repliques.csv et bd/documents.csv (produits par 02_extraction_bd.py)
Sortie : deux nouvelles tables en CSV dans bd/ (chargees ensuite dans Oracle par 04_chargement_oracle.py)
  moderation_repliques   scores des 13 categories du modele pour chaque replique
  toxicite_documents     1 ligne par interrogatoire : indicateurs + verdict bon / mauvais / toxique

Methode (hypotheses de depart)
  - On juge le comportement des ENQUETEURS : un suspect qui decrit un meurtre produit des scores
    "violence" eleves sans que l'interrogatoire soit contraire a l'ethique.
  - Categories retenues pour l'enqueteur : harassment, harassment/threatening, hate,
    hate/threatening, violence (menaces).
  - toxique : au moins une replique d'enqueteur signalee (flagged) par le modele sur ces categories,
              ou plus de SEUIL_TAUX des repliques d'enqueteur au-dessus de SEUIL_FORT.
  - mauvais : aucun signalement, mais au moins une replique d'enqueteur au-dessus de SEUIL_MOYEN.
  - bon     : sinon.
  Quand les locuteurs n'ont pas pu etre identifies, toutes les repliques sont jugees
  et le verdict est marque "fiabilite faible".

Prerequis : pip install openai pandas
            cle API dans la variable d'environnement OPENAI_API_KEY
            (PowerShell : $env:OPENAI_API_KEY = "sk-...")

Usage (depuis le dossier "Projet BD Etics") :
  python scripts/03_moderation_toxicite.py                 # tout le corpus (reprend la ou il s'est arrete)
  python scripts/03_moderation_toxicite.py --docs INT008   # test sur un document
  python scripts/03_moderation_toxicite.py --limite 200    # test sur 200 repliques
  python scripts/03_moderation_toxicite.py --verdict-seul  # recalcule les verdicts sans appeler l'API
  puis : python scripts/04_chargement_oracle.py            # recharge la BD Oracle avec les resultats
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BD = ROOT / "bd"
MODERATION_CSV = BD / "moderation_repliques.csv"
MODEL = "omni-moderation-latest"
BATCH = 32            # repliques envoyees par requete
MAX_CHARS = 4000      # les blocs tres longs sont tronques

CATEGORIES = ["harassment", "harassment/threatening", "hate", "hate/threatening", "illicit",
              "illicit/violent", "self-harm", "self-harm/intent", "self-harm/instructions",
              "sexual", "sexual/minors", "violence", "violence/graphic"]
CATS_ENQUETEUR = ["harassment", "harassment/threatening", "hate", "hate/threatening", "violence"]
SEUIL_FORT = 0.5
SEUIL_MOYEN = 0.2
SEUIL_TAUX = 0.02


def col(cat):
    return "score_" + cat.replace("/", "_").replace("-", "_")


def moderate(client, texts):
    """Appel API avec reprise automatique en cas de limite de debit ou d'erreur passagere."""
    for attempt in range(6):
        try:
            return client.moderations.create(model=MODEL, input=texts).results
        except Exception as e:
            wait = 2 ** attempt
            print(f"  erreur API ({type(e).__name__}: {e}) - nouvel essai dans {wait}s")
            time.sleep(wait)
    raise RuntimeError("API de moderation indisponible apres 6 essais")


def score_repliques(docs, limite):
    from openai import OpenAI
    client = OpenAI()  # lit OPENAI_API_KEY

    rep = pd.read_csv(BD / "repliques.csv")
    doc = pd.read_csv(BD / "documents.csv")
    rep = rep[rep.doc_id.isin(doc[doc.type_document == "interrogatoire"].doc_id)]
    deja = set(pd.read_csv(MODERATION_CSV).replique_id) if MODERATION_CSV.exists() else set()
    todo = rep[~rep.replique_id.isin(deja)]       # reprise : on saute ce qui est deja analyse
    if docs:
        todo = todo[todo.doc_id.isin(docs)]
    if limite:
        todo = todo.head(limite)
    print(f"{len(todo)} repliques a analyser avec {MODEL}")

    columns = ["replique_id", "doc_id", "role", "flagged", *[col(c) for c in CATEGORIES],
               "categorie_max", "score_max", "modele", "date_analyse"]
    for start in range(0, len(todo), BATCH):
        chunk = todo.iloc[start:start + BATCH]
        results = moderate(client, [str(t)[:MAX_CHARS] for t in chunk.texte])
        rows = []
        for (_, r), res in zip(chunk.iterrows(), results):
            scores = res.category_scores.model_dump(by_alias=True)
            vals = [float(scores.get(c) or 0.0) for c in CATEGORIES]
            best = max(range(len(CATEGORIES)), key=lambda i: vals[i])
            rows.append((r.replique_id, r.doc_id, r.role, int(res.flagged), *vals,
                         CATEGORIES[best], vals[best], MODEL, datetime.now().isoformat(timespec="seconds")))
        pd.DataFrame(rows, columns=columns).to_csv(MODERATION_CSV, mode="a", index=False, encoding="utf-8",
                                                   header=not MODERATION_CSV.exists())
        done = min(start + BATCH, len(todo))
        if done % (BATCH * 20) == 0 or done == len(todo):
            print(f"  {done}/{len(todo)}")


def verdicts():
    if not MODERATION_CSV.exists():
        sys.exit("Aucune replique analysee : lancer d'abord le script sans --verdict-seul.")
    m = pd.read_csv(MODERATION_CSV).drop_duplicates("replique_id", keep="last")
    docs = pd.read_csv(BD / "documents.csv")
    docs = docs[docs.type_document == "interrogatoire"][["doc_id", "titre", "format_transcription"]]
    cats = [col(c) for c in CATS_ENQUETEUR]
    m["score_enqueteur"] = m[cats].max(axis=1)
    out = []
    for doc_id, g in m.groupby("doc_id"):
        enq = g[g.role == "enqueteur"]
        fiable = len(enq) > 0
        cible = enq if fiable else g          # sans locuteurs identifies : toutes les repliques
        nb = len(cible)
        signalees = int(((cible.flagged == 1) & (cible.score_enqueteur >= SEUIL_FORT)).sum())
        fortes = int((cible.score_enqueteur >= SEUIL_FORT).sum())
        moyennes = int((cible.score_enqueteur >= SEUIL_MOYEN).sum())
        if signalees > 0 or (nb and fortes / nb > SEUIL_TAUX):
            verdict = "toxique"
        elif moyennes > 0:
            verdict = "mauvais"
        else:
            verdict = "bon"
        row = {"doc_id": doc_id, "verdict": verdict,
               "fiabilite": "normale" if fiable else "faible (locuteurs non identifies)",
               "nb_repliques_jugees": nb, "nb_signalees": signalees,
               "nb_score_fort": fortes, "nb_score_moyen": moyennes,
               "taux_score_fort": round(fortes / nb, 4) if nb else 0,
               "score_max_enqueteur": round(float(cible.score_enqueteur.max()), 4) if nb else 0}
        for c in CATS_ENQUETEUR:   # profil de l'enqueteur, categorie par categorie
            row[f"max_{col(c)[6:]}_enqueteur"] = round(float(cible[col(c)].max()), 4) if nb else 0
        interro = g[g.role == "interroge"]
        row["max_violence_interroge"] = round(float(interro[col("violence")].max()), 4) if len(interro) else None
        row["nb_signalees_tout_locuteur"] = int(g.flagged.sum())
        top = cible.sort_values("score_enqueteur", ascending=False).head(1)
        row["replique_la_plus_toxique"] = top.replique_id.iloc[0] if nb else None
        out.append(row)
    res = docs.merge(pd.DataFrame(out), on="doc_id", how="inner")
    res["modele"] = MODEL
    res["seuils"] = f"fort={SEUIL_FORT}, moyen={SEUIL_MOYEN}, taux={SEUIL_TAUX}"
    res.to_csv(BD / "toxicite_documents.csv", index=False, encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", help="liste de doc_id separes par des virgules (test)")
    ap.add_argument("--limite", type=int, help="nombre maximal de repliques a analyser (test)")
    ap.add_argument("--verdict-seul", action="store_true", help="ne pas appeler l'API, recalculer les verdicts")
    args = ap.parse_args()

    if not args.verdict_seul:
        import os
        if not os.environ.get("OPENAI_API_KEY"):
            sys.exit("OPENAI_API_KEY absente. PowerShell : $env:OPENAI_API_KEY = \"sk-...\"")
        score_repliques(args.docs.split(",") if args.docs else None, args.limite)
    res = verdicts()

    print("\nVerdicts :", res.verdict.value_counts().to_dict())
    print(res[["doc_id", "verdict", "fiabilite", "nb_repliques_jugees", "nb_signalees",
               "score_max_enqueteur"]].to_string(index=False))


if __name__ == "__main__":
    main()
