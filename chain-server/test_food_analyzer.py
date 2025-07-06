"""
Тестирование цепочки для анализа изображений еды.

Для запуска тестов нужно:
1. Установить зависимости: pip install langchain-openai pydantic
2. Установить переменную окружения OPENAI_API_KEY
3. Подготовить тестовые изображения еды
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any

# Добавляем путь к модулю
sys.path.append(str(Path(__file__).parent))

from food_analyzer import create_food_analyzer, FoodImageAnalyzer


def test_single_image(analyzer: FoodImageAnalyzer, image_path: str) -> None:
    """
    Тестирует анализ одного изображения.

    Args:
        analyzer: Экземпляр анализатора
        image_path: Путь к изображению
    """
    print(f"\n=== Тестирование изображения: {image_path} ===")

    if not os.path.exists(image_path):
        print(f"❌ Файл не найден: {image_path}")
        return

    print("🔍 Начинаю анализ...")

    try:
        result = analyzer.analyze_image(image_path)

        if "error" in result:
            print(f"❌ Ошибка анализа: {result['error']}")
            return

        print("✅ Анализ завершен успешно!")
        print(f"📊 Результат анализа:")
        print(f"   Уверенность: {result.get('confidence', 0):.2f}")
        print(f"   Общая масса: {result.get('total_weight', 0)} г")
        print(f"   Количество блюд: {len(result.get('dishes', []))}")

        print("\n🍽️  Найденные блюда:")
        for i, dish in enumerate(result.get('dishes', []), 1):
            print(f"   {i}. {dish.get('name', 'Неизвестно')}")
            print(f"      Масса: {dish.get('weight_grams', 0)} г")
            print(f"      Описание: {dish.get('description', 'Нет описания')}")
            print()

        # Красивый вывод JSON
        print("📋 Полный результат (JSON):")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")


def test_batch_analysis(analyzer: FoodImageAnalyzer, image_paths: list[str]) -> None:
    """
    Тестирует анализ нескольких изображений.

    Args:
        analyzer: Экземпляр анализатора
        image_paths: Список путей к изображениям
    """
    print(f"\n=== Пакетный анализ {len(image_paths)} изображений ===")

    existing_paths = [path for path in image_paths if os.path.exists(path)]

    if not existing_paths:
        print("❌ Не найдено ни одного изображения для анализа")
        return

    print(f"📁 Найдено {len(existing_paths)} изображений")

    results = analyzer.analyze_batch(existing_paths)

    total_dishes = 0
    total_weight = 0

    for i, (path, result) in enumerate(zip(existing_paths, results), 1):
        print(f"\n📸 Изображение {i}: {Path(path).name}")

        if "error" in result:
            print(f"   ❌ Ошибка: {result['error']}")
            continue

        dishes_count = len(result.get('dishes', []))
        weight = result.get('total_weight', 0)

        print(f"   ✅ Блюд: {dishes_count}, Масса: {weight} г")
        print(f"   🎯 Уверенность: {result.get('confidence', 0):.2f}")

        total_dishes += dishes_count
        total_weight += weight

    print(f"\n📊 Общая статистика:")
    print(f"   Всего блюд: {total_dishes}")
    print(f"   Общая масса: {total_weight} г")


def create_test_images_list() -> list[str]:
    """
    Создает список тестовых изображений.

    Returns:
        Список путей к тестовым изображениям
    """
    # Возможные пути к тестовым изображениям
    test_paths = [
        "test_images/pizza.jpg",
        "test_images/salad.png",
        "test_images/dinner.jpeg",
        "../pyapp-web/uploads/test_food.jpg",
        "food_sample.jpg",
        "meal.png"
    ]

    return test_paths


def main():
    """Основная функция для запуска тестов."""
    print("🍔 Тестирование анализатора изображений еды")
    print("=" * 50)

    # Проверяем наличие API ключа
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Не найден OPENAI_API_KEY в переменных окружения")
        print("   Установите ключ: export OPENAI_API_KEY='your-api-key'")
        return

    print("✅ API ключ найден")

    # Создаем анализатор
    try:
        print("🔧 Создаю анализатор...")
        analyzer = create_food_analyzer()
        print("✅ Анализатор создан успешно")
    except Exception as e:
        print(f"❌ Ошибка создания анализатора: {e}")
        return

    # Получаем список тестовых изображений
    test_images = create_test_images_list()

    # Проверяем, какие изображения доступны
    available_images = [img for img in test_images if os.path.exists(img)]

    if not available_images:
        print("\n⚠️  Тестовые изображения не найдены")
        print("   Создайте папку 'test_images' и добавьте файлы:")
        for img in test_images:
            print(f"   - {img}")
        print("\n📝 Или укажите путь к изображению еды:")

        # Предлагаем пользователю ввести путь
        user_image = input("   Путь к изображению: ").strip()
        if user_image and os.path.exists(user_image):
            available_images = [user_image]
        else:
            print("❌ Файл не найден или не указан")
            return

    print(f"\n📋 Найдено {len(available_images)} изображений для тестирования")

    # Тестируем каждое изображение отдельно
    for image_path in available_images:
        test_single_image(analyzer, image_path)

    # Пакетный анализ, если изображений больше одного
    if len(available_images) > 1:
        test_batch_analysis(analyzer, available_images)

    print("\n🎉 Тестирование завершено!")


if __name__ == "__main__":
    main()