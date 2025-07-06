# Food Tracker Web App

Веб-приложение для отслеживания еды с анализом изображений.

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Скопируйте пример конфигурации:
```bash
cp config.example.yaml config.yaml
```

3. Отредактируйте `config.yaml` под свои нужды

4. Запустите приложение:
```bash
python app.py
```

## Конфигурация

Настройки приложения хранятся в файле `config.yaml`. Вы можете изменить:

- Настройки сервера (хост, порт, debug режим)
- Настройки базы данных
- Параметры загрузки файлов
- Настройки безопасности
- Настройки почты

### Пример конфигурации:

```yaml
server:
  host: "0.0.0.0"
  port: 5001
  debug: true

database:
  url: "sqlite:///app.db"
  track_modifications: false

upload:
  folder: "uploads"
  max_content_length_mb: 16
  allowed_extensions: ["png", "jpg", "jpeg", "gif", "webp"]

security:
  remember_cookie_duration_days: 7
  secret_key: null  # Автоматически генерируется

mail:
  server: "smtp.example.com"
  port: 465
  username: "username"
  password: "password"
  default_sender: "noreply@example.com"
  use_tls: true
  use_ssl: true
```

## Переменные окружения

Некоторые настройки могут быть переопределены через переменные окружения:

- `SECRET_KEY` - Секретный ключ для Flask
- `DATABASE_URL` - URL базы данных
- `MAIL_SERVER` - SMTP сервер
- `MAIL_PORT` - Порт SMTP сервера
- `MAIL_USERNAME` - Логин для почты
- `MAIL_PASSWORD` - Пароль для почты
- `MAIL_DEFAULT_SENDER` - Отправитель по умолчанию

## Структура проекта

```
pyapp-web/
├── app.py               # Основное приложение
├── config.yaml          # Конфигурация
├── requirements.txt     # Зависимости
├── instance/           # Папка с секретными данными
├── static/             # Статические файлы
│   ├── css/
│   └── js/
├── templates/          # HTML шаблоны
├── uploads/           # Загруженные изображения
└── README.md          # Этот файл
```

## Функционал

- Регистрация и авторизация пользователей
- Подтверждение email
- Сброс пароля
- Загрузка изображений еды
- Анализ изображений с помощью OpenAI через chain-server
- Автоматическое определение блюд и их массы
- История загрузок
- Responsive дизайн

## Планы развития

- Интеграция с chain-server для анализа изображений
- Добавление питательной ценности блюд
- Статистика потребления
- Экспорт данных
- Мобильное приложение