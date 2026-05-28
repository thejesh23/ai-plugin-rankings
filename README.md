# data branch

Append-only daily snapshots for the AI Plugin Rankings repo.

## Format

`snapshots/YYYY-MM-DD.jsonl` — one line per plugin, JSONL:

```json
{"id":"superpowers","repo":"obra/superpowers","stars":1247,"forks":89,"open_issues":12,"archived":false,"pushed_at":"2026-05-27T18:22:00Z"}
```

Files are written by the daily GitHub Actions workflow on the `main` branch.
This branch has no shared history with `main` (it's an orphan branch) so it
can grow indefinitely without bloating the main checkout.
