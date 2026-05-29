.PHONY: test lint typecheck smoke discover-smoke

test:
	pytest -v

lint:
	ruff check .

typecheck:
	mypy scripts tests

smoke:
	@if [ -z "$$GITHUB_TOKEN" ]; then \
		if command -v gh >/dev/null 2>&1; then \
			GITHUB_TOKEN=$$(gh auth token); export GITHUB_TOKEN; \
		else \
			echo "Set GITHUB_TOKEN or install gh CLI"; exit 1; \
		fi; \
	fi; \
	mkdir -p /tmp/ai-plugin-rankings-data/snapshots; \
	MAIN_DIR=. DATA_DIR=/tmp/ai-plugin-rankings-data python -m scripts.scrape; \
	echo "Smoke test complete. Inspect:"; \
	echo "  README.md"; \
	echo "  rankings/"; \
	echo "  data/latest.json"; \
	echo "  /tmp/ai-plugin-rankings-data/snapshots/"

discover-smoke:
	@set -e; \
	if [ -z "$$GITHUB_TOKEN" ]; then \
		if command -v gh >/dev/null 2>&1; then \
			GITHUB_TOKEN=$$(gh auth token); export GITHUB_TOKEN; \
		else \
			echo "Set GITHUB_TOKEN or install gh CLI"; exit 1; \
		fi; \
	fi; \
	python -m scripts.discover && \
	echo "Discovery complete. Inspect:" && \
	echo "  plugins.yaml (new entries appended)" && \
	echo "  discovery.log (audit lines appended)"
