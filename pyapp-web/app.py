from __future__ import annotations

import os
import uuid
import yaml
import json
import base64
import requests
from pathlib import Path
from typing import Final, Set, Dict, Any

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for, session
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from email.message import EmailMessage
import smtplib
import ssl
from markupsafe import Markup

from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import inspect, text as sa_text, select

# ----------------------------------------------------------------------------
# Конфигурация
# ----------------------------------------------------------------------------

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Загружает конфигурацию из YAML файла."""
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config

# Загружаем конфигурацию
config = load_config()

# Константы из конфигурации
UPLOAD_FOLDER: Final[str] = config["upload"]["folder"]
ALLOWED_EXTENSIONS: Final[Set[str]] = set(config["upload"]["allowed_extensions"])
MAX_CONTENT_LENGTH: Final[int] = config["upload"]["max_content_length_mb"] * 1024 * 1024

# ----------------------------------------------------------------------------
# Расширения
# ----------------------------------------------------------------------------

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "login"

# ----------------------------------------------------------------------------
# Модели
# ----------------------------------------------------------------------------

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

class Upload(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(260), nullable=False)
    # Результат анализа в формате markdown
    ingredients_md = db.Column(db.Text, default="", nullable=False)
    # Результат анализа в формате JSON от модели
    ingredients_json = db.Column(db.Text, nullable=True)
    # Контрольная сумма файла — пригодится для поиска дубликатов
    crc = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    # Результат анализа нутриентов в формате JSON
    nutrients_json = db.Column(db.Text, nullable=True)

@login_manager.user_loader  # type: ignore
def load_user(user_id: str):
    return db.session.get(User, int(user_id))

# ----------------------------------------------------------------------------
# Почтовая логика
# ----------------------------------------------------------------------------

def _send_confirmation_email(app: Flask, user: User) -> None:
    """Формирует и отправляет ссылку подтверждения на email пользователя."""

    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    token = serializer.dumps(user.email, salt="email-confirm-salt")
    confirm_url = url_for("confirm_email", token=token, _external=True)

    # В демо-режиме просто выводим ссылку в лог.
    app.logger.info("Ссылка для подтверждения %s: %s", user.email, confirm_url)

    # Пример для боевой отправки через SMTP (требует настроек MAIL_*). Закомментировано.
    """
    msg = EmailMessage()
    msg["Subject"] = "Подтвердите регистрацию"
    msg["From"] = app.config["MAIL_DEFAULT_SENDER"]
    msg["To"] = user.email
    msg.set_content(f"Для подтверждения перейдите по ссылке: {confirm_url}")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(app.config["MAIL_SERVER"], app.config["MAIL_PORT"], context=context) as smtp:
        smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
        smtp.send_message(msg)
    """

# -------------------- Сброс пароля --------------------

def _send_reset_email(app: Flask, user: User) -> None:
    """Формирует и отправляет ссылку для сброса пароля (логируется)."""

    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    token = serializer.dumps(user.email, salt="password-reset-salt")
    reset_url = url_for("reset_password", token=token, _external=True)

    # Пока вместо реальной отправки письма выводим ссылку в лог
    app.logger.info("Ссылка для сброса пароля %s: %s", user.email, reset_url)

    # Шаблон для полноценной отправки (закомментировано)
    """
    msg = EmailMessage()
    msg["Subject"] = "Сброс пароля"
    msg["From"] = app.config["MAIL_DEFAULT_SENDER"]
    msg["To"] = user.email
    msg.set_content(f"Перейдите по ссылке для сброса пароля: {reset_url}")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(app.config["MAIL_SERVER"], app.config["MAIL_PORT"], context=context) as smtp:
        smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
        smtp.send_message(msg)
    """

# ----------------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    """Проверяет расширение файла."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def analyze_image_with_chain_server(image_path: str) -> Dict[str, Any]:
    """Анализирует изображение с помощью chain-сервера."""
    chain_config = config.get("chain_server", {})

    chain_url = chain_config.get("url", "http://localhost:8000")
    analyze_endpoint = chain_config.get("analyze_endpoint", "/analyze")
    timeout = chain_config.get("timeout", 30)

    full_url = f"{chain_url}{analyze_endpoint}"

    # Проверяем, существует ли файл
    if not os.path.exists(image_path):
        return {
            "error": f"Файл изображения не найден: {image_path}",
            "dishes": [],
            "confidence": 0.0
        }

    # Кодируем изображение в base64
    with open(image_path, "rb") as image_file:
        image_base64 = base64.b64encode(image_file.read()).decode('utf-8')

    # Подготавливаем запрос
    payload = {
        "image_base64": image_base64,
        "filename": Path(image_path).name
    }

    # Отправляем запрос к chain-серверу
    response = requests.post(
        full_url,
        json=payload,
        timeout=timeout,
        headers={"Content-Type": "application/json"}
    )

    if response.status_code == 200:
        result = response.json()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        # Убираем поле error если оно None (успешный анализ)
        if result.get("error") is None:
            result.pop("error", None)
        return result
    else:
        error_msg = f"Ошибка chain-сервера: {response.status_code}"
        if response.headers.get("content-type") == "application/json":
            error_data = response.json()
            if "detail" in error_data:
                error_msg = error_data["detail"]

        return {
            "error": error_msg,
            "dishes": [],
            "confidence": 0.0
        }


# ----------------------------------------------------------------------------
# Фильтры Jinja
# ----------------------------------------------------------------------------

RUS_WEEKDAYS: Final[list[str]] = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]


def _ru_weekday(value: datetime) -> str:  # pragma: no cover
    """Возвращает название дня недели на русском."""
    return RUS_WEEKDAYS[value.weekday()]

def _format_datetime_ru(value: datetime) -> Markup:  # pragma: no cover
    """Форматирует дату/время как '25.06.2025 (17:55)<br>Среда'."""
    return Markup(f"{value.strftime('%d.%m.%Y (%H:%M)')}<br>{_ru_weekday(value)}")


def _extract_dishes_only(ingredients_md_text: str) -> str:  # pragma: no cover
    """Извлекает только список блюд из полного результата анализа."""
    if not ingredients_md_text:
        return ""

    lines = ingredients_md_text.split('\n')
    dishes_section = []
    found_dishes = False

    for line in lines:
        # Ищем начало списка блюд
        if "Обнаруженные блюда:" in line:
            found_dishes = True
            continue

        # Если нашли секцию блюд, собираем все строки до конца
        if found_dishes:
            # Пропускаем пустые строки в начале секции блюд
            if not dishes_section and not line.strip():
                continue
            dishes_section.append(line)

    # Если секция блюд найдена, возвращаем её
    if dishes_section:
        return '\n'.join(dishes_section).strip()

    # Если секция не найдена, пробуем найти строки, начинающиеся с цифры
    dish_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and (stripped[0].isdigit() or stripped.startswith('_')):
            dish_lines.append(line)

    return '\n'.join(dish_lines) if dish_lines else ingredients_md_text

# ----------------------------------------------------------------------------
# Фабрика приложения
# ----------------------------------------------------------------------------

def _get_or_create_secret_key() -> str:
    """Возвращает постоянный SECRET_KEY, сохраняя его в instance/secret_key.txt.

    Это гарантирует работоспособность «remember me» между перезапусками
    приложения: если ключ меняется, подпись cookies становится недействительной.
    """

    instance_dir = Path(__file__).resolve().parent / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    key_path = instance_dir / "secret_key.txt"

    if key_path.exists():
        return key_path.read_text().strip()

    new_key = os.urandom(24).hex()
    key_path.write_text(new_key)
    return new_key

def create_app() -> Flask:
    app = Flask(__name__)

    # Настройки из конфигурации
    database_config = config["database"]
    upload_config = config["upload"]
    security_config = config["security"]
    mail_config = config["mail"]

    app.config.update(
        UPLOAD_FOLDER=upload_config["folder"],
        MAX_CONTENT_LENGTH=upload_config["max_content_length_mb"] * 1024 * 1024,
        # Безопасность и БД
        SECRET_KEY=os.getenv("SECRET_KEY", security_config.get("secret_key") or _get_or_create_secret_key()),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", database_config["url"]),
        SQLALCHEMY_TRACK_MODIFICATIONS=database_config["track_modifications"],
        # Настройки cookie «Запомнить меня»
        REMEMBER_COOKIE_DURATION=timedelta(days=security_config["remember_cookie_duration_days"]),
        # Настройки почты (можно переопределить через переменные среды)
        MAIL_SERVER=os.getenv("MAIL_SERVER", mail_config["server"]),
        MAIL_PORT=int(os.getenv("MAIL_PORT", mail_config["port"])),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME", mail_config["username"]),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", mail_config["password"]),
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER", mail_config["default_sender"]),
        MAIL_USE_TLS=mail_config.get("use_tls", True),
        MAIL_USE_SSL=mail_config.get("use_ssl", True),
    )

    # Инициализируем расширения
    db.init_app(app)
    login_manager.init_app(app)

    # Регистрируем фильтры
    app.add_template_filter(_ru_weekday, name="ru_weekday")
    app.add_template_filter(_format_datetime_ru, name="ru_dt")
    app.add_template_filter(_extract_dishes_only, name="dishes_only")

    # Убедимся, что каталог для загрузок существует
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    # Создаём таблицы при первом запуске
    with app.app_context():
        db.create_all()

        # --- Простейшая миграция: добавляем недостающие столбцы Upload ---
        engine = db.engine
        inspector = inspect(engine)

        upload_cols = {col["name"] for col in inspector.get_columns("upload")}
        alter_stmts: list[str] = []

        # Миграция: добавляем новые поля ingredients_md и ingredients_json
        if "ingredients_md" not in upload_cols:
            alter_stmts.append("ALTER TABLE upload ADD COLUMN ingredients_md TEXT NOT NULL DEFAULT '';")
            # Если есть старое поле ingredients, копируем данные
            if "ingredients" in upload_cols:
                alter_stmts.append("UPDATE upload SET ingredients_md = ingredients;")

        if "ingredients_json" not in upload_cols:
            alter_stmts.append("ALTER TABLE upload ADD COLUMN ingredients_json TEXT;")

        if "crc" not in upload_cols:
            alter_stmts.append("ALTER TABLE upload ADD COLUMN crc VARCHAR(16) NOT NULL DEFAULT '';")

        if "nutrients_json" not in upload_cols:
            alter_stmts.append("ALTER TABLE upload ADD COLUMN nutrients_json TEXT;")

        if alter_stmts:
            with engine.begin() as conn:
                for stmt in alter_stmts:
                    conn.execute(sa_text(stmt))

    # ---------------------------------------------------------------------
    # Роуты
    # ---------------------------------------------------------------------

    @app.get("/")
    @login_required
    def index():  # type: ignore
        """Главная страница с опциональным предпросмотром ранее загруженного изображения."""
        # Приоритет: параметр строки запроса → сохранённый в сессии URL
        preload_url = request.args.get("image") or session.get("last_image", "")
        return render_template("index.html", preload_url=preload_url)

    @app.post("/upload")
    @login_required
    def upload():  # type: ignore
        """Приём файла изображения через AJAX."""
        if not current_user.is_confirmed:
            return jsonify({"error": "Подтвердите email"}), 403

        if "file" not in request.files:
            return jsonify({"error": "Файл не найден"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Имя файла отсутствует"}), 400

        if not allowed_file(file.filename):
            return jsonify({"error": "Недопустимый формат"}), 400

        # Читаем содержимое заранее, чтобы вычислить CRC32. Файл небольшого размера (≤16 МБ).
        import zlib

        file_bytes = file.read()
        crc_value = f"{zlib.crc32(file_bytes) & 0xFFFFFFFF:08x}"
        # После чтения перематываем указатель, иначе save() запишет пустой файл.
        file.seek(0)

        filename = secure_filename(file.filename)
        # Генерируем уникальное имя, чтобы избежать коллизий
        ext = filename.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
        file.save(save_path)

        # Привязываем файл к текущему пользователю
        upload_record = Upload(
            filename=unique_name,
            user_id=current_user.id,
            crc=crc_value,
            ingredients_md="",  # будет заполнено после анализа
            ingredients_json=None,  # будет заполнено после анализа
        )
        db.session.add(upload_record)
        db.session.commit()

        file_url = url_for("uploaded_file", filename=unique_name, _external=False)
        # Запоминаем в сессии, чтобы отображать после переходов по сайту
        session["last_image"] = file_url
        return jsonify({"url": file_url, "upload_id": upload_record.id})

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str):  # type: ignore
        """Отдаёт сохранённое изображение."""
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.post("/save_analysis")
    @login_required
    def save_analysis():  # type: ignore
        """Сохраняет результат анализа изображения."""
        if not current_user.is_confirmed:
            return jsonify({"error": "Подтвердите email"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Нет данных"}), 400

        upload_id = data.get("upload_id")
        ingredients_md = data.get("ingredients_md", "")
        ingredients_json = data.get("ingredients_json")

        if not upload_id:
            return jsonify({"error": "ID загрузки не указан"}), 400

        upload_record = db.get_or_404(Upload, upload_id)
        if upload_record.user_id != current_user.id:
            return jsonify({"error": "Доступ запрещен"}), 403

        upload_record.ingredients_md = ingredients_md
        if ingredients_json:
            upload_record.ingredients_json = json.dumps(ingredients_json, indent=2, ensure_ascii=False)
        # При обновлении ingredients_json очищаем nutrients_json
        upload_record.nutrients_json = None
        db.session.commit()

        return jsonify({"success": True})

    @app.get("/get_analysis/<path:filename>")
    @login_required
    def get_analysis(filename: str):  # type: ignore
        """Получает сохраненный анализ по имени файла."""
        upload_record = db.first_or_404(
            select(Upload).filter_by(
                filename=filename,
                user_id=current_user.id
            )
        )

        # Декодируем JSON если он есть
        ingredients_json = None
        if upload_record.ingredients_json:
            ingredients_json = json.loads(upload_record.ingredients_json)

        nutrients_json = None
        if upload_record.nutrients_json:
            nutrients_json = json.loads(upload_record.nutrients_json)

        return jsonify({
            "ingredients_md": upload_record.ingredients_md,
            "ingredients_json": ingredients_json,
            "nutrients_json": nutrients_json,
            "upload_id": upload_record.id
        })

    @app.post("/analyze_image")
    @login_required
    def analyze_image():  # type: ignore
        """Анализирует изображение с помощью chain-сервера."""
        if not current_user.is_confirmed:
            return jsonify({"error": "Подтвердите email"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Нет данных"}), 400

        upload_id = data.get("upload_id")
        if not upload_id:
            return jsonify({"error": "ID загрузки не указан"}), 400

        # Находим запись о загрузке
        upload_record = db.get_or_404(Upload, upload_id)
        if upload_record.user_id != current_user.id:
            return jsonify({"error": "Доступ запрещен"}), 403

        # Путь к файлу
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], upload_record.filename)

        if not os.path.exists(image_path):
            return jsonify({"error": "Файл изображения не найден"}), 404

        # Проверяем, работает ли chain-сервер
        chain_config = config.get("chain_server", {})
        chain_url = chain_config.get("url", "http://localhost:8000")

        health_response = requests.get(f"{chain_url}/health", timeout=5)
        if health_response.status_code != 200:
            return jsonify({"error": "Chain-сервер недоступен"}), 503

        health_data = health_response.json()
        if not health_data.get("image_analyzer_ready"):
            return jsonify({"error": "Анализатор не готов"}), 503

        # Анализируем изображение через chain-сервер
        analysis_result = analyze_image_with_chain_server(image_path)

        # Проверяем результат анализа
        error_msg = analysis_result.get("error")
        if error_msg:
            return jsonify({
                "success": False,
                "error": error_msg
            }), 500

        # Формируем текст ингредиентов в markdown формате
        dishes = analysis_result.get("dishes", [])
        confidence = analysis_result.get("confidence", 0)

        ingredients_text = f"**Результат анализа изображения:**\n\n"
        ingredients_text += f"**Уверенность:** {confidence:.1%}\n\n"
        ingredients_text += "**Обнаруженные блюда:**\n\n"

        for i, dish in enumerate(dishes, 1):
            name = dish.get("name", "Неизвестное блюдо")
            name_en = dish.get("name_en", "")
            description = dish.get("description", "")
            description_en = dish.get("description_en", "")
            unit_type = dish.get("unit_type", "")
            amount = dish.get("amount", 0)

            # Основная информация
            ingredients_text += f"{i}. **{name}**"
            if name_en:
                ingredients_text += f" _{name_en}_"

            # Количество и единицы
            if unit_type and amount:
                if unit_type == "штук":
                    ingredients_text += f" — {amount:.0f} {unit_type}"
                else:
                    ingredients_text += f" — {amount} {unit_type}"

            ingredients_text += "\n"

            # Описание
            if description:
                ingredients_text += f"   _{description}_"
                if description_en:
                    ingredients_text += f" _{description_en}_"
                ingredients_text += "\n"

            ingredients_text += "\n"

        # Сохраняем в базу данных
        upload_record.ingredients_md = ingredients_text
        upload_record.ingredients_json = json.dumps(analysis_result, indent=2, ensure_ascii=False)
        # При обновлении ingredients_json очищаем nutrients_json
        upload_record.nutrients_json = None
        db.session.commit()

        return jsonify({
            "success": True,
            "analysis": analysis_result,
            "formatted_text": ingredients_text
        })

    @app.post("/analyze_nutrients")
    @login_required
    def analyze_nutrients():  # type: ignore
        """Анализирует питательную ценность блюда через chain-сервер."""
        if not current_user.is_confirmed:
            return jsonify({"error": "Подтвердите email"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Нет данных"}), 400

        dish = data.get("dish")
        amount = data.get("amount", 100)
        unit = data.get("unit", "грамм")
        upload_id = data.get("upload_id")
        is_first_dish = data.get("is_first_dish", False)

        if not dish:
            return jsonify({"error": "Не указано блюдо"}), 400

        # Если указан upload_id, проверяем права доступа
        upload_record = None
        if upload_id:
            upload_record = db.get_or_404(Upload, upload_id)
            if upload_record.user_id != current_user.id:
                return jsonify({"error": "Доступ запрещен"}), 403

        # Настройки chain-сервера
        chain_config = config.get("chain_server", {})
        chain_url = chain_config.get("url", "http://localhost:8000")
        timeout = chain_config.get("timeout", 30)

        # Проверяем, работает ли chain-сервер
        try:
            health_response = requests.get(f"{chain_url}/health", timeout=5)
            if health_response.status_code != 200:
                return jsonify({"error": "Chain-сервер недоступен"}), 503

            health_data = health_response.json()
            if not health_data.get("nutrients_analyzer_ready"):
                return jsonify({"error": "Анализатор нутриентов не готов"}), 503
        except requests.RequestException:
            return jsonify({"error": "Chain-сервер недоступен"}), 503

        # Отправляем запрос на анализ нутриентов
        try:
            response = requests.post(
                f"{chain_url}/analyze-nutrients",
                json={"dish": dish, "amount": amount, "unit": unit},
                timeout=timeout,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                result = response.json()

                                # Сохраняем результат в базу данных, если указан upload_id
                if upload_record:
                    # Получаем существующие данные нутриентов
                    existing_nutrients = []
                    if not is_first_dish and upload_record.nutrients_json:
                        try:
                            existing_data = json.loads(upload_record.nutrients_json)
                            if isinstance(existing_data, list):
                                existing_nutrients = existing_data
                        except (json.JSONDecodeError, TypeError):
                            existing_nutrients = []

                    # Добавляем новый результат с информацией о блюде
                    result_with_dish = {
                        "dish": dish,
                        "amount": amount,
                        "unit": unit,
                        "nutrients": result,
                        "analyzed_at": datetime.utcnow().isoformat()
                    }

                    # Проверяем, есть ли уже результат для этого блюда
                    updated = False
                    for i, existing in enumerate(existing_nutrients):
                        if existing.get("dish") == dish and existing.get("amount") == amount and existing.get("unit") == unit:
                            existing_nutrients[i] = result_with_dish
                            updated = True
                            break

                    if not updated:
                        existing_nutrients.append(result_with_dish)

                    upload_record.nutrients_json = json.dumps(existing_nutrients, indent=2, ensure_ascii=False)
                    db.session.commit()

                return jsonify(result)
            else:
                error_msg = f"Ошибка chain-сервера: {response.status_code}"
                if response.headers.get("content-type") == "application/json":
                    try:
                        error_data = response.json()
                        if "detail" in error_data:
                            error_msg = error_data["detail"]
                    except:
                        pass

                return jsonify({"error": error_msg}), 500

        except requests.RequestException as e:
            return jsonify({"error": f"Ошибка соединения: {str(e)}"}), 500

    @app.get("/get_nutrients/<int:upload_id>")
    @login_required
    def get_nutrients(upload_id: int):  # type: ignore
        """Получает сохраненные данные о нутриентах по upload_id."""
        upload_record = db.get_or_404(Upload, upload_id)
        if upload_record.user_id != current_user.id:
            return jsonify({"error": "Доступ запрещен"}), 403

        nutrients_json = None
        if upload_record.nutrients_json:
            nutrients_json = json.loads(upload_record.nutrients_json)

        return jsonify({
            "nutrients_json": nutrients_json,
            "upload_id": upload_record.id
        })

    # Обработка 413 — превышен размер файла
    @app.errorhandler(413)
    def file_too_large(_: Exception):  # type: ignore
        return jsonify({"error": "Файл слишком большой"}), 413

    # ---------------------- Аутентификация ------------------------------

    @app.route("/register", methods=["GET", "POST"])
    def register():  # type: ignore
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not email or not password:
                return render_template("register.html", error="Заполните все поля")

            if db.session.execute(select(User).filter_by(email=email)).scalar_one_or_none():
                return render_template("register.html", error="Email уже зарегистрирован")

            user = User(email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            _send_confirmation_email(app, user)
            return render_template("register.html", success="Проверьте почту для подтверждения")

        return render_template("register.html")

    @app.route("/confirm/<token>")
    def confirm_email(token: str):  # type: ignore
        serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
        try:
            email = serializer.loads(token, salt="email-confirm-salt", max_age=3600)
        except (BadSignature, SignatureExpired):
            return "Ссылка недействительна или устарела", 400

        user = db.first_or_404(select(User).filter_by(email=email))
        if not user.is_confirmed:
            user.is_confirmed = True
            db.session.commit()
        return render_template("confirm.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():  # type: ignore
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        # Если email передан query-string'ом (после logout), используем его, чтобы
        # показать короткую форму с одним полем пароля.
        prefilled_email = request.args.get("email", "")

        if request.method == "POST":
            # email может прийти как скрытое поле, поэтому берём из формы
            email = request.form.get("email", "").lower()
            password = request.form.get("password", "")
            user = db.session.execute(select(User).filter_by(email=email)).scalar_one_or_none()

            if user and user.check_password(password):
                if not user.is_confirmed:
                    return render_template(
                        "login.html",
                        error="Подтвердите email перед входом",
                        prefilled_email=prefilled_email or email,
                    )

                # Запоминаем пользователя всегда на 7 дней
                login_user(user, remember=True)

                # Сохраняем в сессии последний загруженный файл (если есть)
                last_upload = db.session.execute(
                    select(Upload)
                    .filter_by(user_id=user.id)
                    .order_by(Upload.created_at.desc())
                ).scalar_one_or_none()
                if last_upload:
                    session["last_image"] = url_for(
                        "uploaded_file", filename=last_upload.filename, _external=False
                    )
                else:
                    session.pop("last_image", None)

                return redirect(url_for("index"))

            return render_template(
                "login.html",
                error="Неверные учётные данные",
                prefilled_email=prefilled_email or email,
            )

        return render_template("login.html", prefilled_email=prefilled_email)

    @app.get("/logout")
    @login_required
    def logout():  # type: ignore
        logout_user()
        # Удаляем только пользовательские данные, не очищая весь объект session,
        # иначе Flask-Login не сможет выставить cookie с очисткой «remember me».
        session.pop("last_image", None)
        return redirect(url_for("login"))

    # ---------------------- История загрузок -----------------------------

    @app.get("/history")
    @login_required
    def history():  # type: ignore
        """Таблица с ранее загруженными изображениями пользователя."""
        uploads = db.session.execute(
            select(Upload)
            .filter_by(user_id=current_user.id)
            .order_by(Upload.created_at.desc())
        ).scalars().all()
        return render_template("history.html", uploads=uploads)

    @app.get("/nutrition_stats")
    @login_required
    def nutrition_stats():  # type: ignore
        """Статистика потребления нутриентов по дням за последний месяц."""
        # Получаем записи за последний месяц с анализом нутриентов
        month_ago = datetime.utcnow() - timedelta(days=30)
        uploads = db.session.execute(
            select(Upload)
            .filter(
                Upload.user_id == current_user.id,
                Upload.created_at >= month_ago,
                Upload.nutrients_json.isnot(None),
                Upload.nutrients_json != ""
            )
            .order_by(Upload.created_at.desc())
        ).scalars().all()

        # Группируем по дням и суммируем нутриенты
        daily_stats = {}

        for upload in uploads:
            try:
                nutrients_data = json.loads(upload.nutrients_json)
                if not isinstance(nutrients_data, list):
                    continue

                # Группируем по дате (без времени)
                upload_date = upload.created_at.date()
                date_str = upload_date.strftime('%Y-%m-%d')

                if date_str not in daily_stats:
                    daily_stats[date_str] = {
                        'date': upload_date,
                        'calories': 0,
                        'protein': 0,
                        'fat': 0,
                        'carbohydrates': 0,
                        'fiber': 0,
                        'uploads_count': 0
                    }

                daily_stats[date_str]['uploads_count'] += 1

                # Суммируем нутриенты по всем блюдам в загрузке
                for dish_data in nutrients_data:
                    nutrients = dish_data.get('nutrients', {})
                    daily_stats[date_str]['calories'] += nutrients.get('calories', 0)
                    daily_stats[date_str]['protein'] += nutrients.get('protein', 0)
                    daily_stats[date_str]['fat'] += nutrients.get('fat', 0)
                    daily_stats[date_str]['carbohydrates'] += nutrients.get('carbohydrates', 0)
                    daily_stats[date_str]['fiber'] += nutrients.get('fiber', 0)

            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        # Сортируем по дате (новые сначала)
        sorted_stats = sorted(daily_stats.values(), key=lambda x: x['date'], reverse=True)

        return render_template("nutrition_stats.html", daily_stats=sorted_stats)

    @app.get("/use/<int:upload_id>")
    @login_required
    def use_upload(upload_id: int):  # type: ignore
        """Возвращает пользователя на главную с выбранным изображением."""
        upload_rec = db.get_or_404(Upload, upload_id)
        if upload_rec.user_id != current_user.id:
            return "Forbidden", 403

        image_url = url_for("uploaded_file", filename=upload_rec.filename, _external=False)
        # Обновляем сессию — выбран именно этот файл
        session["last_image"] = image_url
        return redirect(url_for("index", image=image_url))

    @app.get("/delete/<int:upload_id>")
    @login_required
    def delete_upload(upload_id: int):  # type: ignore
        """Удаляет запись и сам файл (если существует)."""
        upload_rec = db.get_or_404(Upload, upload_id)
        if upload_rec.user_id != current_user.id:
            return "Forbidden", 403

        # Удаляем файл если он существует
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], upload_rec.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        db.session.delete(upload_rec)
        db.session.commit()

        # Если пользователь удалил файл, который показывался в превью — очищаем сессию
        image_url = url_for("uploaded_file", filename=upload_rec.filename, _external=False)
        if session.get("last_image") == image_url:
            session.pop("last_image", None)

        return redirect(url_for("history"))

    @app.route("/forgot", methods=["GET", "POST"])
    def forgot_password():  # type: ignore
        """Форма запроса ссылки для сброса пароля."""
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        message: str | None = None
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            # Не раскрываем, существует ли email
            user = db.session.execute(select(User).filter_by(email=email)).scalar_one_or_none()
            if user:
                _send_reset_email(app, user)
            # Сообщаем однотипно
            message = "Если такой email зарегистрирован, мы отправили ссылку для сброса пароля."
        return render_template("forgot.html", message=message)

    @app.route("/reset/<token>", methods=["GET", "POST"])
    def reset_password(token: str):  # type: ignore
        """Сброс пароля по токену."""
        serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
        try:
            email = serializer.loads(token, salt="password-reset-salt", max_age=3600)
        except (BadSignature, SignatureExpired):
            return "Ссылка недействительна или устарела", 400

        user = db.first_or_404(select(User).filter_by(email=email))

        success: str | None = None
        error: str | None = None

        if request.method == "POST":
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            if not password or not confirm:
                error = "Заполните оба поля"
            elif password != confirm:
                error = "Пароли не совпадают"
            else:
                user.set_password(password)
                db.session.commit()
                success = "Пароль обновлён. Теперь вы можете войти."
        return render_template("reset.html", error=error, success=success)

    return app


# ----------------------------------------------------------------------------
# Точка входа
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    # Для локальной отладки. В проде вместо debug=True — нормальный сервер.
    server_config = config["server"]
    create_app().run(
        host=server_config["host"],
        port=server_config["port"],
        debug=server_config["debug"]
    )