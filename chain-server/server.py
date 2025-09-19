"""
LangServe сервер для анализа изображений еды и расчета питательных веществ.

Содержит две основные функции:
1. Анализ изображений еды (модель image_recognition_model)
2. Анализ питательных веществ через Edamam API (модель analyze_nutrients_model)

Запуск: python server.py
"""

import os
import base64
import yaml
import logging
import time
from typing import Dict, Any
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from langserve import add_routes
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from food_analyzer import (FoodImageAnalyzer, EdamamFoodSearcher, FoodSearchRequest, NutrientAnalysis,
                          MultipleDishesRequest, MultipleDishItem, MultipleNutrientAnalysis)


# Константы для настроек
CORS_SETTINGS = {
    "allow_origins": ["*"],
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}

FILES_SETTINGS = {
    "temp_dir": "temp_images",
    "allowed_extensions": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
    "max_file_size_mb": 16,
}

ANALYSIS_SETTINGS = {
    "confidence_threshold": 0.0,
    "default_language": "ru",
}

LANGSERVE_SETTINGS = {
    "path": "/langserve",
    "playground_type": "default",
    "enable_feedback_endpoint": False,
}


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Загружает конфигурацию из YAML файла."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        raise FileNotFoundError(f"Файл конфигурации {config_path} не найден")
    except yaml.YAMLError as e:
        raise ValueError(f"Ошибка чтения конфигурации: {e}")


def setup_logging(log_config: Dict[str, Any]) -> logging.Logger:
    """Настраивает логирование запросов в файл с ротацией."""
    log_file = log_config.get("file", "logs/api_requests.log")
    log_level = log_config.get("level", "INFO")
    max_size_mb = log_config.get("max_size_mb", 50)
    backup_count = log_config.get("backup_count", 5)

    # Создаем директорию для логов если её нет
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Настраиваем логгер
    logger = logging.getLogger("chain_server_api")
    logger.setLevel(getattr(logging, log_level.upper()))

    # Убираем существующие обработчики
    logger.handlers.clear()

    # Создаем форматтер
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Файловый обработчик с ротацией
    max_bytes = max_size_mb * 1024 * 1024  # Конвертируем МБ в байты
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Консольный обработчик для ошибок
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def create_food_analyzer_with_config(config: Dict[str, Any]) -> FoodImageAnalyzer:
    """Создает анализатор изображений с настройками из конфигурации."""
    image_config = config.get("image_recognition_model", {})

    return FoodImageAnalyzer(
        model_name=image_config.get("model", "gpt-4o"),
        temperature=image_config.get("temperature", 0.1),
        max_tokens=image_config.get("max_tokens", 1000)
    )


def create_nutrients_analyzer_with_config(config: Dict[str, Any]) -> EdamamFoodSearcher:
    """Создает анализатор питательных веществ с настройками из конфигурации."""
    edamam_config = config.get("edamam", {})
    nutrients_config = config.get("analyze_nutrients_model", {})

    app_id = os.getenv("EDAMAM_APP_ID")
    app_key = os.getenv("EDAMAM_APP_KEY")
    if not app_id or not app_key:
        raise ValueError("EDAMAM_APP_ID и/или EDAMAM_APP_KEY не найдены в переменных окружения")

    return EdamamFoodSearcher(
        app_id=app_id,
        app_key=app_key,
        base_url=edamam_config.get("base_url"),
        timeout=edamam_config.get("timeout", 30),
        max_results=edamam_config.get("max_results", 10),
        model_name=nutrients_config.get("model", "gpt-4o"),
        temperature=nutrients_config.get("temperature", 0.5),
        max_tokens=nutrients_config.get("max_tokens", 800),
        request_timeout=nutrients_config.get("timeout", 45),
        debug_api_log=DEBUG_API_LOG,
        debug_max_chars=DEBUG_MAX_CHARS
    )


# Загружаем конфигурацию
config = load_config()

# Debug настройки печати сырых ответов API
DEBUG_SETTINGS = config.get("debug", {})
DEBUG_API_LOG = bool(DEBUG_SETTINGS.get("api_log", False))
DEBUG_MAX_CHARS = int(DEBUG_SETTINGS.get("max_print_chars", 2000))

# Настраиваем логирование
logging_config = config.get("logging", {})
api_logger = setup_logging(logging_config)

# Глобальные экземпляры сервисов
analyzer: FoodImageAnalyzer | None = None
food_searcher: EdamamFoodSearcher | None = None


def _require_env_vars(var_names: list[str]) -> None:
    """Проверяет наличие обязательных переменных окружения.

    При отсутствии печатает сообщение в консоль, логирует ошибку и завершает процесс.
    """
    missing = [name for name in var_names if not os.getenv(name)]
    if missing:
        msg = "[STARTUP] Не заданы обязательные переменные окружения: " + ", ".join(missing)
        api_logger.error(msg)
        print("❌ " + msg)
        raise SystemExit(1)


def validate_environment() -> None:
    """Валидирует все необходимые переменные окружения для запуска сервера."""
    _require_env_vars(["OPENAI_API_KEY", "EDAMAM_APP_ID", "EDAMAM_APP_KEY"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    global analyzer, food_searcher

    # Startup
    api_logger.info("[STARTUP] Запуск chain-server...")

    # Проверяем необходимые переменные окружения до инициализации сервисов
    validate_environment()

    try:
        analyzer = create_food_analyzer_with_config(config)
        api_logger.info("[STARTUP] ✅ Анализатор изображений инициализирован")
        print("✅ Анализатор изображений инициализирован")

        # Инициализация анализатора питательных веществ
        food_searcher = create_nutrients_analyzer_with_config(config)
        api_logger.info("[STARTUP] ✅ Анализатор питательных веществ инициализирован")
        print("✅ Анализатор питательных веществ инициализирован")

        api_logger.info("[STARTUP] 🚀 Chain-server готов к работе")

    except Exception as e:
        api_logger.error(f"[STARTUP] Ошибка инициализации сервисов: {str(e)}")
        raise

    yield

    # Shutdown
    api_logger.info("[SHUTDOWN] Завершение работы chain-server...")
    analyzer = None
    food_searcher = None
    api_logger.info("[SHUTDOWN] 🔄 Анализаторы отключены")
    print("🔄 Анализаторы отключены")


class ImageAnalysisRequest(BaseModel):
    """Модель запроса для анализа изображения."""
    image_path: str | None = None
    image_base64: str | None = None
    filename: str | None = None


class ImageAnalysisResponse(BaseModel):
    """Модель ответа с результатами анализа."""
    dishes: list[Dict[str, Any]]
    confidence: float
    error: str | None = None


# Создаем FastAPI приложение с настройками из конфигурации
server_config = config.get("server", {})
app = FastAPI(
    title=server_config.get("title", "Food Image Analyzer API"),
    description=server_config.get("description", "API для анализа изображений еды с помощью LangChain и OpenAI"),
    version=server_config.get("version", "1.0.0"),
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# Добавляем CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_SETTINGS["allow_origins"],
    allow_credentials=CORS_SETTINGS["allow_credentials"],
    allow_methods=CORS_SETTINGS["allow_methods"],
    allow_headers=CORS_SETTINGS["allow_headers"],
)


# Middleware для логирования запросов
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логирует все HTTP запросы."""
    start_time = time.time()

    # Получаем информацию о запросе
    client_ip = request.client.host if request.client else "unknown"
    method = request.method
    url = str(request.url)
    headers = dict(request.headers)
    user_agent = headers.get("user-agent", "unknown")

    # Логируем начало запроса
    api_logger.info(f"[REQUEST] {method} {url} from {client_ip} | UA: {user_agent}")

    # Обрабатываем запрос
    try:
        response = await call_next(request)

        # Вычисляем время обработки
        process_time = time.time() - start_time

        # Логируем завершение запроса
        api_logger.info(
            f"[RESPONSE] {method} {url} | Status: {response.status_code} | "
            f"Time: {process_time:.3f}s | IP: {client_ip}"
        )

        return response

    except Exception as e:
        process_time = time.time() - start_time
        api_logger.error(
            f"[ERROR] {method} {url} | Error: {str(e)} | "
            f"Time: {process_time:.3f}s | IP: {client_ip}"
        )
        raise




def _save_base64_image(image_base64: str, filename: str) -> str:
    """Сохраняет base64 изображение во временный файл."""
    temp_dir = Path(FILES_SETTINGS["temp_dir"])
    temp_dir.mkdir(exist_ok=True)

    # Убираем префикс data:image если есть
    if "," in image_base64:
        image_base64 = image_base64.split(",")[1]

    # Декодируем и сохраняем
    image_data = base64.b64decode(image_base64)
    temp_path = temp_dir / filename

    with open(temp_path, "wb") as f:
        f.write(image_data)

    return str(temp_path)


@app.post("/api/v1/analyze", response_model=ImageAnalysisResponse, tags=["analysis"])
async def analyze_image(request: ImageAnalysisRequest) -> ImageAnalysisResponse:
    """
    Анализирует изображение еды.

    Args:
        request: Запрос с путем к изображению или base64 данными

    Returns:
        Результат анализа изображения
    """
    api_logger.info(f"[ANALYZE] Получен запрос на анализ изображения | filename: {request.filename}")

    if analyzer is None:
        api_logger.error("[ANALYZE] Анализатор не инициализирован")
        raise HTTPException(status_code=500, detail="Анализатор не инициализирован")

    try:
        # Определяем путь к изображению
        if request.image_path:
            image_path = request.image_path
            api_logger.info(f"[ANALYZE] Использую локальный файл: {image_path}")
        elif request.image_base64:
            if not request.filename:
                api_logger.error("[ANALYZE] Не указан filename для base64 изображения")
                raise HTTPException(status_code=400, detail="Для base64 изображения нужен filename")
            image_path = _save_base64_image(request.image_base64, request.filename)
            api_logger.info(f"[ANALYZE] Сохранено base64 изображение: {image_path}")
        else:
            api_logger.error("[ANALYZE] Не указан путь к изображению или base64 данные")
            raise HTTPException(status_code=400, detail="Укажите image_path или image_base64")

        # Анализируем изображение
        api_logger.info(f"[ANALYZE] Начинаю анализ изображения: {image_path}")
        result = analyzer.analyze_image(image_path)

        # Логируем результат
        if result.get("error"):
            api_logger.error(f"[ANALYZE] Ошибка анализа: {result['error']}")
        else:
            dishes_count = len(result.get("dishes", []))
            confidence = result.get("confidence", 0)
            api_logger.info(f"[ANALYZE] Анализ завершен | блюд: {dishes_count} | уверенность: {confidence:.2%}")

        # Удаляем временный файл если создавали
        if request.image_base64:
            try:
                os.remove(image_path)
                api_logger.debug(f"[ANALYZE] Удален временный файл: {image_path}")
            except Exception as cleanup_error:
                api_logger.warning(f"[ANALYZE] Не удалось удалить временный файл {image_path}: {cleanup_error}")

        return ImageAnalysisResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"[ANALYZE] Неожиданная ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/analyze-nutrients", tags=["nutrients"])
async def analyze_nutrients(request: FoodSearchRequest) -> Dict[str, Any]:
    """
    Анализ питательных веществ блюда через Edamam Food Database API.

    Args:
        request: Запрос с названием блюда

    Returns:
        Результат анализа питательных веществ
    """
    api_logger.info(f"[NUTRIENTS] Запрос анализа нутриентов | блюдо: '{request.dish}' | количество: {request.amount} {request.unit}")

    if food_searcher is None:
        api_logger.error("[NUTRIENTS] Поисковик еды не инициализирован")
        raise HTTPException(status_code=500, detail="Поисковик еды не инициализирован")

    try:
        result = food_searcher.analyze_dish_nutrients(request.dish, request.amount, request.unit)

        # Логируем результат
        if result.get("error"):
            api_logger.error(f"[NUTRIENTS] Ошибка анализа нутриентов для '{request.dish}': {result['error']}")
        else:
            calories = result.get("calories", 0)
            protein = result.get("protein", 0)
            api_logger.info(f"[NUTRIENTS] Анализ завершен для '{request.dish}' | калории: {calories:.1f} ккал | белки: {protein:.1f} г")

        return result
    except Exception as e:
        api_logger.error(f"[NUTRIENTS] Неожиданная ошибка при анализе '{request.dish}': {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/analyze-full", tags=["analysis"])
async def analyze_full(request: ImageAnalysisRequest) -> Dict[str, Any]:
    """
    Комбинированный эндпоинт: принимает изображение, определяет блюда и
    рассчитывает нутриенты для всех найденных блюд одним запросом.

    Возвращает объект вида:
      {
        "analysis": ImageAnalysisResponse,
        "nutrients": Dict[str, Any]
      }
    """
    api_logger.info("[FULL] Получен запрос на полный анализ изображения")

    if analyzer is None or food_searcher is None:
        api_logger.error("[FULL] Анализатор(ы) не инициализированы")
        raise HTTPException(status_code=500, detail="Анализаторы не инициализированы")

    # Вспомогательная конвертация единиц в формат, ожидаемый нутриент‑анализом
    def _unit_ru_to_en(unit_ru: str) -> str:
        mapping = {
            "штук": "pieces",
            "кусок": "piece",
            "ломтик": "slice",
            "чашка": "cup",
            "грамм": "gram",
        }
        return mapping.get(unit_ru.strip().lower(), "gram")

    try:
        # 1) Получаем путь к изображению
        if request.image_path:
            image_path = request.image_path
            api_logger.info(f"[FULL] Использую локальный файл: {image_path}")
        elif request.image_base64:
            if not request.filename:
                api_logger.error("[FULL] Не указан filename для base64 изображения")
                raise HTTPException(status_code=400, detail="Для base64 изображения нужен filename")
            image_path = _save_base64_image(request.image_base64, request.filename)
            api_logger.info(f"[FULL] Сохранено base64 изображение: {image_path}")
        else:
            api_logger.error("[FULL] Не указан путь к изображению или base64 данные")
            raise HTTPException(status_code=400, detail="Укажите image_path или image_base64")

        # 2) Анализ изображения → блюда
        api_logger.info(f"[FULL] Запускаю анализ изображения: {image_path}")
        analysis = analyzer.analyze_image(image_path)

        if analysis.get("error"):
            api_logger.error(f"[FULL] Ошибка анализа изображения: {analysis['error']}")
            # Удаляем временный файл если создавали
            if request.image_base64:
                try:
                    os.remove(image_path)
                except Exception:
                    pass
            return {"analysis": analysis, "nutrients": {"error": analysis.get("error")}}

        dishes = analysis.get("dishes", []) or []

        # 3) Готовим запрос для множественного анализа нутриентов
        items: list[MultipleDishItem] = []
        for dish in dishes:
            name_en = (dish.get("name_en") or dish.get("name") or "").strip()
            amount = dish.get("amount") or 100
            unit_ru = dish.get("unit_type") or "грамм"
            unit_en = _unit_ru_to_en(unit_ru)
            if name_en:
                items.append(MultipleDishItem(dish=name_en, amount=float(amount), unit=unit_en))

        nutrients: Dict[str, Any]
        if items:
            api_logger.info(f"[FULL] Анализирую нутриенты для {len(items)} блюд")
            nutrients = food_searcher.analyze_multiple_dishes_nutrients(items)
        else:
            nutrients = {"dishes": [], "total_dishes": 0, "successful_dishes": 0, "failed_dishes": 0}

        # 4) Убираем временный файл если создавали
        if request.image_base64:
            try:
                os.remove(image_path)
                api_logger.debug(f"[FULL] Удален временный файл: {image_path}")
            except Exception as cleanup_error:
                api_logger.warning(f"[FULL] Не удалось удалить временный файл {image_path}: {cleanup_error}")

        return {"analysis": analysis, "nutrients": nutrients}

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"[FULL] Неожиданная ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/analyze-multiple-nutrients", tags=["nutrients"])
async def analyze_multiple_nutrients(request: MultipleDishesRequest) -> Dict[str, Any]:
    """
    Анализ питательных веществ множественных блюд через Edamam Food Database API.
    Отправляет один запрос к LLM для всех блюд вместо отдельных запросов.

    Args:
        request: Запрос со списком блюд

    Returns:
        Результат анализа питательных веществ для всех блюд
    """
    dishes_str = ", ".join([f"'{dish.dish}'" for dish in request.dishes[:3]])
    if len(request.dishes) > 3:
        dishes_str += f" и ещё {len(request.dishes) - 3} блюд"

    api_logger.info(f"[MULTIPLE_NUTRIENTS] Запрос анализа нутриентов множественных блюд | блюд: {len(request.dishes)} | {dishes_str}")

    if food_searcher is None:
        api_logger.error("[MULTIPLE_NUTRIENTS] Поисковик еды не инициализирован")
        raise HTTPException(status_code=500, detail="Поисковик еды не инициализирован")

    try:
        result = food_searcher.analyze_multiple_dishes_nutrients(request.dishes)

        # Логируем результат
        if result.get("error"):
            api_logger.error(f"[MULTIPLE_NUTRIENTS] Ошибка анализа множественных нутриентов: {result['error']}")
        else:
            total_dishes = result.get("total_dishes", 0)
            successful_dishes = result.get("successful_dishes", 0)
            failed_dishes = result.get("failed_dishes", 0)

            # Считаем общие калории
            total_calories = sum([dish.get("calories", 0) for dish in result.get("dishes", [])])

            api_logger.info(f"[MULTIPLE_NUTRIENTS] Анализ завершен | всего блюд: {total_dishes} | успешно: {successful_dishes} | ошибки: {failed_dishes} | общие калории: {total_calories:.1f} ккал")

        return result
    except Exception as e:
        api_logger.error(f"[MULTIPLE_NUTRIENTS] Неожиданная ошибка при анализе множественных блюд: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/health", tags=["health"])
async def health_check():
    """Проверка состояния сервера."""
    status = {
        "status": "healthy",
        "image_analyzer_ready": analyzer is not None,
        "nutrients_analyzer_ready": food_searcher is not None,
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY"))
    }

    api_logger.debug(f"[HEALTH] Проверка состояния | image_analyzer: {status['image_analyzer_ready']} | nutrients_analyzer: {status['nutrients_analyzer_ready']}")

    return status


# Создаем цепочки для LangServe
def create_langserve_chain():
    """Создает цепочку для LangServe."""

    def analyze_wrapper(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Обертка для анализа изображения."""
        if analyzer is None:
            return {"error": "Анализатор не инициализирован"}

        image_path = inputs.get("image_path")
        if not image_path:
            return {"error": "Не указан путь к изображению"}

        return analyzer.analyze_image(image_path)

    return RunnableLambda(analyze_wrapper)


def create_nutrient_analysis_chain():
    """Создает цепочку для анализа питательных веществ через Edamam API."""

    def analysis_wrapper(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Обертка для анализа питательных веществ блюда."""
        if food_searcher is None:
            return {"error": "Анализатор питательных веществ не инициализирован"}

        dish = inputs.get("dish")
        amount = inputs.get("amount", 100)
        unit = inputs.get("unit", "грамм")

        if not dish:
            return {"error": "Не указано блюдо для анализа"}

        result = food_searcher.analyze_dish_nutrients(dish, amount, unit)

        # Возвращаем результат как есть (либо nutrients, либо error)
        return result

    return RunnableLambda(analysis_wrapper)


def create_multiple_nutrient_analysis_chain():
    """Создает цепочку для анализа питательных веществ множественных блюд через Edamam API."""

    def multiple_analysis_wrapper(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Обертка для анализа питательных веществ множественных блюд."""
        if food_searcher is None:
            return {"error": "Анализатор питательных веществ не инициализирован"}

        dishes_data = inputs.get("dishes", [])
        if not dishes_data:
            return {"error": "Не указаны блюда для анализа"}

        # Преобразуем входные данные в список MultipleDishItem
        dishes = []
        for dish_data in dishes_data:
            if isinstance(dish_data, dict):
                dishes.append(MultipleDishItem(
                    dish=dish_data.get("dish", ""),
                    amount=dish_data.get("amount", 100),
                    unit=dish_data.get("unit", "gram")
                ))

        if not dishes:
            return {"error": "Некорректный формат данных о блюдах"}

        result = food_searcher.analyze_multiple_dishes_nutrients(dishes)

        # Возвращаем результат как есть
        return result

    return RunnableLambda(multiple_analysis_wrapper)


# Добавляем LangServe маршруты
add_routes(
    app,
    create_langserve_chain(),
    path=LANGSERVE_SETTINGS["path"],
    playground_type=LANGSERVE_SETTINGS["playground_type"]
)

# Добавляем цепочку анализа питательных веществ
add_routes(
    app,
    create_nutrient_analysis_chain(),
    path="/api/v1/analyze-nutrients",
    playground_type=LANGSERVE_SETTINGS["playground_type"]
)

# Добавляем цепочку анализа питательных веществ для множественных блюд
add_routes(
    app,
    create_multiple_nutrient_analysis_chain(),
    path="/api/v1/analyze-multiple-nutrients",
    playground_type=LANGSERVE_SETTINGS["playground_type"]
)


# Кастомная генерация OpenAPI: скрываем LangServe эндпоинты из документации
def custom_openapi():
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    paths = schema.get("paths", {})

    def _is_langserve_path(path: str) -> bool:
        if path.startswith("/langserve"):
            return True
        if path.startswith("/api/v1/analyze-nutrients/"):
            return True
        if path.startswith("/api/v1/analyze-multiple-nutrients/"):
            return True
        return False

    filtered_paths = {p: v for p, v in paths.items() if not _is_langserve_path(p)}
    schema["paths"] = filtered_paths
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn

    # Запуск сервера с настройками из конфигурации
    server_config = config.get("server", {})
    uvicorn.run(
        app,
        host=server_config.get("host", "0.0.0.0"),
        port=server_config.get("port", 8000),
        log_level=server_config.get("log_level", "info")
    )