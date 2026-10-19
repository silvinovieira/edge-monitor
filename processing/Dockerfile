FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY processing ./processing
RUN uv sync --frozen --no-dev

# The venv's python directly (not uv run), so SIGTERM reaches the service.
CMD ["/app/.venv/bin/python", "-m", "processing"]
