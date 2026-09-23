# Runtime Data

This directory is reserved for local runtime state and is intentionally excluded from Git.

Typical files include:

- ETF SQLite database
- Portfolio feed JSON files
- SQLite WAL / SHM files
- Temporary execution state

Do not commit live databases, account data, or operational portfolio feeds.

A sample portfolio format is available at:

`examples/portfolio.example.json`
