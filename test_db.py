#!/usr/bin/env python3

from sqlalchemy import create_engine, text
import os
import sqlite3

def test_direct_sqlite():
    """Тест прямого подключения через sqlite3"""
    print("=== Тест прямого подключения sqlite3 ===")
    try:
        conn = sqlite3.connect('instance/app.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"✅ Прямое подключение успешно!")
        print(f"Найденные таблицы: {[table[0] for table in tables]}")
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Ошибка прямого подключения: {e}")
        return False

def test_sqlalchemy():
    """Тест подключения через SQLAlchemy"""
    print("\n=== Тест подключения SQLAlchemy ===")
    database_url = "sqlite:///instance/app.db"
    print(f"URL базы данных: {database_url}")
    print(f"Рабочий каталог: {os.getcwd()}")

    try:
        engine = create_engine(database_url)
        connection = engine.connect()

        # Проверяем список таблиц
        result = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
        tables = [row[0] for row in result]
        print(f"✅ SQLAlchemy подключение успешно!")
        print(f"Найденные таблицы: {tables}")

        connection.close()
        return True
    except Exception as e:
        print(f"❌ Ошибка SQLAlchemy подключения: {e}")
        return False

def check_file_permissions():
    """Проверка файла и прав доступа"""
    print("\n=== Проверка файла и прав доступа ===")

    db_path = "instance/app.db"
    if os.path.exists(db_path):
        stat = os.stat(db_path)
        print(f"✅ Файл существует: {db_path}")
        print(f"Размер файла: {stat.st_size} байт")
        print(f"Права доступа: {oct(stat.st_mode)[-3:]}")

        # Проверяем доступ на чтение/запись
        readable = os.access(db_path, os.R_OK)
        writable = os.access(db_path, os.W_OK)
        print(f"Доступ на чтение: {'✅' if readable else '❌'}")
        print(f"Доступ на запись: {'✅' if writable else '❌'}")

        return readable and writable
    else:
        print(f"❌ Файл не существует: {db_path}")
        return False

if __name__ == "__main__":
    print("Тестирование подключения к базе данных...\n")

    file_ok = check_file_permissions()
    sqlite_ok = test_direct_sqlite()
    sqlalchemy_ok = test_sqlalchemy()

    print(f"\n=== Сводка результатов ===")
    print(f"Файл и права доступа: {'✅' if file_ok else '❌'}")
    print(f"Прямое подключение sqlite3: {'✅' if sqlite_ok else '❌'}")
    print(f"Подключение SQLAlchemy: {'✅' if sqlalchemy_ok else '❌'}")

    if all([file_ok, sqlite_ok, sqlalchemy_ok]):
        print("\n🎉 Все тесты прошли успешно! База данных готова к использованию.")
    else:
        print("\n⚠️ Есть проблемы с базой данных.")