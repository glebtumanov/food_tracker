"""
Цепочка для анализа изображений еды с помощью LangChain и OpenAI API.

Принимает изображение еды и возвращает JSON с блюдами и их примерной массой.
"""

import os
import base64
from pathlib import Path
from typing import Dict, List, Any, Literal
import json
import requests

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


class FoodSearchRequest(BaseModel):
    """Модель запроса для анализа питательных веществ."""
    dish: str = Field(description="Название блюда для анализа")
    amount: float = Field(description="Количество блюда")
    unit: str = Field(default="грамм", description="Единица измерения (грамм, штук, чашка, кусок, ломтик)")


class NutrientAnalysis(BaseModel):
    """Модель результата анализа питательных веществ."""
    dish_name: str = Field(description="Название блюда с количеством")
    calories: float = Field(description="Калории в ккал")
    protein: float = Field(description="Белки в граммах")
    fat: float = Field(description="Жиры в граммах")
    carbohydrates: float = Field(description="Углеводы в граммах")
    fiber: float = Field(description="Клетчатка в граммах")


class EdamamFoodSearcher:
    """Анализатор питательных веществ через Edamam API и OpenAI."""

    def __init__(self, app_id: str, app_key: str, base_url: str, timeout: int = 30, max_results: int = 3,
                 model_name: str = "gpt-4o", temperature: float = 0.5, max_tokens: int = 800,
                 request_timeout: int = 45):
        """
        Инициализация анализатора.

        Args:
            app_id: ID приложения Edamam
            app_key: Ключ приложения Edamam
            base_url: Базовый URL API
            timeout: Таймаут запроса к Edamam API в секундах
            max_results: Максимальное количество результатов
            model_name: Название модели OpenAI
            temperature: Температура для генерации
            max_tokens: Максимальное количество токенов
            request_timeout: Таймаут запроса к OpenAI API в секундах
        """
        self.app_id = app_id
        self.app_key = app_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_results = max_results

        # Инициализация OpenAI модели для анализа питательных веществ
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout
        )
        self.nutrient_parser = JsonOutputParser(pydantic_object=NutrientAnalysis)

        # Системный промпт для анализа питательных веществ
        self.nutrient_prompt = """
        Ты эксперт по питанию. Проанализируй данные о еде из Edamam API и определи питательную ценность блюда.

        ВАЖНО: Все данные в Edamam API указаны на 100 грамм продукта!

        Алгоритм расчета:
        1. Изучи JSON данные от Edamam API
        2. Найди наиболее подходящий продукт для указанного блюда в разделах "parsed" или "hints"
        3. Возьми значения питательных веществ из поля "nutrients" (они даны на 100г)
        4. ОБЯЗАТЕЛЬНО пересчитай на указанное количество по формуле:
           Итоговое_значение = (Значение_на_100г * Указанное_количество_в_граммах) / 100

        Правила расчета:
        - ВСЕ данные из API даны на 100г - это критически важно!
        - Для "грамм": используй указанное количество напрямую
        - Для "штук": 1 штука = ~150г (средний размер)
        - Для "кусок": 1 кусок = ~100г
        - Для "ломтик": 1 ломтик = ~50г
        - Для "чашка": 1 чашка = ~200г
        - Округляй результаты до 2 знаков после запятой
        - В поле dish_name укажи название блюда с количеством, как указано в запросе

        Пример расчета: если продукт содержит 108 ккал на 100г, а нужно рассчитать для 200г, то:
        Калории = (108 * 200) / 100 = 216 ккал

        Возвращай результат строго в указанном JSON формате.
        """

        self._build_chain()

    def _search_single_dish(self, dish_name: str) -> Dict[str, Any]:
        """Поиск одного блюда в Edamam API."""
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "ingr": dish_name,
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()

            # Ограничиваем количество результатов
            if "parsed" in data and len(data["parsed"]) > self.max_results:
                data["parsed"] = data["parsed"][:self.max_results]
            if "hints" in data and len(data["hints"]) > self.max_results:
                data["hints"] = data["hints"][:self.max_results]

            return {
                "dish_name": dish_name,
                "success": True,
                "data": data
            }

        except requests.exceptions.RequestException as e:
            return {
                "dish_name": dish_name,
                "success": False,
                "error": str(e),
                "data": None
            }

    def _analyze_nutrients_with_llm(self, edamam_data: Dict[str, Any], dish: str, amount: float, unit: str) -> Dict[str, Any]:
        """Анализ питательных веществ через OpenAI на основе данных Edamam."""
        try:
            # Формируем полное название блюда с количеством
            dish_with_amount = f"{dish} ({amount} {unit})"

            # Формируем запрос для LLM
            user_query = f"""
            Блюдо: {dish}
            Количество: {amount} {unit}

            Данные от Edamam API:
            {json.dumps(edamam_data, ensure_ascii=False, indent=2)}

            Проанализируй и рассчитай питательную ценность для указанного количества блюда.
            В поле dish_name укажи: "{dish_with_amount}"
            """

            # Создаем сообщение
            messages = [
                HumanMessage(content=f"{self.nutrient_prompt}\n\nФормат ответа:\n{self.nutrient_parser.get_format_instructions()}\n\n{user_query}")
            ]

            # Получаем ответ от LLM
            response = self.llm.invoke(messages)
            nutrients = self.nutrient_parser.parse(response.content)

            return {
                "success": True,
                "nutrients": nutrients
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка анализа питательных веществ: {str(e)}",
                "nutrients": None
            }

    def _build_chain(self):
        """Строит цепочку для анализа питательных веществ блюда."""

        def analyze_dish_nutrients(inputs: Dict[str, Any]) -> Dict[str, Any]:
            """Анализ питательных веществ блюда."""
            dish = inputs.get("dish", "").strip()
            amount = inputs.get("amount", 100)
            unit = inputs.get("unit", "грамм")

            if not dish:
                return {
                    "error": "Не указано блюдо для анализа"
                }

            # Сначала получаем данные от Edamam
            edamam_result = self._search_single_dish(dish)

            if not edamam_result.get("success"):
                return {
                    "error": edamam_result.get("error", "Ошибка получения данных от Edamam API")
                }

                        # Затем анализируем питательные вещества через LLM
            nutrients_result = self._analyze_nutrients_with_llm(
                edamam_result["data"], dish, amount, unit
            )

            # Возвращаем только nutrients
            if nutrients_result["success"]:
                return nutrients_result["nutrients"]
            else:
                return {
                    "error": edamam_result.get("error") or nutrients_result.get("error")
                }

        self.chain = RunnableLambda(analyze_dish_nutrients)

    def analyze_dish_nutrients(self, dish: str, amount: float = 100, unit: str = "грамм") -> Dict[str, Any]:
        """
        Анализ питательных веществ блюда.

        Args:
            dish: Название блюда
            amount: Количество блюда
            unit: Единица измерения

        Returns:
            Результат анализа питательных веществ
        """
        return self.chain.invoke({"dish": dish, "amount": amount, "unit": unit})


def create_food_analyzer() -> FoodImageAnalyzer:
    """Создает экземпляр анализатора изображений еды."""
    return FoodImageAnalyzer()


def create_food_searcher(app_id: str, app_key: str, base_url: str, timeout: int = 30, max_results: int = 10,
                        model_name: str = "gpt-4o", temperature: float = 0.5, max_tokens: int = 800,
                        request_timeout: int = 45) -> EdamamFoodSearcher:
    """Создает экземпляр анализатора питательных веществ."""
    return EdamamFoodSearcher(app_id, app_key, base_url, timeout, max_results, model_name, temperature,
                             max_tokens, request_timeout)