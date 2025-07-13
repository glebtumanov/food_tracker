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

## Настройка почты

Для отправки писем подтверждения регистрации и сброса пароля необходимо настроить SMTP:

### Gmail (рекомендуется)

1. Включите двухфакторную аутентификацию в вашем аккаунте Google
2. Создайте пароль приложения: [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Настройте `config.yaml`:

```yaml
mail:
  server: "smtp.gmail.com"
  port: 587
  username: "your-email@gmail.com"
  password: "your-app-password"  # Пароль приложения, не основной пароль!
  default_sender: "noreply@yourdomain.com"
  use_tls: true
  use_ssl: false
```

### Яндекс.Почта

```yaml
mail:
  server: "smtp.yandex.ru"
  port: 465
  username: "your-email@yandex.ru"
  password: "your-password"
  default_sender: "noreply@yourdomain.com"
  use_tls: false
  use_ssl: true
```

### Mail.ru

```yaml
mail:
  server: "smtp.mail.ru"
  port: 587
  username: "your-email@mail.ru"
  password: "your-password"
  default_sender: "noreply@yourdomain.com"
  use_tls: true
  use_ssl: false
```

### Отключение отправки писем

Если вы хотите отключить отправку писем (только для разработки), оставьте настройки по умолчанию. Ссылки будут выводиться в логи приложения.

### Тестирование настроек почты

После настройки `config.yaml` протестируйте отправку писем:

```bash
python test_email.py
```

Скрипт отправит тестовое письмо и покажет результат. Если есть ошибки, он подскажет, как их исправить.

## Решение проблем

### Ошибка "Multiple rows were found"

Если при входе в систему возникает ошибка "Multiple rows were found when one or none was required", это означает наличие дублированных пользователей в базе данных.

Для исправления запустите утилиту:

```bash
python fix_duplicates.py
```

Утилита:
- Найдет все дублированные email адреса
- Создаст резервную копию базы данных
- Оставит только самую старую запись для каждого email
- Создаст уникальный индекс для предотвращения будущих дубликатов

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

- ✅ Регистрация и авторизация пользователей
- ✅ Подтверждение email через отправку писем
- ✅ Сброс пароля через email
- ✅ Загрузка изображений еды
- ✅ Анализ изображений с помощью ИИ через chain-server
- ✅ Автоматическое определение блюд и их массы
- ✅ Анализ питательной ценности блюд
- ✅ Статистика потребления нутриентов по дням
- ✅ История загрузок
- ✅ Responsive дизайн

## Планы развития

- 📊 Расширенная аналитика (графики, тренды)
- 📤 Экспорт данных в CSV/PDF
- 🎯 Установка целей по питанию
- 📱 PWA для мобильных устройств
- 🔄 Интеграция с фитнес-трекерами
- 🍽️ База данных рецептов
- 👥 Социальные функции (друзья, достижения)