"""
LangServe сервер для анализа изображений еды.

Запуск: python server.py
"""

import os
import base64
import yaml
from typing import Dict, Any
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langserve import add_routes
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from food_analyzer import FoodImageAnalyzer


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


def create_food_analyzer_with_config(config: Dict[str, Any]) -> FoodImageAnalyzer:
    """Создает анализатор с настройками из конфигурации."""
    openai_config = config.get("openai", {})

    return FoodImageAnalyzer(
        model_name=openai_config.get("model", "gpt-4o"),
        temperature=openai_config.get("temperature", 0.1),
        max_tokens=openai_config.get("max_tokens", 1000)
    )


# Загружаем конфигурацию
config = load_config()

# Глобальный экземпляр анализатора
analyzer: FoodImageAnalyzer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    global analyzer

    # Startup
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY не найден в переменных окружения")

    analyzer = create_food_analyzer_with_config(config)
    print("✅ Анализатор изображений инициализирован")

    yield

    # Shutdown
    analyzer = None
    print("🔄 Анализатор отключен")


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


@app.post("/analyze", response_model=ImageAnalysisResponse)
async def analyze_image(request: ImageAnalysisRequest) -> ImageAnalysisResponse:
    """
    Анализирует изображение еды.

    Args:
        request: Запрос с путем к изображению или base64 данными

    Returns:
        Результат анализа изображения
    """
    if analyzer is None:
        raise HTTPException(status_code=500, detail="Анализатор не инициализирован")

    try:
        # Определяем путь к изображению
        if request.image_path:
            image_path = request.image_path
        elif request.image_base64:
            if not request.filename:
                raise HTTPException(status_code=400, detail="Для base64 изображения нужен filename")
            image_path = _save_base64_image(request.image_base64, request.filename)
        else:
            raise HTTPException(status_code=400, detail="Укажите image_path или image_base64")

        # Анализируем изображение
        result = analyzer.analyze_image(image_path)

        # Удаляем временный файл если создавали
        if request.image_base64:
            try:
                os.remove(image_path)
            except:
                pass

        return ImageAnalysisResponse(**result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))





@app.get("/health")
async def health_check():
    """Проверка состояния сервера."""
    return {
        "status": "healthy",
        "analyzer_ready": analyzer is not None,
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY"))
    }


# Создаем цепочку для LangServe
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


# Добавляем LangServe маршруты
add_routes(
    app,
    create_langserve_chain(),
    path=LANGSERVE_SETTINGS["path"],
    playground_type=LANGSERVE_SETTINGS["playground_type"]
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