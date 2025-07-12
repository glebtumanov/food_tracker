"""
Цепочка для анализа изображений еды с помощью LangChain и OpenAI API.

Принимает изображение еды и возвращает JSON с блюдами и их примерной массой.
"""

import os
import base64
from pathlib import Path
from typing import Dict, List, Any, Literal
import json

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from pydantic import BaseModel, Field


class FoodItem(BaseModel):
    """Модель для описания блюда."""
    name: str = Field(description="Название блюда на русском")
    name_en: str = Field(description="Название блюда на английском")
    description: str = Field(description="Краткое описание блюда на русском")
    description_en: str = Field(description="Краткое описание блюда на английском")
    unit_type: Literal["штук", "грамм", "чашка", "кусок", "ломтик"] = Field(description="Мера измерения")
    amount: float = Field(description="Количество блюда в единицах unit_type")


class FoodAnalysis(BaseModel):
    """Модель для результата анализа изображения."""
    dishes: List[FoodItem] = Field(description="Список блюд на изображении")
    confidence: float = Field(description="Уверенность в анализе от 0 до 1")


class FoodImageAnalyzer:
    """Анализатор изображений еды с помощью OpenAI Vision API."""

    def __init__(self, model_name: str = "gpt-4o", temperature: float = 0.1, max_tokens: int = 1000):
        """
        Инициализация анализатора.

        Args:
            model_name: Название модели OpenAI для анализа изображений
            temperature: Температура для генерации (0.0 - 1.0)
            max_tokens: Максимальное количество токенов в ответе
        """
        self.model_name = model_name
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens
        )
        self.parser = JsonOutputParser(pydantic_object=FoodAnalysis)

        # Системный промпт для анализа изображений еды
        self.system_prompt = """
        Ты эксперт по питанию и кулинарии. Анализируй изображения еды и определяй:

        1. Все блюда и продукты на изображении
        2. Названия блюд на русском и английском языках
        3. Описания блюд на русском и английском языках
        4. Подходящую единицу измерения для каждого блюда
        5. Количество каждого блюда в указанных единицах

        Правила анализа:
        - Будь максимально точен в определении блюд
        - Для unit_type используй только: "штук", "грамм", "чашка", "кусок", "ломтик"
        - Выбирай наиболее подходящую единицу измерения:
          * "штук" - для целых предметов (яйца, яблоки, печенья, котлеты)
          * "грамм" - для блюд без четких границ (каши, салаты, жидкости)
          * "чашка" - для напитков и жидких блюд
          * "кусок" - для продуктов, которые режутся кусками (торт, сыр, сахар)
          * "ломтик" - для хлеба, колбасы, мяса, нарезанных овощей
        - Количество указывай точно, учитывая видимые порции
        - Если на изображении несколько одинаковых блюд, указывай общее количество
        - Переводи названия и описания на английский точно и корректно
        - Указывай уверенность в анализе (0-1)

        Возвращай результат строго в указанном JSON формате.
        """

        self._build_chain()

    def _encode_image(self, image_path: str) -> str:
        """Кодирует изображение в base64."""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _prepare_image_message(self, image_path: str) -> Dict[str, Any]:
        """Подготавливает сообщение с изображением для OpenAI API."""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Изображение не найдено: {image_path}")

        # Проверяем тип файла
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        if Path(image_path).suffix.lower() not in allowed_extensions:
            raise ValueError(f"Неподдерживаемый формат файла: {Path(image_path).suffix}")

        base64_image = self._encode_image(image_path)

        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_image}",
                "detail": "high"
            }
        }

    def _build_chain(self):
        """Строит цепочку для анализа изображений."""

        def create_message(inputs: Dict[str, Any]) -> List[HumanMessage]:
            """Создает сообщение с изображением и текстом."""
            image_path = inputs["image_path"]

            image_content = self._prepare_image_message(image_path)

            content = [
                {
                    "type": "text",
                    "text": f"{self.system_prompt}\n\nФормат ответа:\n{self.parser.get_format_instructions()}"
                },
                image_content
            ]

            return [HumanMessage(content=content)]

        # Создаем цепочку
        self.chain = (
            RunnableLambda(create_message)
            | self.llm
            | self.parser
        )

    def analyze_image(self, image_path: str) -> Dict[str, Any]:
        """
        Анализирует изображение еды и возвращает JSON с блюдами.

        Args:
            image_path: Путь к файлу изображения

        Returns:
            Словарь с результатами анализа
        """
        try:
            result = self.chain.invoke({"image_path": image_path})
            return result
        except Exception as e:
            return {
                "error": str(e),
                "dishes": [],
                "confidence": 0.0
            }

    def analyze_batch(self, image_paths: List[str]) -> List[Dict[str, Any]]:
        """
        Анализирует несколько изображений.

        Args:
            image_paths: Список путей к изображениям

        Returns:
            Список результатов анализа
        """
        results = []
        for image_path in image_paths:
            result = self.analyze_image(image_path)
            results.append(result)
        return results


def create_food_analyzer() -> FoodImageAnalyzer:
    """Создает экземпляр анализатора изображений еды."""
    return FoodImageAnalyzer()