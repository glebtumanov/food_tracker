# Food Tracker - Трекер еды с анализом изображений

Система состоит из двух частей:
- **pyapp-web** - веб-приложение для пользователей
- **chain-server** - сервер для анализа изображений еды с помощью LangChain и OpenAI

## Быстрый старт

### 1. Запуск сервера анализа изображений

```bash
cd chain-server
export OPENAI_API_KEY='your-openai-api-key'
export EDAMAM_APP_ID='your-edamam-app-id'
export EDAMAM_APP_KEY='your-edamam-app-key'
pip install -r requirements.txt
python server.py
```

Сервер доступен на `http://localhost:8000`, документация Swagger — на `http://localhost:8000/api/v1/docs`.

### 2. Запуск веб-приложения

```bash
cd pyapp-web
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Отредактируйте config.yaml под свои нужды
python app.py
```

Веб-приложение будет доступно на `http://localhost:5001`

## Конфигурация

### Chain Server (chain-server/config.yaml)

```yaml
server:
  host: "0.0.0.0"
  port: 8000

image_recognition_model:
  model: "gpt-4o"
  temperature: 0.1
  max_tokens: 1000

analyze_nutrients_model:
  model: "gpt-4o"
  temperature: 0.5
  max_tokens: 800
  timeout: 45

edamam:
  base_url: "https://api.edamam.com/api/food-database/v2/parser"
  timeout: 30
  max_results: 10

logging:
  file: "logs/api_requests.log"
  level: "INFO"
  max_size_mb: 50
  backup_count: 5
```

#### Переменные окружения

Не храните `EDAMAM_APP_ID` и `EDAMAM_APP_KEY` в `config.yaml`. Задайте их через переменные окружения (как `OPENAI_API_KEY`):

```bash
export EDAMAM_APP_ID='your-edamam-app-id'
export EDAMAM_APP_KEY='your-edamam-app-key'
```

### Web App (pyapp-web/config.yaml)

```yaml
server:
  host: "0.0.0.0"
  port: 5001
  debug: true

database:
  url: "sqlite:///app.db"

upload:
  folder: "uploads"
  max_content_length_mb: 16
  allowed_extensions: ["png", "jpg", "jpeg", "gif", "webp"]
```

## Архитектура

```
┌─────────────────┐    HTTP API     ┌─────────────────┐
│   Web App       │◄───────────────►│   Chain Server  │
│   (Flask)       │ /analyze_image  │   (LangServe)   │
│   Port: 5001    │ /analyze_nutrients    Port: 8000    │
└─────────────────┘                 └─────────────────┘
         │                                   │
         ▼                                   ▼
┌─────────────────┐                ┌─────────────────┐
│   SQLite DB     │                │   OpenAI API    │
│   (User data)   │                │   (gpt-4o)      │
└─────────────────┘                └─────────────────┘
                                             │
                                             ▼
                                   ┌─────────────────┐
                                   │   Edamam API    │
                                   │ (Food Database) │
                                   └─────────────────┘
```

**Поток данных:**

### Анализ изображений:
1. Пользователь загружает изображение в веб-приложение
2. Web App сохраняет файл и метаданные в SQLite
3. При нажатии "Определить еду на картинке" Web App отправляет изображение в Chain Server
4. Chain Server анализирует изображение через OpenAI API (gpt-4o с vision)
5. Результат (блюда + количества) возвращается в Web App и сохраняется в базе
6. Пользователь видит структурированный результат анализа

### Анализ нутриентов:
1. После анализа изображения пользователь нажимает "Определить нутриенты"
2. Web App отправляет данные о блюдах в Chain Server `/analyze-nutrients`
3. Chain Server запрашивает данные о продуктах из Edamam Food Database API
4. Chain Server использует OpenAI API для анализа и расчета питательной ценности
5. Результат (калории, белки, жиры, углеводы) возвращается в Web App
6. Пользователь видит детальную информацию о питательной ценности

## Возможности

- 🔐 Регистрация и авторизация пользователей
- 📧 Подтверждение email и сброс пароля
- 📸 Загрузка изображений еды
- 🤖 Анализ изображений с помощью OpenAI GPT-4o
- 📊 Определение блюд и их массы
- 🥗 Анализ питательной ценности через Edamam API
- 📈 Расчет калорий, белков, жиров и углеводов
- 📝 История загрузок и анализов
- 🔍 Двухэтапный анализ: изображение → нутриенты
- 📊 Логирование API запросов
- 🎨 Современный responsive дизайн

## Разработка

### Требования

- Python 3.12+
- OpenAI API ключ
- Современный браузер

### Установка для разработки

```bash
# Клонируйте репозиторий
git clone <repository-url>
cd food-tracker

# Установите зависимости для веб-приложения
cd pyapp-web
pip install -r requirements.txt
cp config.example.yaml config.yaml

# Установите зависимости для сервера анализа
cd ../chain-server
pip install -r requirements.txt

# Настройте API ключи
export OPENAI_API_KEY='your-openai-api-key'
export EDAMAM_APP_ID='your-edamam-app-id'
export EDAMAM_APP_KEY='your-edamam-app-key'
```

### Запуск в режиме разработки

Откройте два терминала:

**Терминал 1 - Chain Server:**
```bash
cd chain-server
python server.py
```

**Терминал 2 - Web App:**
```bash
cd pyapp-web
python app.py
```

## API Endpoints

### Chain Server (порт 8000)

- `POST /api/v1/analyze` — Анализ изображения (определение блюд)
- `POST /api/v1/analyze-nutrients` — Анализ питательной ценности одного блюда
- `POST /api/v1/analyze-multiple-nutrients` — Анализ питательной ценности для нескольких блюд
- `POST /api/v1/analyze-full` — Комбинированный анализ: блюда + нутриенты за один запрос
- `POST /api/v1/jobs` — Создать асинхронную задачу анализа (очередь)
- `GET /api/v1/jobs/{id}` — Получить статус/результат асинхронной задачи
- `GET /api/v1/health` — Проверка состояния серверов и API
- `GET /api/v1/docs` — Swagger документация

Приватные служебные маршруты и playground скрыты из документации и не считаются публичными.
### Асинхронная очередь задач (Job)

Для долгих запросов используйте очередь задач, чтобы быстро возвращать клиенту `job_id` и обрабатывать анализ изображения в фоне.

Пример создания задачи:

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "image_url": "https://example.com/food.jpg",
    "filename": "food.jpg",
    "params": {"source": "web"}
  }'
```

Проверка статуса:

```bash
curl http://localhost:8000/api/v1/jobs/<UUID>
```

Статусы: `queued`, `processing`, `done`, `error`.

Хранилище задач — локальный файл `chain-server/jobs.sqlite3`.


#### Корреляционные заголовки
- `X-Request-ID` — если не передан клиентом, сервер сгенерирует UUID и вернёт его в ответе (заголовок `X-Request-ID`).
- `Idempotency-Key` — значение из заголовка сохраняется в `request.state.idempotency_key` (подготовка к идемпотентным операциям).

### Web App (порт 5001)

- `GET /` — Главная (требуется вход)
- `POST /upload` — Загрузка изображения (требуется вход)
- `POST /analyze_image` — Анализ изображения через Chain Server (требуется вход)
- `POST /analyze_nutrients` — Анализ нутриентов через Chain Server (требуется вход)
- `POST /save_analysis` — Сохранение результата анализа (требуется вход)
- `GET /get_analysis/<filename>` — Получение сохранённого анализа (требуется вход)
- `GET /get_nutrients/<upload_id>` — Получение сохранённых нутриентов (требуется вход)
- `GET /uploads/<path:filename>` — Получение загруженного изображения
- `GET /history` — История загрузок (требуется вход)
- `GET /nutrition_stats` — Статистика по дням (требуется вход)
- `GET /use/<upload_id>` — Выбрать загрузку для просмотра (требуется вход)
- `GET /delete/<upload_id>` — Удаление загрузки (требуется вход)
- `GET/POST /register` — Регистрация
- `GET/POST /login` — Вход
- `GET /logout` — Выход
- `GET/POST /forgot` — Запрос на сброс пароля
- `GET/POST /reset/<token>` — Сброс пароля по токену

## Планы развития

- ✅ ~~Интеграция веб-приложения с chain-server~~ (реализовано)
- ✅ ~~Добавление питательной ценности блюд~~ (реализовано)
- ✅ ~~Логирование API запросов~~ (реализовано)
- 📈 Статистика потребления и дневник питания
- 🎯 Цели по калориям и макронутриентам
- 📊 Графики и аналитика потребления
- 🔧 Docker контейнеры
- 🚀 Deployment инструкции
