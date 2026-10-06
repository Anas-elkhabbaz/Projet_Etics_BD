# ETICS – Toxicité éthique dans les interrogatoires policiers (P02, Sujet 3)

Des documents non structurés (PDF) vers une base de données structurée, puis une évaluation de toxicité.

## Structure du dossier
```
Projet BD Etics/
├── README.md                      ce fichier
├── consignes/                     sujet du projet (PDF du prof)
├── documents/
│   ├── pdf/interrogatoire/        41 PDF INT001…INT041 (documents d'entrée)
│   ├── pdf/decision/              29 PDF DEC001…DEC029
│   ├── ocr_documentcloud/         texte OCR de chaque PDF (pour les scans)
│   └── catalogue_documents.csv    titre, source, URL, pages de chaque PDF
├── scripts/
│   ├── 01_collecte_documents.py   télécharge les PDF
│   ├── 02_extraction_bd.py        PDF -> tables structurées (CSV)
│   ├── 03_moderation_toxicite.py  omni-moderation-latest -> verdicts
│   ├── 04_chargement_oracle.py    CSV -> base Oracle (schéma ETICS)
│   ├── 05_llm_fiches.py           LLM : fiche structurée + rôles des locuteurs
│   ├── 06_llm_tactiques_decision.py  LLM : tactiques non éthiques + décision finale
│   └── llm_commun.py              appel du LLM (JSON), reprise après interruption
├── bd/                            une table par fichier CSV
├── oracle/                        scripts SQL : utilisateur, schéma (clés), données
└── archive_crime/                 ancienne piste C.R.I.M.E. (abandonnée, gardée pour mémoire)
```

## Documents en entrée
Source : [DocumentCloud](https://www.documentcloud.org), où journalistes et tribunaux publient des pièces judiciaires réelles.

| Type | Nb | Contenu |
|---|---|---|
| `interrogatoire` | 41 PDF (~2 500 pages) | transcriptions d'interrogatoires par la police ou le FBI (Kouri Richins, Glossip/Sneed, Reality Winner, Knoxville 2007…) |
| `decision` | 29 PDF | décisions de juges et requêtes d'avocats sur la recevabilité d'aveux (« motion to suppress statements ») |

## Chaîne de traitement
Les PDF ne sont pas versionnés sur GitHub (trop volumineux) : `01_collecte_documents.py` les retélécharge dans `documents/pdf/`.

```
python scripts/01_collecte_documents.py    # télécharge les PDF + l'OCR DocumentCloud -> documents/
python scripts/02_extraction_bd.py         # PDF -> tables structurées dans bd/*.csv
python scripts/03_moderation_toxicite.py   # omni-moderation-latest -> scores + verdicts
python scripts/05_llm_fiches.py            # LLM -> fiche par interrogatoire + rôles des locuteurs
python scripts/06_llm_tactiques_decision.py  # LLM -> tactiques non éthiques + décision finale
python scripts/04_chargement_oracle.py     # crée le schéma ETICS dans Oracle et charge toutes les tables
```
Les étapes 3, 5 et 6 demandent une clé OpenAI : `$env:OPENAI_API_KEY = "sk-..."` (PowerShell). Elle reprend où elle s'est arrêtée si elle est interrompue. Pour un test rapide : `--docs INT008`.

## Base de données Oracle (PDB `FREEPDB1`, schéma `ETICS`)
Dans SQL Developer, avec la connexion SYSTEM sur FREEPDB1 : *Autres utilisateurs > ETICS > Tables*, ou `SELECT * FROM etics.repliques;`.
Le schéma est créé sans mot de passe. Pour s'y connecter directement : `ALTER USER etics IDENTIFIED BY "mot_de_passe";`.
Sans Python, on peut exécuter `oracle/00_utilisateur.sql`, `01_schema.sql` puis `02_donnees.sql` dans SQL Developer (F5).

| Table | Grain | Clé primaire | Clés étrangères |
|---|---|---|---|
| `documents` | 1 PDF | `doc_id` | – |
| `locuteurs` | 1 personne dans un interrogatoire | (`doc_id`, `locuteur`) | `doc_id` → documents |
| `repliques` | 1 tour de parole | `replique_id` | `doc_id` → documents ; (`doc_id`, `locuteur`) → locuteurs |
| `decisions` | 1 décision judiciaire | `doc_id` | `doc_id` → documents |
| `problemes_qualite` | 1 problème rencontré | `probleme_id` | `doc_id` → documents |
| `moderation_repliques` | 1 réplique analysée | `replique_id` | `replique_id` → repliques ; `doc_id` → documents |
| `toxicite_documents` | 1 interrogatoire | `doc_id` | `doc_id` → documents ; `replique_la_plus_toxique` → repliques |
| `fiches_llm` | 1 interrogatoire | `doc_id` | `doc_id` → documents |
| `roles_llm` | 1 locuteur | (`doc_id`, `locuteur`) | (`doc_id`, `locuteur`) → locuteurs |
| `tactiques_llm` | 1 tactique repérée | `tactique_id` | `replique_id` → repliques ; `doc_id` → documents |
| `decision_finale` | 1 interrogatoire | `doc_id` | `doc_id` → documents |

```
documents 1──n locuteurs 1──n repliques 1──1 moderation_repliques
documents 1──n repliques
documents 1──1 decisions        documents 1──n problemes_qualite
documents 1──1 toxicite_documents   documents 1──1 fiches_llm   documents 1──1 decision_finale
locuteurs 1──1 roles_llm           repliques 1──n tactiques_llm
```

## Problèmes rencontrés (table `problemes_qualite`)
- 25 PDF scannés sans couche texte : on utilise l'OCR fourni par DocumentCloud, qui contient des erreurs de lecture.
- Formats de transcription hétérogènes (`NOM: texte`, `Q/A`, nom seul sur une ligne). Pour 10 documents, aucun locuteur n'est reconnu et le texte est découpé en blocs.
- Locuteurs abrégés (RW, SAT, VC…), donc le rôle est déduit par heuristique (nom dans le titre, mots-clés DET/AGENT, part de questions).
- Bruit : numéros de ligne, en-têtes de tribunal, pagination, passages caviardés.

## Où intervient le LLM
| Étape | Sans LLM (règles) | Avec LLM |
|---|---|---|
| Structuration | 02 : regex pour découper les répliques et deviner les rôles | 05 : le LLM lit chaque interrogatoire et remplit une fiche JSON (personne interrogée, statut, agence, date, infraction, droits Miranda lus, avocat demandé), et corrige le rôle de chaque locuteur |
| Toxicité | 03 : omni-moderation note la toxicité verbale (insultes, menaces, haine) | 06 : le LLM classe chaque réplique d'enquêteur selon une grille éthique (menace, fausse promesse, mensonge sur les preuves, minimisation, pression psychologique, humiliation, non-respect des droits, discrimination), avec une gravité de 1 à 3, une justification et une citation |

La chaîne 01 → 06 fonctionne comme un **agent** au sens de l'énoncé : elle lit chaque fichier, identifie l'information, la structure en JSON et l'écrit dans la base, sans intervention.

**Décision finale** (`decision_finale`) : **toxique** si une tactique de gravité 3 ou un verdict « toxique » de la modération ; **mauvais** si une tactique de gravité 2 ou un verdict « mauvais » ; **bon** sinon.

## Méthode d'évaluation de la modération (étape 3)
- On évalue le **comportement de l'enquêteur**. Un suspect qui raconte un crime fait monter le score « violence » sans que l'interrogatoire soit contraire à l'éthique.
- Catégories prises en compte pour l'enquêteur : harassment, harassment/threatening, hate, hate/threatening, violence.
- **toxique** : au moins une réplique d'enquêteur signalée par le modèle (score ≥ 0,5), ou plus de 2 % de répliques ≥ 0,5.
- **mauvais** : rien de signalé, mais au moins une réplique ≥ 0,2.
- **bon** : sinon.
- Limite : le modèle détecte le langage toxique (insultes, menaces, haine), pas les tactiques non éthiques formulées poliment (fausses promesses, mensonge sur les preuves). La table `decisions` montre ce que les juges retiennent comme coercitif.

## Prochaines étapes
1. Lancer l'étape 3 avec une clé OpenAI, puis lire `bd/toxicite_documents.csv`.
2. Vérifier à la main 5 à 10 verdicts (lire les répliques les plus toxiques) pour valider ou ajuster les seuils.
3. Lancer les étapes 5 et 6 (LLM), puis comparer sur une dizaine d'interrogatoires la décision du LLM avec une lecture humaine.
4. Rédiger le rapport court et les diapositives (soutenance de 10 à 15 min) : documents d'entrée, architecture de la BD, problèmes rencontrés, méthode et résultats.
