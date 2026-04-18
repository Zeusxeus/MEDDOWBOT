---
name: meddowbot-python
description: >
  Python environment setup and management for MEDDOWBOT project.
  Use when setting up the Python environment, installing dependencies,
  running the bot, or managing the uv package manager.
  Triggers: "set up Python", "install deps", "create venv", "run bot",
  "uv install", "add dependency", "Python environment".
---

# MEDDOWBOT Python Environment

## Package Manager: uv (NOT pip)
All Python operations use `uv`. Never use `pip install` directly.

## Initial Setup (run once)
```bash
cd ~/projects/MEDDOWBOT

# Install all dependencies from pyproject.toml
uv sync --all-extras

# Verify
uv run python --version  # Python 3.12.x
uv run python -c "import aiogram; print(aiogram.__version__)"
```

## Adding New Dependencies
```bash
# Add to pyproject.toml and install
uv add package-name

# Add dev dependency
uv add --dev package-name

# NEVER: pip install package-name
# NEVER: python -m pip install
```

## Running Commands
```bash
# Always prefix with uv run
uv run python -m bot.main          # Run bot
uv run pytest tests/ -v            # Run tests
uv run ruff check . --fix          # Lint + autofix
uv run mypy .                      # Type check
uv run alembic upgrade head        # DB migrations
```

## pyproject.toml Location
~/projects/MEDDOWBOT/pyproject.toml

## Virtual Environment
uv manages this automatically in .venv/
Do NOT activate manually — uv run handles it.
