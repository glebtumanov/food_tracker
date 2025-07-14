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

        КРИТИЧЕСКИ ВАЖНО - различай сырые и приготовленные продукты:
        - Овсянка в тарелке = "Овсяная каша" / "Oatmeal porridge" или "Cooked oatmeal"
        - Сухая овсянка = "Овсяные хлопья" / "Dry oats" или "Rolled oats"
        - Вареное яйцо = "Вареное яйцо" / "Boiled egg" или "Hard-boiled egg"
        - Жареное яйцо = "Жареное яйцо" / "Fried egg"
        - Рис в тарелке = "Вареный рис" / "Cooked rice"
        - Макароны в тарелке = "Отварные макароны" / "Cooked pasta"

        Правила анализа:
        - Будь максимально точен в определении СОСТОЯНИЯ блюд (сырое/приготовленное)
        - Для unit_type используй только: "штук", "грамм", "чашка", "кусок", "ломтик"

        ПРАВИЛА ВЫБОРА ЕДИНИЦ ИЗМЕРЕНИЯ (по приоритету):

        1. ПРИОРИТЕТ: Используй "грамм" для:
          * Всех нарезанных продуктов (картофель кусочками, нарезанное мясо, овощи дольками)
          * Составных блюд и гарниров (каши, салаты, пюре, жареные овощи)
          * Порезанных на кусочки продуктов (даже если это части одного предмета)
          * Любых блюд без четких индивидуальных границ
          * Мясных и рыбных блюд в виде кусочков или филе

        2. Используй "штук" ТОЛЬКО для:
          * Целых, неразделенных предметов (целое яйцо, целое яблоко, целая булочка)
          * Отдельных изделий (печенье, конфета, орех в скорлупе)
          * ВАЖНО: если видишь несколько кусочков одного продукта - это "грамм", не "штук"!

        3. Используй "кусок" только для:
          * Больших порционных кусков (кусок торта, кусок сыра, отбивная)
          * НЕ используй для мелких нарезанных кусочков!

        4. Используй "ломтик" для:
          * Тонко нарезанных продуктов (хлеб, колбаса, сыр ломтиками)

        5. Используй "чашка" для:
          * Напитков и жидких блюд в чашках/стаканах

        ПРИМЕРЫ ПРАВИЛЬНОГО ОПРЕДЕЛЕНИЯ:
        - 6 кусочков жареной картошки → "200 грамм" (не "6 штук"!)
        - 5 кусочков нарезанной курицы → "150 грамм" (не "5 кусков"!)
        - 1 целое вареное яйцо → "1 штук"
        - Порция риса → "180 грамм"
        - Салат из овощей → "120 грамм"
        - 1 целая булочка → "1 штук"
        - Кусок торта → "1 кусок"

        - Количество указывай разумно, учитывая стандартные порции
        - Если на изображении несколько одинаковых блюд, указывай общее количество
        - В английском названии ОБЯЗАТЕЛЬНО указывай способ приготовления
        - Указывай уверенность в анализе (0-1)

        Примеры правильных названий:
        - "Овсяная каша" → "Cooked oatmeal porridge"
        - "Вареное яйцо" → "Hard-boiled egg"
        - "Жареная картошка" → "Fried potatoes"
        - "Гречневая каша" → "Cooked buckwheat porridge"

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
    unit: str = Field(default="gram", description="Единица измерения (gram/грамм, pieces/штук, cup/чашка, piece/кусок, slice/ломтик)")


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
        3. КРИТИЧЕСКИ ВАЖНО: выбирай продукт правильного состояния (сырой/приготовленный)
        4. Возьми значения питательных веществ из поля "nutrients" (они даны на 100г)
        5. ОБЯЗАТЕЛЬНО пересчитай на указанное количество по формуле:
           Итоговое_значение = (Значение_на_100г * Указанное_количество_в_граммах) / 100

        Правила выбора продукта:
        - Для "Cooked oatmeal" ищи "oatmeal, cooked" или "porridge", НЕ "oats, dry"
        - Для "Hard-boiled egg" ищи "egg, boiled" или "egg, hard-boiled"
        - Для "Cooked rice" ищи "rice, cooked", НЕ "rice, dry"
        - Для "Cooked pasta" ищи "pasta, cooked", НЕ "pasta, dry"

        Правила расчета единиц:
        - ВСЕ данные из API даны на 100г - это критически важно!
        - ПРИОРИТЕТ: Используй данные из раздела "measures" для точного веса единиц

        Алгоритм определения веса:
        1. Сначала ищи в разделе "measures" подходящую единицу измерения:
           * Для "pieces"/"штук" → "Whole", "Serving" или "Unit"
           * Для "cup"/"чашка" → "Cup"
           * Для "slice"/"ломтик" → "Slice"
           * Для "piece"/"кусок" → "Piece" или "Serving"
           * Для "gram"/"грамм" → "Gram" (обычно 1.0)

                 2. Если нашел в measures - используй точный вес из поля "weight"
         3. Учитывай qualified варианты (например, "large", "medium", "small", "chopped")
         4. При выборе из нескольких вариантов:
            - Предпочитай стандартные размеры без qualified (обычные размеры)
            - Если есть qualified, выбирай "medium" или без спецификации
            - Логируй в ответе какая единица из measures была использована

        Примеры работы с measures:
        - "Whole": 40.0 → 1 штука яйца = 40г
        - "Whole" + "large": 50.0 → 1 крупное яйцо = 50г
        - "Cup": 136.0 → 1 чашка = 136г
        - "Serving": 50.0 → 1 порция = 50г

        Fallback значения (если нет в measures):
        - Для "pieces": яйцо=50г, яблоко=180г, банан=120г, остальное=100г
        - Для "piece": 1 кусок = 100г
        - Для "slice": 1 ломтик = 30г (хлеб/сыр), 50г (мясо)
        - Для "cup": 1 чашка = 200г
        - Для "gram": используй указанное количество напрямую

        - Округляй результаты до 1 знака после запятой
        - В поле dish_name укажи название блюда с количеством, как указано в запросе

        Примеры расчета с использованием measures:

        Пример 1: 1 яйцо (1 pieces)
        - Ищем в measures: "Whole": {"weight": 40.0} или "Whole" + "large": {"weight": 50.0}
        - Используем стандартное: 1 яйцо = 1 * 40г = 40г
        - Если яйцо содержит 155 ккал на 100г, то: (155 * 40) / 100 = 62.0 ккал

        Пример 2: 1 чашка овсянки (1 cup)
        - Ищем в measures: "Cup": {"weight": 136.0}
        - 1 чашка = 1 * 136г = 136г
        - Если овсянка содержит 68 ккал на 100г, то: (68 * 136) / 100 = 92.5 ккал

        Пример 3: 250 грамм (250 gram)
        - Прямой расчет: 250г
        - Если продукт содержит 68 ккал на 100г, то: (68 * 250) / 100 = 170.0 ккал

        Возвращай результат строго в указанном JSON формате.
        """

        self._build_chain()

    def _optimize_search_term(self, dish_name: str) -> str:
        """Оптимизирует поисковый термин для лучшего поиска в Edamam API."""
        # Приводим к нижнему регистру для сравнения
        dish_lower = dish_name.lower()

        # Словарь для улучшения поисковых запросов
        search_optimizations = {
            # Приготовленные блюда
            "cooked oatmeal": "oatmeal cooked",
            "oatmeal porridge": "oatmeal cooked",
            "cooked oatmeal porridge": "oatmeal cooked",
            "hard-boiled egg": "egg boiled",
            "boiled egg": "egg boiled",
            "soft-boiled egg": "egg boiled",
            "fried egg": "egg fried",
            "scrambled eggs": "egg scrambled",
            "cooked rice": "rice cooked",
            "cooked pasta": "pasta cooked",
            "cooked buckwheat": "buckwheat cooked",
            "cooked quinoa": "quinoa cooked",

            # Исправления для популярных продуктов
            "buckwheat porridge": "buckwheat cooked",
            "rice porridge": "rice cooked",
            "millet porridge": "millet cooked",
            "pearl barley porridge": "barley cooked",

            # Овощи
            "fried potatoes": "potato fried",
            "mashed potatoes": "potato mashed",
            "boiled potatoes": "potato boiled",
            "baked potato": "potato baked",

            # Мясо и рыба
            "grilled chicken": "chicken grilled",
            "fried chicken": "chicken fried",
            "baked fish": "fish baked",
            "grilled fish": "fish grilled",

            # Молочные продукты
            "greek yogurt": "yogurt greek",
            "cottage cheese": "cheese cottage",
        }

        # Проверяем, есть ли оптимизация для данного блюда
        for dish_key, optimized_term in search_optimizations.items():
            if dish_key in dish_lower:
                return optimized_term

        # Если точного совпадения нет, применяем общие правила
        if "cooked" in dish_lower or "porridge" in dish_lower:
            # Убираем слова "cooked" и "porridge" и добавляем "cooked" в конец
            base_dish = dish_lower.replace("cooked ", "").replace(" porridge", "").replace("porridge", "")
            return f"{base_dish.strip()} cooked"

        if "boiled" in dish_lower or "hard-boiled" in dish_lower:
            # Для вареных продуктов
            base_dish = dish_lower.replace("hard-boiled ", "").replace("boiled ", "").replace(" boiled", "")
            return f"{base_dish.strip()} boiled"

        if "fried" in dish_lower:
            # Для жареных продуктов
            base_dish = dish_lower.replace("fried ", "").replace(" fried", "")
            return f"{base_dish.strip()} fried"

        # Если никаких правил не применилось, возвращаем оригинальное название
        return dish_name

    def _search_single_dish(self, dish_name: str) -> Dict[str, Any]:
        """Поиск одного блюда в Edamam API."""
        # Улучшаем поисковый запрос для лучшего поиска приготовленных блюд
        search_term = self._optimize_search_term(dish_name)

        # Логируем оптимизацию поиска если термин изменился
        if search_term.lower() != dish_name.lower():
            print(f"🔍 Поиск оптимизирован: '{dish_name}' → '{search_term}'")

        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "ingr": search_term,
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

            # Логируем количество найденных результатов
            parsed_count = len(data.get("parsed", []))
            hints_count = len(data.get("hints", []))
            print(f"📊 Edamam поиск '{search_term}': parsed={parsed_count}, hints={hints_count}")

            return {
                "dish_name": dish_name,
                "search_term": search_term,
                "success": True,
                "data": data
            }

        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка поиска в Edamam для '{search_term}': {str(e)}")
            return {
                "dish_name": dish_name,
                "search_term": search_term,
                "success": False,
                "error": str(e),
                "data": None
            }

    def _analyze_nutrients_with_llm(self, edamam_data: Dict[str, Any], dish: str, amount: float, unit: str, search_term: str = None) -> Dict[str, Any]:
        """Анализ питательных веществ через OpenAI на основе данных Edamam."""
        try:
            # Формируем полное название блюда с количеством
            dish_with_amount = f"{dish} ({amount} {unit})"

            # Формируем запрос для LLM
            user_query = f"""
            Блюдо: {dish}
            Количество: {amount} {unit}
            Поисковый термин в Edamam: {search_term or dish}

            Данные от Edamam API:
            {json.dumps(edamam_data, ensure_ascii=False, indent=2)}

            Проанализируй и рассчитай питательную ценность для указанного количества блюда.
            ОБЯЗАТЕЛЬНО выбери продукт правильного состояния (приготовленный/сырой) основываясь на поисковом термине.
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
            unit = inputs.get("unit", "gram")

            # Логируем параметры запроса
            print(f"🥗 Анализ нутриентов: блюдо='{dish}', количество={amount}, единица='{unit}'")

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
                edamam_result["data"], dish, amount, unit, edamam_result.get("search_term")
            )

            # Возвращаем только nutrients
            if nutrients_result["success"]:
                return nutrients_result["nutrients"]
            else:
                return {
                    "error": edamam_result.get("error") or nutrients_result.get("error")
                }

        self.chain = RunnableLambda(analyze_dish_nutrients)

    def analyze_dish_nutrients(self, dish: str, amount: float = 100, unit: str = "gram") -> Dict[str, Any]:
        """
        Анализ питательных веществ блюда.

        Args:
            dish: Название блюда
            amount: Количество блюда
            unit: Единица измерения (gram, pieces, cup, piece, slice)

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