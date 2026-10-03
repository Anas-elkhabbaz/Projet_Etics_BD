"""
Projet ETICS (P02, Sujet 3) - Etape 1 : collecte des documents sources (PDF).

Source : DocumentCloud (https://www.documentcloud.org), plateforme publique ou journalistes
et tribunaux publient des pieces judiciaires. API publique, sans compte.

Deux types de documents, selectionnes a la main apres recherche (liste ci-dessous) :
  interrogatoire : transcription d'un interrogatoire / audition par la police ou le FBI
  decision       : requete ou decision judiciaire sur la recevabilite d'aveux
                   ("motion to suppress statements"), qui sert de reference pour l'evaluation

Sorties :
  documents/pdf/<type>/<doc_id>.pdf
  documents/ocr_documentcloud/<doc_id>.txt   (texte OCR fourni par DocumentCloud)
  documents/catalogue_documents.csv   (metadonnees + tracabilite de chaque fichier)

Usage : python scripts/01_collecte_documents.py   (depuis le dossier "Projet BD Etics")
"""
import csv
import json
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "documents"
API = "https://api.www.documentcloud.org/api/documents/{}/"
UA = {"User-Agent": "curl/8.0"}

# Identifiants DocumentCloud retenus apres tri manuel des resultats de recherche
INTERROGATOIRES = [
    21179915,  # Driskill Interrogation Transcript (Texas)
    4334950,   # Reality Winner (FBI, 2017)
    25978978,  # Adam Ball (FBI, temoin)
    517648,    # Vanessa Coleman (Knoxville, 2007)
    539855,    # Letalvis Cobbins (Knoxville, 2007)
    538394,    # Lemaricus Davidson (Knoxville, 2007)
    539919,    # George Thomas (Lebanon, Ky.)
    23842693,  # Kouri Richins (Utah)
    2424987,   # Justin Sneed (affaire Glossip)
    2395793,   # Richard Glossip, 8 janv. 1997
    2395795,   # Richard Glossip, 9 janv. 1997
    6603507,   # Alexander
    1376707,   # Justin Bourque
    3860831,   # Bill Cosby (2005)
    2730291,   # Carrie Kain
    284251,    # Dewey Pressley
    289707,    # Dustin Paxton
    1379101,   # Dorian Johnson (Ferguson, temoin)
    25919,     # Bruce Elliott, 1er interrogatoire (Wichita)
    25920,     # Bruce Elliott, 2e interrogatoire
    231515,    # Gabriel Morris (Oregon)
    231514,    # Jessica Morris (Oregon)
    4368046,   # Jerry Lawler, Clark County
    4368047,   # Jerry Lawler, Louisville
    4390567,   # Jesse Osborne (aveux)
    3383350,   # Jimmy Snuka (1983)
    395841,    # John Terry
    4051469,   # Sunset Bay
    2940916,   # Interview SVPD 2012
    24658309,  # Boosie
    2780577,   # Officer Dustin Schwarze
    695682,    # Thomas Sullivan Jr.
    3219220,   # M.D. (Cole County)
    20685736,  # Wagner
    22627510,  # Ruben Flores
    20490838,  # Haywood (partiel)
    6810638,   # CCSO Detective Ritchie (2007)
    26098956,  # Halstrom (Cowlitz County)
    6211743,   # Charissa Ray (Bisbee PD)
    6211734,   # Manuel Moots (Bisbee PD)
    20616554,  # Obina Onyiah (interrogatoire + audience)
]
DECISIONS = [
    6589976, 7331285, 7208912, 7016632, 6177177, 6006796, 4756698, 7032200, 5028014,
    4433103, 6777088, 6023015, 7331286, 6660910, 6609703, 4433302, 7335894, 7037955,
    5677666, 4613999,           # "Order on Motion to Suppress Statements" (U.S. District Court)
    2432434,   # Ruling on Involuntary Confession (California Court of Appeals)
    20073917,  # Order denying motion to suppress evidence, statements
    20073926,  # Order to Suppress
    23179243,  # Arterberry suppression order
    613289,    # David Robinson Motion to Suppress Statements
    25477263,  # Roske Motion to Suppress Statements
    1513100,   # Tsarnaev Motion to Suppress Statements
    4108297,   # Courtier Motion to Suppress
    24658327,  # USA opposition to Boosie's motion to suppress
]


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def download(url, dest):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        dest.write_bytes(r.read())


def main():
    rows = []
    for doc_type, ids, prefix in (("interrogatoire", INTERROGATOIRES, "INT"),
                                  ("decision", DECISIONS, "DEC")):
        folder = OUT / "pdf" / doc_type
        folder.mkdir(parents=True, exist_ok=True)
        for n, dc_id in enumerate(ids, 1):
            doc_id = f"{prefix}{n:03d}"
            try:
                meta = get_json(API.format(dc_id))
                pdf_url = f"https://s3.documentcloud.org/documents/{dc_id}/{meta['slug']}.pdf"
                dest = folder / f"{doc_id}.pdf"
                if not dest.exists():
                    download(pdf_url, dest)
                # Texte OCR produit par DocumentCloud : indispensable pour les PDF scannes sans couche texte
                ocr = OUT / "ocr_documentcloud" / f"{doc_id}.txt"
                ocr.parent.mkdir(exist_ok=True)
                if not ocr.exists():
                    download(pdf_url[:-4] + ".txt", ocr)
                status = "ok"
            except Exception as e:  # document retire, acces refuse...
                meta, pdf_url, dest, status = {}, "", None, f"echec: {e}"
            rows.append({
                "doc_id": doc_id, "type_document": doc_type, "documentcloud_id": dc_id,
                "titre": meta.get("title", ""), "nb_pages": meta.get("page_count", ""),
                "source_declaree": meta.get("source") or "", "langue": meta.get("language", ""),
                "date_publication": (meta.get("created_at") or "")[:10],
                "url_page": meta.get("canonical_url", ""), "url_pdf": pdf_url,
                "fichier_local": str(dest.relative_to(ROOT)) if dest else "",
                "taille_ko": round(dest.stat().st_size / 1024) if dest and dest.exists() else 0,
                "date_collecte": date.today().isoformat(), "statut": status,
            })
            print(doc_id, status, rows[-1]["titre"][:60])
            time.sleep(0.3)

    with open(OUT / "catalogue_documents.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    ok = sum(r["statut"] == "ok" for r in rows)
    print(f"\n{ok}/{len(rows)} documents telecharges -> {OUT / 'catalogue_documents.csv'}")


if __name__ == "__main__":
    main()
