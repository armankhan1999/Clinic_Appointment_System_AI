-- CI only: passwords for the throwaway Postgres service container in .github/workflows/ci.yml.
-- These values protect nothing; real environments set SCRAM verifiers via scripts/db_role_passwords.py.
alter role clinic_migrator with password 'ci-migrator-password';
alter role clinic_app with password 'ci-app-password';
alter role clinic_test_app with password 'ci-test-app-password';
