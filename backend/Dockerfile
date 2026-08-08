FROM python:3.12-slim
# Версия uv зафиксирована так же строго, как и зависимости в uv.lock рядом:
# плавающий :latest означал, что сборка одного и того же коммита завтра может
# собраться другим инструментом.
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen
COPY . .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
