"""
Projet ETICS (P02, Sujet 3) - Etape 6 : le LLM repere les tactiques non ethiques, puis decision finale.

Pourquoi un LLM en plus d'omni-moderation (etape 03) ? Le modele de moderation ne voit que la
toxicite verbale (insultes, menaces explicites, haine). Les interrogatoires coercitifs sont souvent
polis : fausse promesse de clemence, mensonge sur les preuves, refus d'ecouter une demande d'avocat.
Le LLM lit les repliques avec leur contexte et classe chaque replique d'enqueteur selon cette grille :

  menace                   menace de peine plus lourde, de violence, de consequences pour les proches
  fausse_promesse          promesse de clemence, de liberation, d'aide en echange d'aveux
  mensonge_preuves         preuves inventees ou exagerees ("on a ton ADN", "ton complice a avoue")
  minimisation             minimiser la gravite des faits pour obtenir un aveu
  pression_psychologique   accusation repetee, refus d'entendre les denegations, epuisement
  humiliation_insulte      insulte, moquerie, propos degradants
  non_respect_droits       ignorer une demande d'avocat ou de silence, droits mal expliques
  discrimination           propos sur l'origine, le genre, la religion, le handicap
Gravite : 1 = leger, 2 = net, 3 = grave (coercitif).

Decision finale par interrogatoire (hypotheses de depart) :
  toxique : au moins une tactique de gravite 3, ou verdict "toxique" de la moderation (etape 03)
  mauvais : au moins une tactique de gravite 2, ou verdict "mauvais" de la moderation
  bon     : sinon

Entree : bd/repliques.csv, bd/roles_llm.csv (etape 05, facultatif), bd/toxicite_documents.csv (etape 03, facultatif)
Sortie : bd/tactiques_llm.csv (1 ligne par tactique reperee) et bd/decision_finale.csv (1 ligne par interrogatoire)

Usage : python scripts/06_llm_tactiques_decision.py                 (tout le corpus, reprise automatique)
        python scripts/06_llm_tactiques_decision.py --docs INT008   (test)
        python scripts/06_llm_tactiques_decision.py --decision-seule  (recalcule la decision sans appeler le LLM)
"""
import argparse

import pandas as pd

from llm_commun import BD, MODEL, append_csv, ask_json, client, done_ids

TACTIQUES = BD / "tactiques_llm.csv"
FAITS = BD / "fenetres_llm.csv"        # fenetres deja analysees (pour la reprise)
DECISION = BD / "decision_finale.csv"
WINDOW = 25                            # repliques envoyees ensemble, pour que le LLM ait le contexte
MAX_CHARS = 700
CATEGORIES = {"menace", "fausse_promesse", "mensonge_preuves", "minimisation", "pression_psychologique",
              "humiliation_insulte", "non_respect_droits", "discrimination"}
TACTIQUE_COLUMNS = ["replique_id", "doc_id", "categorie", "gravite", "justification", "citation", "modele"]

SYSTEM = """Tu es un expert en ethique des interrogatoires de police (methodes PEACE et Reid,
jurisprudence sur les aveux involontaires). On te donne une suite de repliques numerotees d'un
interrogatoire (en anglais). Pour chaque replique marquee [A JUGER], dis si l'enqueteur utilise
une tactique non ethique de cette grille :
menace, fausse_promesse, mensonge_preuves, minimisation, pression_psychologique,
humiliation_insulte, non_respect_droits, discrimination.
Gravite : 1 = leger, 2 = net, 3 = grave (coercitif).
Une question normale, meme insistante ou desagreable, n'est PAS une tactique non ethique.
Le contexte (repliques precedentes) sert a juger, par exemple une demande d'avocat ignoree.
Reponds uniquement en JSON :
{"tactiques": [{"replique_id": "...", "categorie": "...", "gravite": 1, "justification": "une phrase en francais", "citation": "extrait court en anglais"}]}
Si aucune replique n'est concernee : {"tactiques": []}"""


def load_repliques(docs):
    reps = pd.read_csv(BD / "repliques.csv")
    if (BD / "roles_llm.csv").exists():          # roles corriges par le LLM a l'etape 05
        roles = pd.read_csv(BD / "roles_llm.csv")[["doc_id", "locuteur", "role_llm"]]
        reps = reps.merge(roles, on=["doc_id", "locuteur"], how="left")
        reps["role"] = reps.role_llm.fillna(reps.role)
    if docs:
        reps = reps[reps.doc_id.isin(docs)]
    return reps.sort_values(["doc_id", "rang"])


def analyse(docs):
    cli = client()
    reps = load_repliques(docs)
    deja = done_ids(FAITS, "fenetre_id")
    for doc_id, g in reps.groupby("doc_id"):
        juger_tout = not (g.role == "enqueteur").any()   # locuteurs inconnus : on juge tout
        for start in range(0, len(g), WINDOW):
            fenetre_id = f"{doc_id}_{start:05d}"
            if fenetre_id in deja:
                continue
            w = g.iloc[start:start + WINDOW]
            a_juger = set(w.replique_id if juger_tout else w[w.role == "enqueteur"].replique_id)
            rows = []
            if a_juger:
                texte = "\n".join(
                    f"[{r.replique_id}] {'[A JUGER] ' if r.replique_id in a_juger else ''}"
                    f"{r.locuteur} ({r.role}) : {str(r.texte)[:MAX_CHARS]}" for r in w.itertuples())
                out = ask_json(cli, SYSTEM, texte)
                for t in out.get("tactiques") or []:
                    if t.get("replique_id") in a_juger and t.get("categorie") in CATEGORIES:
                        rows.append({"replique_id": t["replique_id"], "doc_id": doc_id,
                                     "categorie": t["categorie"], "gravite": int(t.get("gravite") or 1),
                                     "justification": t.get("justification"), "citation": t.get("citation"),
                                     "modele": MODEL})
            append_csv(rows, TACTIQUES, TACTIQUE_COLUMNS)
            append_csv([{"fenetre_id": fenetre_id, "doc_id": doc_id, "nb_tactiques": len(rows)}],
                       FAITS, ["fenetre_id", "doc_id", "nb_tactiques"])
        print(f"{doc_id} analyse")


def decision():
    analyses = pd.read_csv(FAITS).doc_id.unique() if FAITS.exists() else []
    tac = pd.read_csv(TACTIQUES) if TACTIQUES.exists() else pd.DataFrame(columns=TACTIQUE_COLUMNS)
    tac = tac.drop_duplicates(["replique_id", "categorie"])
    mod = pd.read_csv(BD / "toxicite_documents.csv") if (BD / "toxicite_documents.csv").exists() else None
    rows = []
    for doc_id in analyses:
        t = tac[tac.doc_id == doc_id]
        verdict_mod = None
        if mod is not None and doc_id in set(mod.doc_id):
            verdict_mod = mod.loc[mod.doc_id == doc_id, "verdict"].iloc[0]
        g_max = int(t.gravite.max()) if len(t) else 0
        if g_max >= 3 or verdict_mod == "toxique":
            verdict = "toxique"
        elif g_max == 2 or verdict_mod == "mauvais":
            verdict = "mauvais"
        else:
            verdict = "bon"
        raisons = [f"{c} ({n})" for c, n in t.categorie.value_counts().items()]
        rows.append({"doc_id": doc_id, "verdict_final": verdict, "verdict_moderation": verdict_mod,
                     "nb_tactiques": len(t), "gravite_max": g_max,
                     "nb_tactiques_graves": int((t.gravite >= 3).sum()),
                     "tactiques_reperees": ", ".join(raisons) or None, "modele_llm": MODEL})
    res = pd.DataFrame(rows)
    res.to_csv(DECISION, index=False, encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", help="doc_id separes par des virgules (test)")
    ap.add_argument("--decision-seule", action="store_true", help="recalculer la decision sans appeler le LLM")
    args = ap.parse_args()
    if not args.decision_seule:
        analyse(args.docs.split(",") if args.docs else None)
    res = decision()
    if res.empty:
        print("Aucun interrogatoire analyse.")
        return
    print("\nDecision finale :", res.verdict_final.value_counts().to_dict())
    print(res[["doc_id", "verdict_final", "verdict_moderation", "nb_tactiques", "gravite_max",
               "tactiques_reperees"]].to_string(index=False))


if __name__ == "__main__":
    main()
