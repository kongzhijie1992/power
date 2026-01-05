FROM pytorchlightning/pytorch_lightning:base-cuda-py3.12-torch2.4-cuda12.4.0

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.2.1 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --only main --no-root --no-interaction --no-ansi

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

ENV PORT=7860

EXPOSE 7860

CMD ["sh", "-c", "streamlit run scripts/streamlit_dashboard.py --server.address=0.0.0.0 --server.port=${PORT} --server.headless=true"]
