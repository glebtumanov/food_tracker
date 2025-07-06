# Chain Server - LangChain цепочки для анализа еды

Этот модуль содержит LangChain цепочки для анализа изображений еды с помощью OpenAI API.

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Установите переменную окружения с API ключом OpenAI:
```bash
export OPENAI_API_KEY='your-openai-api-key'
```

## Использование

### Анализ одного изображения

```python
from food_analyzer import create_food_analyzer

# Создаем анализатор
analyzer = create_food_analyzer()

# Анализируем изображение
result = analyzer.analyze_image("path/to/food/image.jpg")

print(result)
```

### Пример результата

```json
{
  "dishes": [
    {
      "name": "Паста Болоньезе",
      "weight_grams": 350,
      "description": "Спагетти с мясным соусом и сыром пармезан"
    },
    {
      "name": "Салат Цезарь",
      "weight_grams": 150,
      "description": "Зеленый салат с курицей, сухариками и соусом"
    }
  ],
  "total_weight": 500,
  "confidence": 0.85
}
```

### Пакетный анализ

```python
# Анализируем несколько изображений
image_paths = ["image1.jpg", "image2.jpg", "image3.jpg"]
results = analyzer.analyze_batch(image_paths)

for i, result in enumerate(results):
    print(f"Результат для изображения {i+1}: {result}")
```

## Тестирование

Для тестирования цепочки используйте:

```bash
python test_food_analyzer.py
```

Убедитесь, что у вас есть:
- Переменная окружения `OPENAI_API_KEY`
- Тестовые изображения в папке `test_images/`

## Поддерживаемые форматы

- JPG/JPEG
- PNG
- GIF
- WebP

## LangServe сервер

### Запуск сервера

```bash
cd chain-server
export OPENAI_API_KEY='your-api-key'
pip install -r requirements.txt
# Отредактируйте config.yaml если нужно изменить настройки по умолчанию
python server.py
```

Сервер будет доступен по адресу: `http://localhost:8000`

### API endpoints

- `POST /analyze` - Анализ одного изображения
- `POST /analyze_batch` - Пакетный анализ
- `GET /health` - Проверка состояния сервера
- `GET /docs` - Swagger документация
- `/langserve` - LangServe playground

## Конфигурация

Основные настройки сервера хранятся в файле `config.yaml`. Вы можете изменить:

- Модель OpenAI и её параметры
- Порт и хост сервера
- Название и описание API

Пример конфигурации:
```yaml
server:
  host: "0.0.0.0"
  port: 8000
  title: "Food Image Analyzer API"

openai:
  model: "gpt-4o"
  temperature: 0.1
  max_tokens: 1000
```

Дополнительные настройки (CORS, файлы, LangServe) находятся в коде как константы в файле `server.py`.

## Структура проекта

```
chain-server/
├── food_analyzer.py      # Основная цепочка для анализа
├── server.py            # LangServe сервер
├── config.yaml          # Конфигурация сервера
├── test_food_analyzer.py # Тестирование цепочки
├── requirements.txt      # Зависимости
└── README.md            # Этот файл
```

## Особенности

- Используется модель `gpt-4o` для анализа изображений
- Структурированный вывод с помощью Pydantic моделей
- Обработка ошибок и валидация входных данных
- Поддержка пакетного анализа
- Оценка уверенности в результатах

## Планируемые улучшения

- Добавление кеширования результатов
- Интеграция с базой данных продуктов
- Расширенная настройка промптов
- Поддержка дополнительных моделей
- Асинхронная обработка запросов
- Мониторинг и логирование
- Аутентификация и авторизация