# AI Plugin Rankings — Maintainer Handoff

The implementation is complete and the `dev` branch is ready to merge into `main`.

## What's in the repo

- `main` branch: docs/ (design spec + implementation plan) + (after merge) all code
- `dev` branch: all 22 tasks completed (code, tests, workflows)
- `data` branch: orphan branch, holds a placeholder README explaining the snapshot format

## Verification status

- ✅ 53 tests pass
- ✅ ruff clean
- ✅ mypy strict clean
- ✅ Live smoke test against real GitHub API succeeded (run during Task 22)

## Steps to publish

1. **Merge dev → main**
   ```bash
   git checkout main
   git merge --no-ff dev -m "Merge ai-plugin-rankings v1 implementation"
   ```

2. **Create the GitHub repo** (e.g. via `gh`):
   ```bash
   gh repo create <owner>/ai-plugin-rankings --public --source=. --remote=origin
   ```
   Or create via the GitHub UI and add the remote manually:
   ```bash
   git remote add origin git@github.com:<owner>/ai-plugin-rankings.git
   ```

3. **Push both code and history**:
   ```bash
   git push -u origin main
   git push origin data
   ```

4. **Set the ANTHROPIC_API_KEY secret**:
   In repo Settings → Secrets and variables → Actions, add:
   - Name: `ANTHROPIC_API_KEY`
   - Value: your Anthropic API key

5. **Trigger the daily workflow once manually**:
   GitHub Actions tab → "Daily ranking update" → Run workflow.
   Confirm it succeeds before the first cron fires (03:00 UTC tomorrow).

6. **Add more plugins** by opening PRs that edit `plugins.yaml`. The weekly discovery workflow (Sundays 05:00 UTC) will also open candidate PRs automatically.

## Cost expectations

- Daily run: free (GITHUB_TOKEN, ~1 second per plugin)
- Weekly enrichment: ~$0 most weeks (sha-skip), ~cents when many READMEs change
- Weekly discovery: free
