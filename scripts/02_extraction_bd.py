"""
Projet ETICS (P02, Sujet 3) - Etape 2 : des PDF (non structures) vers une BD structuree.

Entree : documents/pdf/*/*.pdf + documents/ocr_documentcloud/*.txt + documents/catalogue_documents.csv
Sortie : bd/etics.db (SQLite) + un CSV par table dans bd/

Tables
  documents         1 ligne par PDF (metadonnees, methode d'extraction, qualite)
  locuteurs         1 ligne par personne qui parle dans un interrogatoire, avec son role deduit
  repliques         1 ligne par tour de parole (unite d'analyse de la toxicite)
  decisions         1 ligne par decision judiciaire (issue : accordee / rejetee / partielle)
  problemes_qualite problemes rencontres pendant l'extraction, document par document

Usage : python scripts/02_extraction_bd.py   (depuis le dossier "Projet BD Etics")
"""
import csv
import re
import sqlite3
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "documents"
OUT = ROOT / "bd"

MIN_CHARS_PER_PAGE = 300   # en dessous, le PDF est un scan sans couche texte
MIN_LABEL_COUNT = 5        # une etiquette de locuteur doit revenir au moins 5 fois
MIN_TURNS = 20             # en dessous, le decoupage par locuteur a echoue
CHUNK_WORDS = 60           # taille des blocs quand on ne trouve pas les locuteurs

# Lignes parasites : en-tetes de tribunal, pagination, mentions de bande
NOISE = re.compile(
    r"^\s*(case\s+\d|document\s+\d|page\s+\d+(\s+of\s+\d+)?\s*$|page\s+[a-z\-]+\s*$|tape\s+\w+\s*$|"
    r"pageid|filed\s+\d|for official use only|unclassified|\(side [ab] of tape|pause[\. ]*$)", re.I)
LINE_NUMBER = re.compile(r"^\s*\d{1,5}\s*[\|\]\[\(\)/:]*\s*")
LABEL_COLON = re.compile(r"^([A-Z][A-Za-z\.\'\- ]{0,35}?|[QA]\d?)\s*[:;](?:\s+(.*)|\s*)$")  # "NOM: texte" ou "NOM:" seul
LABEL_QA = re.compile(r"^([QA]\d?)[\.:]?\s+(.*)$")
LABEL_ALONE = re.compile(r"^([A-Z][A-Z\.\' ]{2,30}?)(\s*\(cont'?d\))?\s*$")
NOT_A_SPEAKER = re.compile(
    r"^(page|case|date|time|re|tel|fax|phone|location|place|duration|length|subject|address|"
    r"interview|transcribed|reviewed|property|description|status|control|cps file|indictment|"
    r"note|exhibit|attachment|cc|from|to|by|the court|participants|person\s*in\s*ter|pers\s*on|"
    r"trans\s*cribed|tran\s*scribed|recording|yeah|okay|ok|right|um|uh|yes|no|man)\b", re.I)

ENQUETEUR = re.compile(
    r"\b(det|detective|officer|agent|sa[gt]?|special agent|investigator|inv|sgt|sergeant|lt|"
    r"lieutenant|cpl|trooper|deputy|police|ds|dc|captain|capt|chief|fbi|q\d?)\b\.?", re.I)
INTERROGE = re.compile(r"^(a\d?)$", re.I)


def read_text(pdf_path, ocr_path, n_pages):
    """Texte du PDF, ou OCR DocumentCloud si le PDF est un scan sans couche texte."""
    pdf_text = ""
    try:
        with fitz.open(pdf_path) as d:
            pdf_text = "\n".join(p.get_text() for p in d)
    except Exception:
        pass
    if len(pdf_text) >= MIN_CHARS_PER_PAGE * max(n_pages, 1):
        return pdf_text, "couche texte du PDF"
    ocr = ocr_path.read_text(encoding="utf-8", errors="replace") if ocr_path.exists() else ""
    if len(ocr) > len(pdf_text):
        return ocr, "OCR DocumentCloud (PDF scanne)"
    return pdf_text, "couche texte du PDF (faible)"


def clean_lines(text):
    lines = []
    for raw in text.splitlines():
        line = raw.replace(" ", " ").strip()
        if not line or NOISE.search(line):
            continue
        line = LINE_NUMBER.sub("", line).strip()
        if line and not re.fullmatch(r"[\W\d_]+", line):
            lines.append(line)
    return lines


def turns_with(lines, pattern, standalone=False):
    """Decoupe en repliques selon un format d'etiquette ; renvoie [(locuteur, texte)]."""
    candidates = Counter()
    for l in lines:
        m = pattern.match(l)
        if m and not NOT_A_SPEAKER.match(m.group(1)):
            candidates[normalize_label(m.group(1))] += 1
    valid = {k for k, v in candidates.items() if v >= MIN_LABEL_COUNT}
    turns, speaker, buf = [], None, []
    for l in lines:
        m = pattern.match(l)
        label = normalize_label(m.group(1)) if m else None
        if label in valid:
            if speaker and buf:
                turns.append((speaker, " ".join(buf)))
            speaker, buf = label, ([] if standalone or not m.group(2) else [m.group(2)])
        elif speaker:
            buf.append(l)
    if speaker and buf:
        turns.append((speaker, " ".join(buf)))
    return [(s, t.strip()) for s, t in turns if t.strip()]


def normalize_label(label):
    label = re.sub(r"\s+", " ", label.strip(" .")).upper()
    return re.sub(r"^(BY )", "", label)


def split_turns(lines):
    """Essaie les 3 formats de transcription rencontres et garde le meilleur."""
    options = {
        "NOM: texte": turns_with(lines, LABEL_COLON),
        "Q/A": turns_with(lines, LABEL_QA),
        "NOM seul sur sa ligne": turns_with(lines, LABEL_ALONE, standalone=True),
    }
    fmt, turns = max(options.items(), key=lambda kv: (len({s for s, _ in kv[1]}) >= 2, len(kv[1])))
    if len(turns) >= MIN_TURNS:
        return fmt, turns
    words = " ".join(lines).split()   # repli : blocs de texte sans locuteur
    return "aucun locuteur detecte (blocs)", [
        ("INCONNU", " ".join(words[i:i + CHUNK_WORDS])) for i in range(0, len(words), CHUNK_WORDS)]


def assign_roles(turns, title):
    """Role de chaque locuteur : nom present dans le titre du document (= personne interrogee),
    puis mots-cles (DET, AGENT, Q...), puis, a defaut, part de questions posees."""
    title_words = {w for w in re.findall(r"[a-z]{3,}", title.lower())}
    stats = {}
    for s, t in turns:
        st = stats.setdefault(s, {"n": 0, "q": 0, "mots": 0})
        st["n"] += 1
        st["q"] += "?" in t
        st["mots"] += len(t.split())
    roles = {}
    for s, st in stats.items():
        if s == "INCONNU":
            roles[s] = "inconnu"
        elif set(re.findall(r"[a-z]{3,}", s.lower())) & title_words:
            roles[s] = "interroge"
        elif ENQUETEUR.search(s):
            roles[s] = "enqueteur"
        elif INTERROGE.match(s):
            roles[s] = "interroge"
        else:
            roles[s] = "enqueteur" if st["q"] / st["n"] >= 0.35 else "interroge"
    if "enqueteur" not in roles.values() and len(stats) > 1:
        top = max((s for s in stats if s != "INCONNU"), key=lambda s: stats[s]["q"] / stats[s]["n"])
        roles[top] = "enqueteur"
    return roles, stats


# Schema relationnel : cles primaires et cles etrangeres declarees
SCHEMA = """
CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY, type_document TEXT NOT NULL, documentcloud_id INTEGER, titre TEXT,
    nb_pages INTEGER, source_declaree TEXT, url_page TEXT, url_pdf TEXT, fichier_local TEXT,
    date_collecte TEXT, methode_extraction TEXT, nb_mots INTEGER, format_transcription TEXT,
    nb_locuteurs INTEGER, nb_repliques INTEGER, exploitable INTEGER);
CREATE TABLE locuteurs (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id), locuteur TEXT NOT NULL, role TEXT,
    nb_repliques INTEGER, nb_mots INTEGER, part_questions REAL,
    PRIMARY KEY (doc_id, locuteur));
CREATE TABLE repliques (
    replique_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(doc_id), rang INTEGER,
    locuteur TEXT NOT NULL, role TEXT, texte TEXT NOT NULL, nb_mots INTEGER, est_question INTEGER,
    FOREIGN KEY (doc_id, locuteur) REFERENCES locuteurs(doc_id, locuteur));
CREATE TABLE decisions (
    doc_id TEXT PRIMARY KEY REFERENCES documents(doc_id), nature TEXT, issue_requete TEXT,
    phrase_conclusion TEXT, mentionne_miranda INTEGER, mentionne_involontaire INTEGER,
    mentionne_menaces INTEGER, mentionne_promesses INTEGER, mentionne_tromperie INTEGER);
CREATE TABLE problemes_qualite (
    probleme_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    probleme TEXT, detail TEXT);
CREATE INDEX ix_rep_doc ON repliques(doc_id);
"""

DECISION_OUTCOME = re.compile(
    r"(motion[^.]{0,250}?\b(?:is|be|are|was|hereby|shall be)\b[^.]{0,40}?\b"
    r"(granted in part|denied in part|granted|denied|sustained|overruled))", re.I | re.S)


COURT_VERB = re.compile(
    r"(\b(grants?|denies|deny|defers ruling on|recommends? that[^.]{0,60}?be (?:granted|denied))\b"
    r"[^.;]{0,120}?motion to suppress[^.;]{0,60})", re.I | re.S)


def decision_outcome(text):
    """Issue de la requete : derniere formule de conclusion trouvee (la decision est en fin de texte)."""
    hits = [(m.start(), m.group(1), m.group(2).lower()) for m in DECISION_OUTCOME.finditer(text)]
    hits += [(m.start(), m.group(1), m.group(2).lower()) for m in COURT_VERB.finditer(text)]
    if not hits:
        return "indeterminee", ""
    _, phrase, verdict = max(hits)
    if "part" in verdict:
        issue = "partielle"
    elif "defer" in verdict:
        issue = "reportee"
    elif "grant" in verdict or verdict == "sustained":
        issue = "accordee"
    else:
        issue = "rejetee"
    return issue, re.sub(r"\s+", " ", phrase)[:300]


def main():
    OUT.mkdir(exist_ok=True)
    catalogue = list(csv.DictReader(open(DOCS / "catalogue_documents.csv", encoding="utf-8")))
    documents, locuteurs, repliques, decisions, problemes = [], [], [], [], []

    for c in catalogue:
        doc_id, n_pages = c["doc_id"], int(c["nb_pages"] or 0)
        text, method = read_text(ROOT / c["fichier_local"], DOCS / "ocr_documentcloud" / f"{doc_id}.txt", n_pages)
        lines = clean_lines(text)
        n_words = sum(len(l.split()) for l in lines)

        def probleme(kind, detail):
            problemes.append({"doc_id": doc_id, "probleme": kind, "detail": detail})

        if "OCR" in method:
            probleme("PDF scanne sans texte", "texte recupere par l'OCR de DocumentCloud (erreurs de lecture possibles)")
        if n_words < 200:
            probleme("texte inexploitable", f"{n_words} mots extraits")
        if re.search(r"\[?(redacted|caviard)", text, re.I) or "█" in text:
            probleme("passages caviardes", "informations masquees dans le document")

        doc = {**{k: c[k] for k in ("doc_id", "type_document", "documentcloud_id", "titre", "nb_pages",
                                    "source_declaree", "url_page", "url_pdf", "fichier_local", "date_collecte")},
               "methode_extraction": method, "nb_mots": n_words, "format_transcription": "",
               "nb_locuteurs": 0, "nb_repliques": 0, "exploitable": n_words >= 200}

        if c["type_document"] == "interrogatoire" and doc["exploitable"]:
            fmt, turns = split_turns(lines)
            roles, stats = assign_roles(turns, c["titre"])
            if fmt.startswith("aucun"):
                probleme("locuteurs non identifies", "format de transcription non reconnu : texte decoupe en blocs")
            short = [s for s in stats if len(s) <= 3 and s not in ("Q", "A", "Q1", "Q2", "A1", "A2")]
            if short:
                probleme("locuteurs abreges", ", ".join(sorted(short)[:6]))
            doc.update(format_transcription=fmt, nb_locuteurs=len(stats), nb_repliques=len(turns))
            for s, st in stats.items():
                locuteurs.append({"doc_id": doc_id, "locuteur": s, "role": roles[s], "nb_repliques": st["n"],
                                  "nb_mots": st["mots"], "part_questions": round(st["q"] / st["n"], 2)})
            for i, (s, t) in enumerate(turns, 1):
                repliques.append({"replique_id": f"{doc_id}_R{i:05d}", "doc_id": doc_id, "rang": i,
                                  "locuteur": s, "role": roles[s], "texte": t, "nb_mots": len(t.split()),
                                  "est_question": "?" in t})
        elif c["type_document"] == "decision" and doc["exploitable"]:
            # Une requete d'avocat ("Motion to Suppress") demande, elle ne decide pas : pas d'issue a lire
            is_ruling = bool(re.search(r"order|ruling", c["titre"], re.I))
            issue, phrase = decision_outcome(" ".join(lines)) if is_ruling else ("sans objet (requete)", "")
            low = text.lower()
            decisions.append({
                "doc_id": doc_id, "nature": "decision du juge" if is_ruling else "requete d'une partie",
                "issue_requete": issue, "phrase_conclusion": phrase,
                "mentionne_miranda": "miranda" in low,
                "mentionne_involontaire": bool(re.search(r"involuntar|coerc", low)),
                "mentionne_menaces": bool(re.search(r"\bthreat", low)),
                "mentionne_promesses": bool(re.search(r"\bpromis", low)),
                "mentionne_tromperie": bool(re.search(r"deceiv|decept|\blied\b|false evidence|trick", low)),
            })
            if issue == "indeterminee":
                probleme("issue non trouvee", "la phrase de conclusion n'a pas ete reconnue")
        documents.append(doc)

    tables = {"documents": pd.DataFrame(documents), "locuteurs": pd.DataFrame(locuteurs),
              "repliques": pd.DataFrame(repliques), "decisions": pd.DataFrame(decisions),
              "problemes_qualite": pd.DataFrame(problemes)}

    # Controles d'integrite
    d, r = tables["documents"], tables["repliques"]
    assert d.doc_id.is_unique and r.replique_id.is_unique
    assert set(r.doc_id) <= set(d.doc_id)
    assert (r.texte.str.len() > 0).all()

    db = OUT / "etics.db"
    db.unlink(missing_ok=True)
    with sqlite3.connect(db) as con:
        con.execute("PRAGMA foreign_keys = ON")   # SQLite verifie les cles etrangeres a l'insertion
        con.executescript(SCHEMA)
        for name, df in tables.items():          # ordre parent -> enfant
            df.to_sql(name, con, index=False, if_exists="append")
    for name, df in tables.items():
        try:
            df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8")
        except PermissionError:                  # fichier ouvert dans Excel
            print(f"  ATTENTION : {name}.csv est ouvert ailleurs (Excel ?), CSV non mis a jour")

    print(f"BD ecrite : {db}")
    for name, df in tables.items():
        print(f"  {name:18s} {len(df):6d} lignes")
    print("\nInterrogatoires :")
    print(d[d.type_document == "interrogatoire"][["doc_id", "methode_extraction", "format_transcription",
                                                  "nb_locuteurs", "nb_repliques", "exploitable"]].to_string(index=False))
    if len(tables["decisions"]):
        print("\nIssue des decisions :", tables["decisions"].issue_requete.value_counts().to_dict())
    print("\nProblemes :", tables["problemes_qualite"].probleme.value_counts().to_dict())


if __name__ == "__main__":
    main()
