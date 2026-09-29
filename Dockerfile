# API and UI image (docker-compose.yml). Multi-stage: build the virtualenv, copy only it.
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Everything the API and the UI read at runtime. A missing folder only fails when the first
# question arrives (unit tests run from the repository, where every file exists).
COPY src ./src
COPY prompts ./prompts
COPY semantic ./semantic
COPY ui ./ui

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
