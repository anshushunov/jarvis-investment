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
   cd backend && uv run uvicorn app.main:app --reload --port 8001
   ```

   > На хосте БД слушает порт `5433`, а бэкенд — `8001`, а не стандартные `5432`/`8000`: эти порты
   > на машине разработки постоянно заняты другими проектами.

   Тот же порт `8001` используется и при запуске бэкенда через `docker compose up -d`
   (сервис `backend` публикуется как `8001:8000`; внутри контейнера uvicorn слушает `8000` как обычно).

## Сертификат T-Bank в `backend/app/connectors/tbank/russian_trusted_ca.pem`

T-Bank (бывший «Тинькофф») выпускает сертификат `*.tinkoff.ru` через цепочку
Минцифры РФ (`Russian Trusted Sub CA` → самоподписанный `Russian Trusted Root
CA`) — после ухода западных удостоверяющих центров это единственная цепочка,
которой подписан домен `invest-public-api.tinkoff.ru`. Этой цепочки нет в
стандартном доверенном наборе Python (`certifi`/Mozilla trust store), поэтому
без явного добавления её TLS-соединение с T-Invest API падает с
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` — не
только в этом окружении, а на любой машине, где эта цепочка не установлена в
системное хранилище отдельно.

Файл `russian_trusted_ca.pem` — это публичные Sub CA и Root CA сертификаты
(секрета в них нет), которые `backend/app/connectors/tbank/client.py`
подключает аддитивно к стандартному набору `certifi` **только для клиента
Т-Банка**: доверие расширяется исключительно в `TBankClient`, на MOEX-клиент
и остальной HTTP-код проекта оно не распространяется.

Проверить, что файл в репозитории соответствует тому, что реально отдаёт
сервер, можно сверкой SHA-256 отпечатков:

```bash
# Отпечатки Sub CA и Root CA из файла в репозитории
openssl crl2pkcs7 -nocrl -certfile backend/app/connectors/tbank/russian_trusted_ca.pem \
  | openssl pkcs7 -print_certs -noout \
  | csplit -s -z -f /tmp/repo_cert -b '%d.pem' - '/-----BEGIN CERTIFICATE-----/' '{*}'
for f in /tmp/repo_cert*.pem; do openssl x509 -in "$f" -noout -fingerprint -sha256 -subject; done

# Отпечатки полной цепочки, которую отдаёт сервер (0 — лист *.tinkoff.ru,
# 1 — Sub CA, 2 — Root CA; сверять со значениями выше нужно 1 и 2)
echo | openssl s_client -connect invest-public-api.tinkoff.ru:443 \
  -servername invest-public-api.tinkoff.ru -showcerts 2>/dev/null > /tmp/live_chain.txt
awk '/BEGIN CERTIFICATE/,/END CERTIFICATE/{print > ("/tmp/live_cert" n ".pem")} /END CERTIFICATE/{n++}' /tmp/live_chain.txt
for f in /tmp/live_cert*.pem; do openssl x509 -in "$f" -noout -fingerprint -sha256 -subject; done
```
