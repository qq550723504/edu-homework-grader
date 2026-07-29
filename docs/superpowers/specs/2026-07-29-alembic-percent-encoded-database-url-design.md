# Alembic percent-encoded database URL repair

## Context

The production PostgreSQL migration Job loads `DATABASE_URL` from the runtime
secret. A percent-encoded password is valid in a SQLAlchemy URL, but Alembic's
`Config.set_main_option` sends that URL through Python `ConfigParser`.
`ConfigParser` treats `%` as interpolation syntax and aborts before a database
connection or migration can run.

## Decision

The online Alembic path will create its engine directly from
`settings.database_url`, using SQLAlchemy's `create_engine` and the existing
`NullPool` setting. It will not write the runtime URL into Alembic's INI
configuration.

The offline path already passes `settings.database_url` directly to
`context.configure` and remains unchanged.

## Alternatives considered

1. Escape every percent sign before calling `set_main_option`. This depends on
   `ConfigParser` escaping rules at the credentials boundary and is rejected.
2. Normalize the password or alter the Kubernetes secret. This changes a valid
   runtime credential to work around a local configuration bug and is rejected.

## Verification

A regression test will run Alembic with a percent-encoded database URL and
assert that the configuration reaches engine construction without a
`ConfigParser` interpolation error. The migration image will then be rebuilt
and the one-time Kubernetes migration Job rerun using its immutable digest.
