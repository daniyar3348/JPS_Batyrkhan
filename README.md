# Платформа научного журнала

Система по образцу Open Journal Systems: подача рукописей, рецензирование, редактура, публикация.
Архитектура описана в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Что готово (этап 1 — каркас)

- **Учётные записи.** Регистрация с согласиями на обработку персональных данных и их передачу за рубеж
  (закон РК), подтверждение e-mail, вход, выход, восстановление пароля, смена пароля, профиль с ORCID.
- **Безопасность.**
  - Пароли хранятся в Argon2id.
  - Сессии хранятся на сервере, cookie недоступна скриптам (httpOnly).
  - Защита от CSRF.
  - Блокировка учётной записи после 10 неудачных попыток входа.
  - Ограничение частоты запросов в nginx.
- **Журнал.** Настройки (название, ISSN с проверкой контрольной цифры, издатель, контакты). Защита от
  одновременной правки двумя людьми: изменения второго отклоняются, данные первого не теряются.
- **Разделы журнала** и назначение их редакторов.
- **Роли и права.** Администратор, главный редактор, редактор раздела, рецензент, автор, литературный
  редактор, верстальщик, корректор, финансовый менеджер.
- **Пользователи.** Поиск, приглашение по e-mail, изменение ролей, блокировка. Нельзя удалить последнего
  администратора.
- **Журнал аудита** всех важных действий.
- **Фоновые задачи.** Письма отправляются в фоне через очередь на PostgreSQL, с повторами при ошибках.
- **Рабочее пространство редакции** (React): вход и регистрация, личный кабинет, страницы администратора.

Следующий этап — подача рукописей (см. план в §21 архитектуры).

## Структура

```
backend/              API и фоновые задачи (Python 3.13, FastAPI, SQLAlchemy, PostgreSQL)
  app/core/           общее: настройки, БД, ошибки, очередь задач, почта, безопасность
  app/modules/        модули: identity, journals, audit, notifications
  migrations/         миграции базы данных (Alembic)
  tests/              тесты (на настоящем PostgreSQL)
workspace/            рабочее пространство редакции (React, Vite, Mantine)
packages/api-client/  типизированный клиент API, генерируется из схемы OpenAPI бэкенда
deploy/nginx/         nginx: раздача интерфейса, прокси к API, заголовки безопасности, лимиты
compose.yaml          всё приложение в Docker одной командой
docs/                 архитектура
```

## Запуск в Docker

Нужен Docker с Compose.

```bash
docker compose up --build
```

```bash
docker compose run --rm api python -m app.cli seed-demo
```

- Рабочее пространство: http://localhost:8080
- Отправленные письма (Mailpit): http://localhost:8025
- Документация API: http://localhost:8080/api/docs

## Запуск для разработки (без Docker)

Нужны Python 3.13 с [uv](https://docs.astral.sh/uv/), Node.js 22.22+ и PostgreSQL 16+
с базой `jps` (пользователь и пароль `jps`).

```bash
cd backend && cp .env.example .env && uv sync
```

```bash
cd backend && uv run alembic upgrade head && uv run python -m app.cli seed-demo
```

```bash
cd backend && uv run uvicorn app.main:create_app --factory --reload
```

```bash
cd backend && uv run python -m app.worker
```

```bash
npm install && npm run dev
```

Рабочее пространство откроется на http://localhost:5173. Письма в режиме разработки печатаются в журнал
процесса `app.worker`.

### Демо-пользователи

Пароль у всех: `demo-password-2026`. Создаются командой `seed-demo` (в production она отключена).

| E-mail | Роли |
|---|---|
| admin@example.org | Администратор |
| chief@example.org | Главный редактор, автор |
| editor@example.org | Редактор раздела, рецензент |
| reviewer@example.org | Рецензент, автор |
| author@example.org | Автор |
| finance@example.org | Финансовый менеджер |

## Настоящий журнал: первый запуск

Создать журнал и первого администратора (пароль спросит или возьмёт из `JPS_ADMIN_PASSWORD`):

```bash
cd backend && uv run python -m app.cli bootstrap --journal-name "Название журнала" --admin-email you@example.org --admin-given-name Имя
```

Остальное (ISSN, контакты, разделы, редакторы) настраивается в рабочем пространстве.

## Проверки

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests && uv run lint-imports && uv run pytest
```

```bash
npx biome check . && npm run check && npm test && npm run build
```

Тесты бэкенда используют базу `jps_test` (адрес можно задать в `JPS_TEST_DATABASE_URL`).
Те же проверки запускает CI (`.github/workflows/ci.yml`). Отдельная проверка в CI следит, чтобы клиент API
был перегенерирован после изменения бэкенда.

После изменения API перегенерируйте клиент:

```bash
npm run generate:api
```

## Настройки

Все настройки бэкенда — переменные окружения с префиксом `JPS_`. Полный список с пояснениями — в
`backend/app/core/config.py`, пример — `backend/.env.example`. Основные:

| Переменная | Назначение |
|---|---|
| `JPS_DATABASE_URL` | подключение к PostgreSQL |
| `JPS_WORKSPACE_URL` | адрес рабочего пространства для ссылок в письмах |
| `JPS_COOKIE_SECURE` | `true` в production (cookie только по HTTPS) |
| `JPS_EMAIL_BACKEND` | `smtp` в production, `console` при разработке |
| `JPS_SMTP_HOST`, `JPS_SMTP_PORT`, `JPS_SMTP_USERNAME`, `JPS_SMTP_PASSWORD` | почтовый сервер |
| `JPS_EMAIL_FROM` | адрес отправителя писем |

С `JPS_ENVIRONMENT=production` приложение не запустится, если cookie не защищены или почта не настроена.
