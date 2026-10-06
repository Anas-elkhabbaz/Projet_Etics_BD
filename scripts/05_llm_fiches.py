"""
Projet ETICS (P02, Sujet 3) - Etape 5 : le LLM lit chaque interrogatoire et remplit sa fiche structuree.

Role du LLM (extraction "texte -> donnees structurees", comme dans l'enonce du projet) :
  - identifier la personne interrogee, son statut (suspect / temoin), l'agence, la date, l'infraction ;
  - dire si les droits (Miranda) ont ete lus, si un avocat a ete demande ou etait present ;
  - attribuer un role a chaque locuteur (enqueteur / interroge / avocat / autre), la ou les regles
    de l'etape 02 n'avaient que des abreviations (RW, SAT, VC...) ;
  - resumer l'interrogatoire en deux phrases.

Entree : bd/documents.csv, bd/locuteurs.csv, bd/repliques.csv
Sortie : bd/fiches_llm.csv (1 ligne par interrogatoire) et bd/roles_llm.csv (1 ligne par locuteur)

Usage : python scripts/05_llm_fiches.py                 (tous les interrogatoires, reprise automatique)
        python scripts/05_llm_fiches.py --docs INT008   (test)
"""
import argparse
import json

import pandas as pd

from llm_commun import BD, MODEL, append_csv, ask_json, client, done_ids

FICHES = BD / "fiches_llm.csv"
ROLES = BD / "roles_llm.csv"
FICHE_COLUMNS = ["doc_id", "personne_interrogee", "statut_personne", "agence", "date_interrogatoire",
                 "infraction", "droits_miranda_lus", "avocat_demande", "avocat_present", "resume", "modele"]
ROLES_LLM = {"enqueteur", "interroge", "avocat", "autre"}

SYSTEM = """Tu es un assistant d'analyse de documents judiciaires.
On te donne le debut de la transcription d'un interrogatoire de police (en anglais) et la liste des
etiquettes de locuteurs trouvees dans le texte. Reponds uniquement en JSON avec ces cles :
{
  "personne_interrogee": "nom ou null",
  "statut_personne": "suspect | temoin | victime | inconnu",
  "agence": "service de police ou agence (ex. FBI) ou null",
  "date_interrogatoire": "AAAA-MM-JJ ou null",
  "infraction": "infraction concernee en quelques mots, ou null",
  "droits_miranda_lus": "oui | non | inconnu",
  "avocat_demande": "oui | non | inconnu",
  "avocat_present": "oui | non | inconnu",
  "resume": "deux phrases en francais",
  "roles": {"ETIQUETTE": "enqueteur | interroge | avocat | autre"}
}
N'invente rien : si l'information n'est pas dans le texte, mets null ou "inconnu".
Donne un role a chaque etiquette de la liste."""


def build_prompt(doc, locs, reps):
    sample = []
    for _, l in locs.iterrows():
        first = reps[reps.locuteur == l.locuteur].head(3).texte.str[:300].tolist()
        sample.append(f"- {l.locuteur} ({l.nb_repliques} repliques) : " + " / ".join(first))
    debut = " ".join(reps.head(40).apply(lambda r: f"{r.locuteur}: {r.texte}", axis=1))[:6000]
    return (f"Titre du document : {doc.titre}\n\nEtiquettes de locuteurs et premieres repliques :\n"
            + "\n".join(sample) + f"\n\nDebut de la transcription :\n{debut}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", help="doc_id separes par des virgules (test)")
    args = ap.parse_args()

    docs = pd.read_csv(BD / "documents.csv")
    docs = docs[(docs.type_document == "interrogatoire") & (docs.exploitable)]
    if args.docs:
        docs = docs[docs.doc_id.isin(args.docs.split(","))]
    locuteurs, repliques = pd.read_csv(BD / "locuteurs.csv"), pd.read_csv(BD / "repliques.csv")
    deja = done_ids(FICHES, "doc_id")
    cli = client()

    for _, doc in docs[~docs.doc_id.isin(deja)].iterrows():
        locs = locuteurs[locuteurs.doc_id == doc.doc_id]
        reps = repliques[repliques.doc_id == doc.doc_id].sort_values("rang")
        out = ask_json(cli, SYSTEM, build_prompt(doc, locs, reps))
        fiche = {c: out.get(c) for c in FICHE_COLUMNS}
        fiche.update(doc_id=doc.doc_id, modele=MODEL)
        roles = out.get("roles") or {}
        role_rows = [{"doc_id": doc.doc_id, "locuteur": l, "role_regles": r,
                      "role_llm": roles.get(l) if roles.get(l) in ROLES_LLM else "autre"}
                     for l, r in zip(locs.locuteur, locs.role)]
        append_csv([fiche], FICHES, FICHE_COLUMNS)
        append_csv(role_rows, ROLES, ["doc_id", "locuteur", "role_regles", "role_llm"])
        print(f"{doc.doc_id} : {fiche['personne_interrogee']} ({fiche['statut_personne']}), "
              f"{sum(r['role_regles'] != r['role_llm'] for r in role_rows)} role(s) corrige(s)")

    if FICHES.exists():
        r = pd.read_csv(ROLES)
        print(f"\nAccord regles / LLM sur les roles : {(r.role_regles == r.role_llm).mean():.0%} des locuteurs")


if __name__ == "__main__":
    main()
