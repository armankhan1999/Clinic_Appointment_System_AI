-- Reverses infrastructure/db/bootstrap.sql. DESTRUCTIVE: deletes every table and row in
-- both application schemas. Run only with explicit approval, as the project owner.
drop schema if exists clinic cascade;
drop schema if exists clinic_test cascade;
drop role if exists clinic_app;
drop role if exists clinic_test_app;
drop role if exists clinic_migrator;
-- btree_gist is left installed: it is harmless and other objects may depend on it.
