-- CI only: plain Postgres has no Supabase `extensions` schema; bootstrap.sql installs btree_gist into it.
create schema if not exists extensions;
