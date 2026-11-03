-- One-time database bootstrap (D-17, D-20). Run once as the project owner (postgres),
-- e.g. through the Supabase MCP. Contains no secrets: role passwords are set separately
-- with SCRAM verifiers produced by scripts/db_role_passwords.py.
-- Re-runnable: every statement is idempotent. Rollback: infrastructure/db/bootstrap_rollback.sql

-- Needed for the no-overlap exclusion constraint on appointments (REC-DB-01).
create extension if not exists btree_gist with schema extensions;

-- Three least-privilege login roles. None can create roles or databases or bypass RLS.
do $$
declare
  r text;
begin
  foreach r in array array['clinic_migrator', 'clinic_app', 'clinic_test_app'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      execute format('create role %I login nosuperuser nocreatedb nocreaterole nobypassrls noinherit', r);
    end if;
  end loop;
end
$$;

-- Dev and test data live in separate schemas. postgres owns them; clinic_migrator creates
-- the tables inside them (and so owns those tables), the app roles only get DML.
create schema if not exists clinic;
create schema if not exists clinic_test;

revoke all on schema clinic, clinic_test from public;
grant usage, create on schema clinic, clinic_test to clinic_migrator;
grant usage on schema clinic to clinic_app;
grant usage on schema clinic_test to clinic_test_app;

-- Runtime safety limits for the application roles.
alter role clinic_app set statement_timeout = '10s';
alter role clinic_app set idle_in_transaction_session_timeout = '30s';
alter role clinic_test_app set statement_timeout = '10s';
alter role clinic_test_app set idle_in_transaction_session_timeout = '30s';
