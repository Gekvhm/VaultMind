# Contributing to VaultMind

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/YOUR_USERNAME/vaultmind.git
   cd vaultmind
   ```

2. **Run the setup script** (macOS Apple Silicon):

   ```bash
   chmod +x setup_env.sh
   ./setup_env.sh
   ```

   This will create a virtual environment, install dependencies (including Metal-accelerated `llama-cpp-python`), and download the default model.

3. **Activate the environment:**

   ```bash
   source .venv/bin/activate
   ```

4. **Install dev dependencies:**

   ```bash
   pip install -e ".[dev]"
   ```

## Code Style

- **Linter/Formatter:** [Ruff](https://docs.astral.sh/ruff/) — run `ruff check .` and `ruff format .` before committing.
- **Type hints:** Required for all function signatures.
- **Docstrings:** Written in **Ukrainian** (project convention).
- **Line length:** 120 characters max.
- **Config:** See `ruff.toml` and `[tool.ruff]` in `pyproject.toml`.

## Running Tests

```bash
pytest
```

Tests live in the `tests/` directory. Add tests for any new functionality.

## Pull Request Process

1. **Fork** the repository and create a feature branch:

   ```bash
   git checkout -b feat/your-feature
   ```

2. **Commit conventions** — use prefixes:
   - `feat:` — new feature
   - `fix:` — bug fix
   - `docs:` — documentation changes
   - `refactor:` — code restructuring without behavior change
   - `test:` — adding or updating tests

3. **Ensure** all tests pass and linting is clean:

   ```bash
   ruff check .
   pytest
   ```

4. **Open a PR** with a clear description:
   - What the change does
   - Why it's needed
   - Any breaking changes

## Reporting Issues

- Use [GitHub Issues](https://github.com/YOUR_USERNAME/vaultmind/issues).
- Include: macOS version, Python version, steps to reproduce, expected vs actual behavior.
- For model-related issues, include the model name and `llama-cpp-python` version.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
