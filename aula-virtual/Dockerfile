FROM ghcr.io/astral-sh/uv:0.12.10 AS uv
FROM python:3.12-slim-bookworm

COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN groupadd --gid 10001 cuadrilla && useradd --uid 10001 --gid cuadrilla --create-home cuadrilla
COPY --chown=10001:10001 artifacts/cuadrilla /app/artifacts/cuadrilla
WORKDIR /app/artifacts/cuadrilla
RUN mkdir -p uploads sample_data .local && chown -R cuadrilla:cuadrilla uploads sample_data .local
USER cuadrilla
EXPOSE 8000
CMD ["python", "run.py"]
