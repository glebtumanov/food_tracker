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
import asyncio
import sqlite3
import json
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid

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


# ==========================
# Хранилище задач (SQLite)
# ==========================
JOBS_DB_PATH = Path("jobs.sqlite3")


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(JOBS_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Создает таблицу job при необходимости."""
    with _db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT,
                result_json TEXT,
                image_url TEXT,
                params_json TEXT
            )
            """
        )
        conn.commit()


def _utc_now_str() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def insert_job(image_url: str | None, params: Dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    now = _utc_now_str()
    with _db_connect() as conn:
        conn.execute(
            "INSERT INTO job (id, status, created_at, updated_at, error, result_json, image_url, params_json)\n             VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)",
            (job_id, "queued", now, now, image_url, json.dumps(params, ensure_ascii=False)),
        )
        conn.commit()
    return job_id


def update_job_status(job_id: str, status: str, error: str | None = None) -> None:
    now = _utc_now_str()
    with _db_connect() as conn:
        conn.execute(
            "UPDATE job SET status = ?, updated_at = ?, error = ? WHERE id = ?",
            (status, now, error, job_id),
        )
        conn.commit()


def update_job_result(job_id: str, result: Dict[str, Any]) -> None:
    now = _utc_now_str()
    with _db_connect() as conn:
        conn.execute(
            "UPDATE job SET status = ?, updated_at = ?, result_json = ? WHERE id = ?",
            ("done", now, json.dumps(result, ensure_ascii=False), job_id),
        )
        conn.commit()


def get_job(job_id: str) -> Dict[str, Any] | None:
    with _db_connect() as conn:
        cur = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {k: row[k] for k in row.keys()}


# ==========================
# Общие вспомогательные функции анализа
# ==========================
def unit_ru_to_en(unit_ru: str) -> str:
    mapping = {
        "штук": "pieces",
        "кусок": "piece",
        "ломтик": "slice",
        "чашка": "cup",
        "грамм": "gram",
    }
    return mapping.get(unit_ru.strip().lower(), "gram")


def _download_image(url: str, filename_hint: str | None = None) -> str:
    """Скачивает изображение по URL во временную папку и возвращает локальный путь."""
    temp_dir = Path(FILES_SETTINGS["temp_dir"])  # type: ignore[index]
    temp_dir.mkdir(exist_ok=True)
    safe_name = filename_hint or f"download_{uuid.uuid4().hex}.img"
    temp_path = temp_dir / safe_name
    try:
        with urlopen(url) as resp, open(temp_path, "wb") as out:
            out.write(resp.read())
    except (URLError, HTTPError) as e:
        raise ValueError(f"Не удалось скачать изображение по URL: {e}")
    return str(temp_path)


def resolve_image_source(image_path: str | None, image_base64: str | None, filename: str | None, image_url: str | None) -> tuple[str, bool]:
    """Возвращает локальный путь к изображению и флаг, что файл временный."""
    if image_path:
        return image_path, False
    if image_base64:
        if not filename:
            raise HTTPException(status_code=400, detail="Для base64 изображения нужен filename")
        return _save_base64_image(image_base64, filename), True
    if image_url:
        return _download_image(image_url, filename), True
    raise HTTPException(status_code=400, detail="Укажите image_path, image_base64 или image_url")


def compute_image_analysis_by_path(image_path: str) -> Dict[str, Any]:
    if analyzer is None:
        raise HTTPException(status_code=500, detail="Анализатор не инициализирован")

    api_logger.info(f"[ANALYSIS] Запускаю анализ изображения: {image_path}")
    analysis = analyzer.analyze_image(image_path)
    if analysis.get("error"):
        api_logger.error(f"[ANALYSIS] Ошибка анализа изображения: {analysis['error']}")
    return {"analysis": analysis}


def compute_full_analysis_by_path(image_path: str) -> Dict[str, Any]:
    if analyzer is None or food_searcher is None:
        raise HTTPException(status_code=500, detail="Анализаторы не инициализированы")

    api_logger.info(f"[FULL] Запускаю анализ изображения: {image_path}")
    analysis = analyzer.analyze_image(image_path)
    if analysis.get("error"):
        api_logger.error(f"[FULL] Ошибка анализа изображения: {analysis['error']}")
        return {"analysis": analysis, "nutrients": {"error": analysis.get("error")}}

    dishes = analysis.get("dishes", []) or []
    items: list[MultipleDishItem] = []
    for dish in dishes:
        name_en = (dish.get("name_en") or dish.get("name") or "").strip()
        amount = dish.get("amount") or 100
        unit_ru = dish.get("unit_type") or "грамм"
        unit_en = unit_ru_to_en(unit_ru)
        if name_en:
            items.append(MultipleDishItem(dish=name_en, amount=float(amount), unit=unit_en))

    if items:
        try:
            api_logger.info(f"[FULL] Анализирую нутриенты для {len(items)} блюд")
            nutrients = food_searcher.analyze_multiple_dishes_nutrients(items)
        except Exception as e:
            api_logger.error(f"[FULL] Ошибка анализа нутриентов: {e}")
            nutrients = {"error": str(e), "dishes": []}
    else:
        nutrients = {"dishes": [], "total_dishes": 0, "successful_dishes": 0, "failed_dishes": 0}

    return {"analysis": analysis, "nutrients": nutrients}


# Хранилище активных задач (для отслеживания жизненного цикла в процессе)
JOB_TASKS: dict[str, asyncio.Task] = {}


async def process_job(job_id: str) -> None:
    """Фоновая обработка задачи анализа (analysis | full)."""
    api_logger.info(f"[JOB] Старт обработки job={job_id}")
    update_job_status(job_id, "processing", None)

    job = get_job(job_id)
    if job is None:
        api_logger.error(f"[JOB] job={job_id} не найдено")
        return

    params_json = job.get("params_json") or "{}"
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as e:
        update_job_status(job_id, "error", f"Некорректный params_json: {e}")
        return

    image_path_in = params.get("image_path")
    image_base64_in = params.get("image_base64")
    filename_in = params.get("filename")
    image_url_in = params.get("image_url") or job.get("image_url")
    mode = (params.get("params") or {}).get("mode", "full")

    temp_created = False
    resolved_path = ""
    try:
        resolved_path, temp_created = resolve_image_source(image_path_in, image_base64_in, filename_in, image_url_in)
        if mode == "analysis":
            result = compute_image_analysis_by_path(resolved_path)
        else:
            result = compute_full_analysis_by_path(resolved_path)
        if result.get("analysis", {}).get("error"):
            update_job_status(job_id, "error", str(result["analysis"].get("error")))
            return
        update_job_result(job_id, result)
        api_logger.info(f"[JOB] Готово job={job_id}")
    except HTTPException as he:
        update_job_status(job_id, "error", he.detail if isinstance(he.detail, str) else str(he.detail))
    except Exception as e:
        api_logger.error(f"[JOB] Ошибка job={job_id}: {e}")
        update_job_status(job_id, "error", str(e))
    finally:
        if temp_created and resolved_path:
            try:
                os.remove(resolved_path)
            except Exception:
                pass

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
        # Инициализация БД задач
        init_db()
        api_logger.info("[STARTUP] ✅ База задач инициализирована")

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
    """Сохранено для совместимости (не используется напрямую)."""
    dishes: list[Dict[str, Any]]
    confidence: float
    error: str | None = None


class JobCreateRequest(BaseModel):
    """Запрос на создание задачи анализа."""
    image_path: str | None = None
    image_base64: str | None = None
    filename: str | None = None
    image_url: str | None = None
    params: Dict[str, Any] | None = None


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    id: str
    status: str
    created_at: str
    updated_at: str
    error: str | None = None
    result: Dict[str, Any] | None = None
    image_url: str | None = None


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


# Middleware для установки X-Request-ID и Idempotency-Key
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    idempotency_key = request.headers.get("idempotency-key")

    # Прокидываем в request.state
    request.state.request_id = request_id
    request.state.idempotency_key = idempotency_key

    response = await call_next(request)
    # Пробрасываем X-Request-ID в ответ
    response.headers["X-Request-ID"] = request_id
    return response


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

    # Идентификаторы запроса
    request_id = getattr(request.state, "request_id", headers.get("x-request-id", "unknown"))

    # Логируем начало запроса
    api_logger.info(f"[REQUEST] rid={request_id} | {method} {url} from {client_ip} | UA: {user_agent}")

    # Обрабатываем запрос
    try:
        response = await call_next(request)

        # Вычисляем время обработки
        process_time = time.time() - start_time

        # Логируем завершение запроса
        api_logger.info(
            f"[RESPONSE] rid={request_id} | {method} {url} | Status: {response.status_code} | "
            f"Time: {process_time:.3f}s | IP: {client_ip}"
        )

        return response

    except Exception as e:
        process_time = time.time() - start_time
        api_logger.error(
            f"[ERROR] rid={request_id} | {method} {url} | Error: {str(e)} | "
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


@app.post("/api/v1/analyze", response_model=JobCreateResponse, tags=["analysis"])
async def analyze_image_async(request: ImageAnalysisRequest) -> JobCreateResponse:
    """Асинхронный анализ изображения: ставит задачу (mode=analysis) и возвращает job_id."""
    if not (request.image_path or request.image_base64 or request.filename or request):
        raise HTTPException(status_code=400, detail="Укажите image_path или image_base64")
    params: Dict[str, Any] = {
        "image_path": request.image_path,
        "image_base64": request.image_base64,
        "filename": request.filename,
        "params": {"mode": "analysis"},
    }
    job_id = insert_job(None, params)
    JOB_TASKS[job_id] = asyncio.create_task(process_job(job_id))
    return JobCreateResponse(job_id=job_id, status="queued")


# Удалён синхронный эндпоинт нутриентов: нутриенты считаются только в режиме полной задачи


@app.post("/api/v1/analyze-full", response_model=JobCreateResponse, tags=["analysis"])
async def analyze_full_async(request: ImageAnalysisRequest) -> JobCreateResponse:
    """Асинхронный полный анализ изображения: ставит задачу (mode=full) и возвращает job_id."""
    if not (request.image_path or request.image_base64 or request.filename or request):
        raise HTTPException(status_code=400, detail="Укажите image_path или image_base64")
    params: Dict[str, Any] = {
        "image_path": request.image_path,
        "image_base64": request.image_base64,
        "filename": request.filename,
        "params": {"mode": "full"},
    }
    job_id = insert_job(None, params)
    JOB_TASKS[job_id] = asyncio.create_task(process_job(job_id))
    return JobCreateResponse(job_id=job_id, status="queued")

# Удалён эндпоинт множественного анализа нутриентов (не используется в асинхронной модели)


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


# Убраны LangServe цепочки и кастомизация OpenAPI — остаются только асинхронные REST эндпоинты


@app.post("/api/v1/jobs", response_model=JobCreateResponse, tags=["jobs"])
async def create_job(request: JobCreateRequest) -> JobCreateResponse:
    """Создает задачу полного анализа изображения и ставит её в очередь."""
    if not (request.image_path or request.image_base64 or request.image_url):
        raise HTTPException(status_code=400, detail="Укажите image_path, image_base64 или image_url")

    params: Dict[str, Any] = {
        "image_path": request.image_path,
        "image_base64": request.image_base64,
        "filename": request.filename,
        "image_url": request.image_url,
        "params": request.params or {},
    }
    job_id = insert_job(request.image_url, params)
    task = asyncio.create_task(process_job(job_id))
    JOB_TASKS[job_id] = task
    api_logger.info(f"[JOBS] Создана задача job={job_id}")
    return JobCreateResponse(job_id=job_id, status="queued")


@app.get("/api/v1/jobs/{job_id}", response_model=JobStatusResponse, tags=["jobs"])
async def get_job_status(job_id: str) -> JobStatusResponse:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    result: Dict[str, Any] | None = None
    if job.get("result_json"):
        try:
            result = json.loads(job["result_json"])
        except json.JSONDecodeError:
            result = None

    return JobStatusResponse(
        id=job["id"],
        status=job["status"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        error=job.get("error"),
        result=result,
        image_url=job.get("image_url"),
    )


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