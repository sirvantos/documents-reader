# Test runner image: Python 3.12 with the locked dependencies (incl. the dev group).
# The repository is mounted read-only at /app at run time (see compose.yaml),
# so the image only needs the environment, not the code.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project
# Editable install: the .pth file points at /app/src, which the mounted repo provides.
COPY src ./src
RUN uv sync --frozen

# Not root: tests rely on file permissions (e.g. a read-only originals folder).
RUN useradd --create-home --uid 1000 tester
USER tester

ENTRYPOINT ["/opt/venv/bin/pytest", "-p", "no:cacheprovider"]
