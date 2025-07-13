#!/usr/bin/env python3
"""
Скрипт для тестирования логирования API chain-server.
"""

import requests
import time
import json
from pathlib import Path


def test_api_logging():
    """Тестирует различные API endpoint'ы для проверки логирования."""
    base_url = "http://localhost:8000"

    print("🧪 Тестирование логирования API...")

    # 1. Health check
    print("\n1. Тестируем health check...")
    try:
        response = requests.get(f"{base_url}/health")
        print(f"   Статус: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Анализатор изображений: {'✅' if data['image_analyzer_ready'] else '❌'}")
            print(f"   Анализатор нутриентов: {'✅' if data['nutrients_analyzer_ready'] else '❌'}")
    except requests.RequestException as e:
        print(f"   ❌ Ошибка: {e}")

    # 2. Тест анализа нутриентов
    print("\n2. Тестируем анализ нутриентов...")
    try:
        nutrient_data = {
            "dish": "Oatmeal",
            "amount": 250,
            "unit": "грамм"
        }
        response = requests.post(f"{base_url}/analyze-nutrients", json=nutrient_data)
        print(f"   Статус: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if "calories" in data:
                print(f"   Калории: {data.get('calories', 0):.1f} ккал")
                print(f"   Белки: {data.get('protein', 0):.1f} г")
            else:
                print(f"   Ошибка: {data.get('error', 'Неизвестная ошибка')}")
    except requests.RequestException as e:
        print(f"   ❌ Ошибка: {e}")

    # 3. Тест несуществующего endpoint'а
    print("\n3. Тестируем несуществующий endpoint...")
    try:
        response = requests.get(f"{base_url}/nonexistent")
        print(f"   Статус: {response.status_code}")
    except requests.RequestException as e:
        print(f"   ❌ Ошибка: {e}")

    # 4. Тест с неправильными данными
    print("\n4. Тестируем с неправильными данными...")
    try:
        response = requests.post(f"{base_url}/analyze-nutrients", json={})
        print(f"   Статус: {response.status_code}")
        if response.status_code != 200:
            data = response.json()
            print(f"   Ожидаемая ошибка: {data.get('detail', 'Неизвестная ошибка')}")
    except requests.RequestException as e:
        print(f"   ❌ Ошибка: {e}")

    print("\n✅ Тестирование завершено!")
    print("\n📝 Проверьте логи в файле: logs/api_requests.log")
    print("   Команда для просмотра: tail -f logs/api_requests.log")


def check_log_file():
    """Проверяет существование и содержимое лог-файла."""
    log_file = Path("logs/api_requests.log")

    if log_file.exists():
        print(f"\n📋 Последние записи из {log_file}:")
        print("-" * 80)
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # Показываем последние 10 строк
            for line in lines[-10:]:
                print(f"   {line.strip()}")
        print("-" * 80)
    else:
        print(f"\n❌ Лог-файл {log_file} не найден")


if __name__ == "__main__":
    # Небольшая задержка чтобы сервер успел запуститься
    print("⏱️  Ожидание 2 секунды для запуска сервера...")
    time.sleep(2)

    test_api_logging()
    check_log_file()