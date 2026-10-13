# ledger

A small ledger on SQLAlchemy and SQLite: accounts, journal entries in integer
cents (positive debits, negative credits), bulk imports and reports.

- `ledger.repository.Ledger`: open a database (`sqlite://` by default), add and
  find accounts, post entries, read balances, per-kind and signed totals.
- `ledger.importer`: bulk-import entries from dicts or CSV text; imported rows
  are committed and visible to every later query.
- `ledger.reports`: trial balance, monthly totals, category breakdown, largest entries.
- `ledger.export`: the journal as CSV text.
- `ledger.schema`: table names, reflection and schema creation helpers.

```bash
uv sync
uv run pytest
```
