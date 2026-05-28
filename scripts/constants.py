"""Controlled vocabularies. The LLM enrichment prompt selects from these lists;
it never invents new categories or tags."""

CATEGORIES: tuple[str, ...] = (
    "productivity",
    "testing",
    "debugging",
    "code-review",
    "documentation",
    "language-support",
    "mcp-bridge",
    "other",
)

TAGS: tuple[str, ...] = (
    "workflow", "skills", "tdd", "agents", "automation",
    "lint", "format", "refactor", "git", "github",
    "browser", "headless", "screenshot", "design", "ui",
    "shell", "cli", "python", "typescript", "rust",
    "go", "java", "data", "sql", "search",
    "embeddings", "rag", "memory", "context", "logging",
)

ASSISTANTS: frozenset[str] = frozenset({"claude-code", "cursor", "copilot", "codex"})
