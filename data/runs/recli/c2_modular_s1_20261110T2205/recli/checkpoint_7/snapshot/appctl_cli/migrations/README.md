# Migrations

appctl and every installed extension may ship migrations:

    <source>/migrations/db/<sequence>_<name>.py          database migrations
    <source>/migrations/container/<sequence>_<name>.py   container migrations

`<source>` is this package directory for appctl itself, or an extension
directory under the packages directory (`<packages>/<extension>` or
`<packages>/<vendor>/<extension>`). `<sequence>` is a number, usually a
`YYYYMMDDHHMMSS` timestamp; pending migrations run in ascending
`(sequence, name, source)` order.

A migration module defines `up()` and optionally `down()` (or a `Migration`
class with those methods). Both may take one argument, a
`MigrationContext` giving access to `db`, `output`, `environ`, `root_dir`
and the migration's `source`, `name`, `type` and `path`.

Applied migrations are recorded in the `migrations` table as
`<source>:<sequence>_<name>` with their type (`db` or `container`).
