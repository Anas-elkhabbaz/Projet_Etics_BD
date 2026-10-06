-- Projet ETICS (P02, Sujet 3) - Schema relationnel de la base des interrogatoires.
-- Tables creees dans le schema ETICS ; l'ordre respecte les cles etrangeres (parent avant enfant).

BEGIN
    FOR t IN (SELECT table_name FROM all_tables WHERE owner = 'ETICS' AND table_name IN
              ('DECISION_FINALE', 'TACTIQUES_LLM', 'ROLES_LLM', 'FICHES_LLM',
               'TOXICITE_DOCUMENTS', 'MODERATION_REPLIQUES', 'PROBLEMES_QUALITE', 'DECISIONS',
               'REPLIQUES', 'LOCUTEURS', 'DOCUMENTS')) LOOP
        EXECUTE IMMEDIATE 'DROP TABLE etics.' || t.table_name || ' CASCADE CONSTRAINTS PURGE';
    END LOOP;
END;
/

-- Un PDF source (interrogatoire ou decision de justice)
CREATE TABLE etics.documents (
    doc_id                VARCHAR2(10)   CONSTRAINT pk_documents PRIMARY KEY,
    type_document         VARCHAR2(20)   NOT NULL CONSTRAINT ck_doc_type CHECK (type_document IN ('interrogatoire', 'decision')),
    documentcloud_id      NUMBER(12),
    titre                 VARCHAR2(300),
    nb_pages              NUMBER(6),
    source_declaree       VARCHAR2(300),
    url_page              VARCHAR2(500),
    url_pdf               VARCHAR2(500),
    fichier_local         VARCHAR2(200),
    date_collecte         DATE,
    methode_extraction    VARCHAR2(60),
    nb_mots               NUMBER(9),
    format_transcription  VARCHAR2(60),
    nb_locuteurs          NUMBER(5),
    nb_repliques          NUMBER(7),
    exploitable           NUMBER(1)      CONSTRAINT ck_doc_exploitable CHECK (exploitable IN (0, 1))
);

-- Une personne qui parle dans un interrogatoire
CREATE TABLE etics.locuteurs (
    doc_id          VARCHAR2(10)  NOT NULL CONSTRAINT fk_loc_doc REFERENCES etics.documents (doc_id),
    locuteur        VARCHAR2(100) NOT NULL,
    role            VARCHAR2(20)  CONSTRAINT ck_loc_role CHECK (role IN ('enqueteur', 'interroge', 'inconnu')),
    nb_repliques    NUMBER(7),
    nb_mots         NUMBER(9),
    part_questions  NUMBER(4, 2),
    CONSTRAINT pk_locuteurs PRIMARY KEY (doc_id, locuteur)
);

-- Un tour de parole (unite d'analyse de la toxicite)
CREATE TABLE etics.repliques (
    replique_id   VARCHAR2(20)  CONSTRAINT pk_repliques PRIMARY KEY,
    doc_id        VARCHAR2(10)  NOT NULL CONSTRAINT fk_rep_doc REFERENCES etics.documents (doc_id),
    rang          NUMBER(7),
    locuteur      VARCHAR2(100) NOT NULL,
    role          VARCHAR2(20),
    texte         CLOB          NOT NULL,
    nb_mots       NUMBER(7),
    est_question  NUMBER(1),
    CONSTRAINT fk_rep_loc FOREIGN KEY (doc_id, locuteur) REFERENCES etics.locuteurs (doc_id, locuteur)
);
CREATE INDEX etics.ix_rep_doc ON etics.repliques (doc_id);

-- Une decision de juge (ou requete d'avocat) sur la recevabilite d'aveux
CREATE TABLE etics.decisions (
    doc_id                  VARCHAR2(10) CONSTRAINT pk_decisions PRIMARY KEY
                                         CONSTRAINT fk_dec_doc REFERENCES etics.documents (doc_id),
    nature                  VARCHAR2(40),
    issue_requete           VARCHAR2(40),
    phrase_conclusion       VARCHAR2(400),
    mentionne_miranda       NUMBER(1),
    mentionne_involontaire  NUMBER(1),
    mentionne_menaces       NUMBER(1),
    mentionne_promesses     NUMBER(1),
    mentionne_tromperie     NUMBER(1)
);

-- Un probleme rencontre pendant l'extraction
CREATE TABLE etics.problemes_qualite (
    probleme_id  NUMBER(6)     CONSTRAINT pk_problemes PRIMARY KEY,
    doc_id       VARCHAR2(10)  NOT NULL CONSTRAINT fk_pb_doc REFERENCES etics.documents (doc_id),
    probleme     VARCHAR2(100),
    detail       VARCHAR2(400)
);

-- Scores omni-moderation-latest d'une replique (rempli par 03_moderation_toxicite.py)
CREATE TABLE etics.moderation_repliques (
    replique_id                   VARCHAR2(20) CONSTRAINT pk_moderation PRIMARY KEY
                                               CONSTRAINT fk_mod_rep REFERENCES etics.repliques (replique_id),
    doc_id                        VARCHAR2(10) CONSTRAINT fk_mod_doc REFERENCES etics.documents (doc_id),
    role                          VARCHAR2(20),
    flagged                       NUMBER(1),
    score_harassment              NUMBER,
    score_harassment_threatening  NUMBER,
    score_hate                    NUMBER,
    score_hate_threatening        NUMBER,
    score_illicit                 NUMBER,
    score_illicit_violent         NUMBER,
    score_self_harm               NUMBER,
    score_self_harm_intent        NUMBER,
    score_self_harm_instructions  NUMBER,
    score_sexual                  NUMBER,
    score_sexual_minors           NUMBER,
    score_violence                NUMBER,
    score_violence_graphic        NUMBER,
    categorie_max                 VARCHAR2(40),
    score_max                     NUMBER,
    modele                        VARCHAR2(40),
    date_analyse                  VARCHAR2(20)
);

-- Verdict par interrogatoire : bon / mauvais / toxique
CREATE TABLE etics.toxicite_documents (
    doc_id                             VARCHAR2(10) CONSTRAINT pk_toxicite PRIMARY KEY
                                                    CONSTRAINT fk_tox_doc REFERENCES etics.documents (doc_id),
    titre                              VARCHAR2(300),
    format_transcription               VARCHAR2(60),
    verdict                            VARCHAR2(10) CONSTRAINT ck_tox_verdict CHECK (verdict IN ('bon', 'mauvais', 'toxique')),
    fiabilite                          VARCHAR2(60),
    nb_repliques_jugees                NUMBER(7),
    nb_signalees                       NUMBER(7),
    nb_score_fort                      NUMBER(7),
    nb_score_moyen                     NUMBER(7),
    taux_score_fort                    NUMBER,
    score_max_enqueteur                NUMBER,
    max_harassment_enqueteur           NUMBER,
    max_harassment_threatening_enqueteur NUMBER,
    max_hate_enqueteur                 NUMBER,
    max_hate_threatening_enqueteur     NUMBER,
    max_violence_enqueteur             NUMBER,
    max_violence_interroge             NUMBER,
    nb_signalees_tout_locuteur         NUMBER(7),
    replique_la_plus_toxique           VARCHAR2(20) CONSTRAINT fk_tox_rep REFERENCES etics.repliques (replique_id),
    modele                             VARCHAR2(40),
    seuils                             VARCHAR2(100)
);

-- Fiche remplie par le LLM pour chaque interrogatoire (05_llm_fiches.py)
CREATE TABLE etics.fiches_llm (
    doc_id               VARCHAR2(10)  CONSTRAINT pk_fiches PRIMARY KEY
                                       CONSTRAINT fk_fiche_doc REFERENCES etics.documents (doc_id),
    personne_interrogee  VARCHAR2(200),
    statut_personne      VARCHAR2(20),
    agence               VARCHAR2(200),
    date_interrogatoire  VARCHAR2(20),
    infraction           VARCHAR2(300),
    droits_miranda_lus   VARCHAR2(10),
    avocat_demande       VARCHAR2(10),
    avocat_present       VARCHAR2(10),
    resume               VARCHAR2(2000),
    modele               VARCHAR2(40)
);

-- Role de chaque locuteur : regles (etape 02) compare au LLM (etape 05)
CREATE TABLE etics.roles_llm (
    doc_id       VARCHAR2(10)  NOT NULL,
    locuteur     VARCHAR2(100) NOT NULL,
    role_regles  VARCHAR2(20),
    role_llm     VARCHAR2(20)  CONSTRAINT ck_role_llm CHECK (role_llm IN ('enqueteur', 'interroge', 'avocat', 'autre')),
    CONSTRAINT pk_roles_llm PRIMARY KEY (doc_id, locuteur),
    CONSTRAINT fk_roles_loc FOREIGN KEY (doc_id, locuteur) REFERENCES etics.locuteurs (doc_id, locuteur)
);

-- Tactique non ethique reperee par le LLM dans une replique (06_llm_tactiques_decision.py)
CREATE TABLE etics.tactiques_llm (
    tactique_id    NUMBER GENERATED ALWAYS AS IDENTITY CONSTRAINT pk_tactiques PRIMARY KEY,
    replique_id    VARCHAR2(20)  NOT NULL CONSTRAINT fk_tac_rep REFERENCES etics.repliques (replique_id),
    doc_id         VARCHAR2(10)  NOT NULL CONSTRAINT fk_tac_doc REFERENCES etics.documents (doc_id),
    categorie      VARCHAR2(30)  CONSTRAINT ck_tac_cat CHECK (categorie IN ('menace', 'fausse_promesse',
                   'mensonge_preuves', 'minimisation', 'pression_psychologique', 'humiliation_insulte',
                   'non_respect_droits', 'discrimination')),
    gravite        NUMBER(1)     CONSTRAINT ck_tac_grav CHECK (gravite BETWEEN 1 AND 3),
    justification  VARCHAR2(1000),
    citation       VARCHAR2(1000),
    modele         VARCHAR2(40)
);

-- Decision finale par interrogatoire : moderation (etape 03) + tactiques LLM (etape 06)
CREATE TABLE etics.decision_finale (
    doc_id               VARCHAR2(10)  CONSTRAINT pk_decision_finale PRIMARY KEY
                                       CONSTRAINT fk_dfin_doc REFERENCES etics.documents (doc_id),
    verdict_final        VARCHAR2(10)  CONSTRAINT ck_dfin_verdict CHECK (verdict_final IN ('bon', 'mauvais', 'toxique')),
    verdict_moderation   VARCHAR2(10),
    nb_tactiques         NUMBER(6),
    gravite_max          NUMBER(1),
    nb_tactiques_graves  NUMBER(6),
    tactiques_reperees   VARCHAR2(1000),
    modele_llm           VARCHAR2(40)
);
