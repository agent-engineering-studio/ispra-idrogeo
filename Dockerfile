# ispra-idrogeo in a container: the library, the `idrogeo` command and the
# `idrogeo-mcp` server (target "app"), Jupyter for the example notebooks
# (target "notebooks") and the Mappa dei dati for public bodies (target
# "web"). Built from this folder, so it runs the code you see.
#
#   make up          the MCP server on http://localhost:8767/mcp
#   make notebooks   Jupyter on http://localhost:8888
#   make app-up      the Mappa dei dati on http://localhost:3002

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_ROOT=/data

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --extra geo --extra mcp --extra warehouse

RUN useradd --create-home --uid 1000 idrogeo \
    && mkdir -p /data/ispra-idrogeo \
    && chown idrogeo /data/ispra-idrogeo
USER idrogeo
WORKDIR /home/idrogeo

EXPOSE 8767
CMD ["idrogeo-mcp"]


FROM app AS notebooks

USER root
WORKDIR /app
RUN uv sync --locked --no-dev --no-editable --extra geo --extra mcp --extra warehouse \
    --group notebooks
USER idrogeo
WORKDIR /home/idrogeo/examples

EXPOSE 8888
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser"]


FROM app AS web

USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN uv sync --locked --no-dev --no-editable --extra geo --extra mcp --extra warehouse \
    --group app
COPY app ./app
RUN sh app/vendor.sh && chown -R idrogeo /app/app
USER idrogeo
ENV IDROGEO_APP_WAREHOUSE=/data/ispra-idrogeo/app.duckdb

EXPOSE 3002
CMD ["uvicorn", "--factory", "app.api:create_app", "--host", "0.0.0.0", "--port", "3002"]
