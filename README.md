# Джарвис

Агрегатор инвестиционного портфеля: FastAPI-бэкенд + React-фронтенд + PostgreSQL.

## Запуск

1. Скопировать `.env.example` в `.env` и вписать токен T-Invest API с правами только на чтение:

   ```bash
   cp .env.example .env
   ```

2. Поднять базу данных:

   ```bash
   docker compose up -d db
   ```

3. Запустить бэкенд:

   ```bash
   cd backend && uv run uvicorn app.main:app --reload
   ```
