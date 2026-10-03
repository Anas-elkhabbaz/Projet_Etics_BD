-- Projet ETICS (P02, Sujet 3) - Creation du schema ETICS dans la PDB FREEPDB1.
-- A executer par un compte DBA (SYSTEM dans SQL Developer, ou "/ as sysdba" en local).
-- Le schema est cree sans mot de passe : on le consulte depuis SYSTEM (Autres utilisateurs > ETICS).
-- Pour s'y connecter directement : ALTER USER etics IDENTIFIED BY "votre_mot_de_passe";

DECLARE
    n NUMBER;
BEGIN
    SELECT COUNT(*) INTO n FROM dba_users WHERE username = 'ETICS';
    IF n = 0 THEN
        EXECUTE IMMEDIATE 'CREATE USER etics NO AUTHENTICATION DEFAULT TABLESPACE users QUOTA UNLIMITED ON users';
        EXECUTE IMMEDIATE 'GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW TO etics';
    END IF;
END;
/
