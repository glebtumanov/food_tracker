# Логирование Chain-Server

## Описание

Chain-server ведет подробное логирование всех API запросов и операций в файл для мониторинга и отладки.

## Настройка

Конфигурация логирования находится в файле `config.yaml`:

```yaml
logging:
  file: "logs/api_requests.log"  # Файл для логов
  level: "INFO"                  # Уровень логирования
  max_size_mb: 50               # Максимальный размер файла (МБ)
  backup_count: 5               # Количество резервных файлов
```

### Уровни логирования

- **DEBUG** - Детальная отладочная информация
- **INFO** - Общая информация о работе (по умолчанию)
- **WARNING** - Предупреждения
- **ERROR** - Ошибки

## Структура логов

### Middleware запросов
```
[REQUEST] GET /health from 127.0.0.1 | UA: Mozilla/5.0...
[RESPONSE] GET /health | Status: 200 | Time: 0.045s | IP: 127.0.0.1
```

### Анализ изображений
```
[ANALYZE] Получен запрос на анализ изображения | filename: image.jpg
[ANALYZE] Сохранено base64 изображение: temp_images/abc123.jpg
[ANALYZE] Начинаю анализ изображения: temp_images/abc123.jpg
[ANALYZE] Анализ завершен | блюд: 2 | уверенность: 95.00%
```

### Анализ нутриентов
```
[NUTRIENTS] Запрос анализа нутриентов | блюдо: 'Oatmeal' | количество: 250.0 грамм
[NUTRIENTS] Анализ завершен для 'Oatmeal' | калории: 389.0 ккал | белки: 16.9 г
```

### Жизненный цикл сервера
```
[STARTUP] Запуск chain-server...
[STARTUP] ✅ Анализатор изображений инициализирован
[STARTUP] ✅ Анализатор питательных веществ инициализирован
[STARTUP] 🚀 Chain-server готов к работе
[SHUTDOWN] Завершение работы chain-server...
```

## Ротация логов

Логи автоматически ротируются при достижении максимального размера:
- Текущий лог: `api_requests.log`
- Старые логи: `api_requests.log.1`, `api_requests.log.2`, и т.д.

## Мониторинг

### Просмотр логов в реальном времени
```bash
tail -f logs/api_requests.log
```

### Поиск ошибок
```bash
grep "ERROR" logs/api_requests.log
```

### Анализ производительности
```bash
grep "Time:" logs/api_requests.log | awk '{print $NF}' | sort -n
```

### Статистика запросов
```bash
grep "\[REQUEST\]" logs/api_requests.log | awk '{print $3}' | sort | uniq -c
```

## Примеры полезных команд

```bash
# Количество запросов сегодня
grep "$(date '+%Y-%m-%d')" logs/api_requests.log | grep "\[REQUEST\]" | wc -l

# Самые медленные запросы
grep "Time:" logs/api_requests.log | sort -k9 -nr | head -10

# Ошибки за последний час
grep "$(date -d '1 hour ago' '+%Y-%m-%d %H')" logs/api_requests.log | grep "ERROR"

# Статистика по методам HTTP
grep "\[REQUEST\]" logs/api_requests.log | awk '{print $3}' | sort | uniq -c | sort -nr
```