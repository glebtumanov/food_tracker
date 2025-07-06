# Food Tracker - Трекер еды с анализом изображений

Система состоит из двух частей:
- **pyapp-web** - веб-приложение для пользователей
- **chain-server** - сервер для анализа изображений еды с помощью LangChain и OpenAI

## Быстрый старт

### 1. Запуск сервера анализа изображений

```bash
cd chain-server
export OPENAI_API_KEY='your-openai-api-key'
pip install -r requirements.txt
python server.py
```

Сервер будет доступен на `http://localhost:8000`

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

openai:
  model: "gpt-4o"
  temperature: 0.1
  max_tokens: 1000
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
┌─────────────────┐    HTTP API    ┌─────────────────┐
│   Web App       │◄──────────────►│   Chain Server  │
│   (Flask)       │  /analyze_image │   (LangServe)   │
│   Port: 5001    │                │   Port: 8000    │
└─────────────────┘                └─────────────────┘
         │                                   │
         ▼                                   ▼
┌─────────────────┐                ┌─────────────────┐
│   SQLite DB     │                │   OpenAI API    │
│   (User data)   │                │   (gpt-4o)      │
└─────────────────┘                └─────────────────┘
```

**Поток данных:**
1. Пользователь загружает изображение в веб-приложение
2. Web App сохраняет файл и метаданные в SQLite
3. При нажатии "Анализировать" Web App отправляет изображение в Chain Server
4. Chain Server анализирует изображение через OpenAI API
5. Результат возвращается в Web App и сохраняется в базе
6. Пользователь видит структурированный результат анализа

## Возможности

- 🔐 Регистрация и авторизация пользователей
- 📧 Подтверждение email и сброс пароля
- 📸 Загрузка изображений еды
- 🤖 Анализ изображений с помощью OpenAI GPT-4o
- 📊 Определение блюд и их массы
- 📝 История загрузок
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

# Настройте API ключ
export OPENAI_API_KEY='your-openai-api-key'
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

- `POST /analyze` - Анализ изображения
- `GET /health` - Проверка состояния
- `GET /docs` - Swagger документация

### Web App (порт 5001)

- `GET /` - Главная страница
- `POST /upload` - Загрузка изображения
- `GET /history` - История загрузок
- `POST /register` - Регистрация
- `POST /login` - Авторизация

## Планы развития

- ✅ ~~Интеграция веб-приложения с chain-server~~ (реализовано)
- 🍎 Добавление питательной ценности блюд
- 📈 Статистика потребления
- 📱 Мобильная версия
- 🔧 Docker контейнеры
- 🚀 Deployment инструкции