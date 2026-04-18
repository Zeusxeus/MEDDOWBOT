---
name: meddowbot-git
description: >
  Git and GitHub operations for MEDDOWBOT. Use when committing code,
  pushing to GitHub, staging files, or checking git status.
  Triggers: "commit", "push", "git", "save to github", "stage".
---

# MEDDOWBOT Git Operations

## Repository
GitHub: https://github.com/Zeusxeus/MEDDOWBOT
Branch: main

## Pre-Commit Checks (ALWAYS run first)
```bash
# 1. What changed?
git status && git diff --stat

# 2. No secrets?
git diff --cached | grep -iE "(password|token|secret|api_key)\s*=" | grep -v "# " || echo "✅ Clean"

# 3. Lint
uv run ruff check . --fix

# 4. Tests
uv run pytest tests/ -q 2>&1 | tail -5
```

## Stage & Commit
```bash
# Stage specific files (NEVER use git add .)
git add path/to/file1.py path/to/file2.py

# Verify what's staged
git diff --staged --stat

# Commit
git commit -m "feat(scope): description

Body of commit message explaining why."
```

## Push to GitHub
```bash
# Verify remote
git remote -v
# Should show: origin https://github.com/Zeusxeus/MEDDOWBOT.git

# Push
git push origin main
```

## Token Setup (one-time)
See PART 9 of the build guide for secure token setup.
Token is stored in git credential store, NEVER in code or chat.

## Gitignore Verification (before any commit)
```bash
# Verify these are ignored:
git check-ignore .env data/cookies/youtube.txt dev.db
# Each should print the path (means it's ignored)
```

## Commit Types
feat: new feature
fix: bug fix
chore: maintenance (deps, config)
docs: documentation
test: tests only
refactor: no feature change
style: formatting only
ci: CI/CD changes
