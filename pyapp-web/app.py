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
    # Асинхронные задания chain-server
    job_id_analysis = db.Column(db.String(64), nullable=True)
    job_id_full = db.Column(db.String(64), nullable=True)

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

    # Отправляем письмо через SMTP
    try:
        msg = EmailMessage()
        msg["Subject"] = "Подтвердите регистрацию в Food Tracker"
        msg["From"] = app.config["MAIL_DEFAULT_SENDER"]
        msg["To"] = user.email

        # HTML содержимое письма
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #198754; margin: 0;">🍽️ Food Tracker</h2>
                <p style="color: #6c757d; margin: 10px 0 0 0;">Анализ питания с помощью ИИ</p>
            </div>

            <h3 style="color: #212529;">Подтверждение регистрации</h3>

            <p style="color: #495057; line-height: 1.6;">
                Здравствуйте!<br><br>
                Вы зарегистрировались в приложении Food Tracker.
                Для завершения регистрации необходимо подтвердить ваш email адрес.
            </p>

            <div style="text-align: center; margin: 30px 0;">
                <a href="{confirm_url}"
                   style="background-color: #198754; color: white; padding: 12px 24px;
                          text-decoration: none; border-radius: 6px; font-weight: 500;
                          display: inline-block;">
                    Подтвердить email
                </a>
            </div>

            <p style="color: #6c757d; font-size: 14px; line-height: 1.5;">
                Если кнопка не работает, скопируйте и вставьте следующую ссылку в адресную строку браузера:<br>
                <a href="{confirm_url}" style="color: #0d6efd; word-break: break-all;">{confirm_url}</a>
            </p>

            <hr style="border: none; border-top: 1px solid #dee2e6; margin: 30px 0;">

            <p style="color: #6c757d; font-size: 12px; margin: 0;">
                Это письмо было отправлено автоматически. Если вы не регистрировались в Food Tracker,
                просто проигнорируйте это письмо.
            </p>
        </body>
        </html>
        """

        # Текстовая версия письма
        text_content = f"""
        Food Tracker - Подтверждение регистрации

        Здравствуйте!

        Вы зарегистрировались в приложении Food Tracker.
        Для завершения регистрации необходимо подтвердить ваш email адрес.

        Перейдите по ссылке для подтверждения:
        {confirm_url}

        Если вы не регистрировались в Food Tracker, просто проигнорируйте это письмо.
        """

        msg.set_content(text_content)
        msg.add_alternative(html_content, subtype='html')

        # Отправляем письмо
        context = ssl.create_default_context()
        if app.config.get("MAIL_USE_SSL", True):
            with smtplib.SMTP_SSL(app.config["MAIL_SERVER"], app.config["MAIL_PORT"], context=context) as smtp:
                smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"]) as smtp:
                if app.config.get("MAIL_USE_TLS", True):
                    smtp.starttls(context=context)
                smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
                smtp.send_message(msg)

        app.logger.info("Письмо подтверждения отправлено на %s", user.email)

    except Exception as e:
        app.logger.error("Ошибка отправки письма подтверждения для %s: %s", user.email, str(e))
        # В случае ошибки отправки письма, продолжаем работу (письмо уже залогировано)

# -------------------- Сброс пароля --------------------

def _send_reset_email(app: Flask, user: User) -> None:
    """Формирует и отправляет ссылку для сброса пароля."""

    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    token = serializer.dumps(user.email, salt="password-reset-salt")
    reset_url = url_for("reset_password", token=token, _external=True)

    # Пока вместо реальной отправки письма выводим ссылку в лог
    app.logger.info("Ссылка для сброса пароля %s: %s", user.email, reset_url)

    # Отправляем письмо через SMTP
    try:
        msg = EmailMessage()
        msg["Subject"] = "Сброс пароля - Food Tracker"
        msg["From"] = app.config["MAIL_DEFAULT_SENDER"]
        msg["To"] = user.email

        # HTML содержимое письма
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #198754; margin: 0;">🍽️ Food Tracker</h2>
                <p style="color: #6c757d; margin: 10px 0 0 0;">Анализ питания с помощью ИИ</p>
            </div>

            <h3 style="color: #212529;">Сброс пароля</h3>

            <p style="color: #495057; line-height: 1.6;">
                Здравствуйте!<br><br>
                Вы запросили сброс пароля для вашего аккаунта в Food Tracker.
                Для создания нового пароля перейдите по ссылке ниже.
            </p>

            <div style="text-align: center; margin: 30px 0;">
                <a href="{reset_url}"
                   style="background-color: #dc3545; color: white; padding: 12px 24px;
                          text-decoration: none; border-radius: 6px; font-weight: 500;
                          display: inline-block;">
                    Сбросить пароль
                </a>
            </div>

            <p style="color: #6c757d; font-size: 14px; line-height: 1.5;">
                Если кнопка не работает, скопируйте и вставьте следующую ссылку в адресную строку браузера:<br>
                <a href="{reset_url}" style="color: #0d6efd; word-break: break-all;">{reset_url}</a>
            </p>

            <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 6px; margin: 20px 0;">
                <p style="color: #856404; margin: 0; font-size: 14px;">
                    ⚠️ <strong>Важно:</strong> Ссылка действительна только в течение 1 часа после отправки.
                    Если вы не запрашивали сброс пароля, просто проигнорируйте это письмо.
                </p>
            </div>

            <hr style="border: none; border-top: 1px solid #dee2e6; margin: 30px 0;">

            <p style="color: #6c757d; font-size: 12px; margin: 0;">
                Это письмо было отправлено автоматически. Если у вас есть вопросы о безопасности
                вашего аккаунта, свяжитесь с поддержкой.
            </p>
        </body>
        </html>
        """

        # Текстовая версия письма
        text_content = f"""
        Food Tracker - Сброс пароля

        Здравствуйте!

        Вы запросили сброс пароля для вашего аккаунта в Food Tracker.
        Для создания нового пароля перейдите по ссылке ниже.

        Ссылка для сброса пароля:
        {reset_url}

        ВАЖНО: Ссылка действительна только в течение 1 часа после отправки.
        Если вы не запрашивали сброс пароля, просто проигнорируйте это письмо.
        """

        msg.set_content(text_content)
        msg.add_alternative(html_content, subtype='html')

        # Отправляем письмо
        context = ssl.create_default_context()
        if app.config.get("MAIL_USE_SSL", True):
            with smtplib.SMTP_SSL(app.config["MAIL_SERVER"], app.config["MAIL_PORT"], context=context) as smtp:
                smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"]) as smtp:
                if app.config.get("MAIL_USE_TLS", True):
                    smtp.starttls(context=context)
                smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
                smtp.send_message(msg)

        app.logger.info("Письмо сброса пароля отправлено на %s", user.email)

    except Exception as e:
        app.logger.error("Ошибка отправки письма сброса пароля для %s: %s", user.email, str(e))
        # В случае ошибки отправки письма, продолжаем работу (письмо уже залогировано)

# ----------------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    """Проверяет расширение файла."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _safe_pretty(obj: Any, max_len: int = 2000) -> str:
    try:
        if isinstance(obj, str):
            s = obj
        else:
            s = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        s = str(obj)
    return s if len(s) <= max_len else s[:max_len] + "\n...[truncated]..."


def analyze_image_with_chain_server(image_path: str) -> Dict[str, Any]:
    """Анализирует изображение с помощью chain-сервера."""
    chain_config = config.get("chain_server", {})

    chain_url = chain_config.get("url", "http://localhost:8000")
    analyze_endpoint = chain_config.get("analyze_endpoint", "/api/v1/analyze")
    analyze_full_endpoint = chain_config.get("analyze_full_endpoint", "/api/v1/analyze-full")
    timeout = chain_config.get("timeout", 30)

    # Выбор endpoint'а зависит от флага single_request_mode
    features = config.get("features", {})
    single_request_mode = bool(features.get("single_request_mode", False))
    full_url = f"{chain_url}{(analyze_full_endpoint if single_request_mode else analyze_endpoint)}"

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
        # Отладочная печать ответа chain-server, если включено
        debug_conf = config.get("debug", {})
        if debug_conf.get("api_log", False):
            print("===== chain-server /analyze RAW response =====")
            print(_safe_pretty(result, int(debug_conf.get("max_print_chars", 2000))))
            print("===== /chain-server /analyze RAW response =====")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # Если включен single_request_mode, сервер возвращает {analysis, nutrients}
        if single_request_mode:
            return result
        else:
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

    # Автоматически строим правильный путь к базе данных
    app_dir = Path(__file__).resolve().parent
    db_path = app_dir / "instance" / "app.db"
    database_url = f"sqlite:///{db_path}"

    app.config.update(
        UPLOAD_FOLDER=upload_config["folder"],
        MAX_CONTENT_LENGTH=upload_config["max_content_length_mb"] * 1024 * 1024,
        # Безопасность и БД
        SECRET_KEY=os.getenv("SECRET_KEY", security_config.get("secret_key") or _get_or_create_secret_key()),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", database_url),
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
        # Новые поля для асинхронной очереди задач
        if "job_id_analysis" not in upload_cols:
            alter_stmts.append("ALTER TABLE upload ADD COLUMN job_id_analysis VARCHAR(64);")
        if "job_id_full" not in upload_cols:
            alter_stmts.append("ALTER TABLE upload ADD COLUMN job_id_full VARCHAR(64);")

        if alter_stmts:
            with engine.begin() as conn:
                for stmt in alter_stmts:
                    conn.execute(sa_text(stmt))

        # --- Очистка дубликатов пользователей ---
        # Проверяем наличие дубликатов email в таблице user
        try:
            with engine.begin() as conn:
                # Находим дубликаты email
                duplicate_check = conn.execute(sa_text("""
                    SELECT email, COUNT(*) as count
                    FROM user
                    GROUP BY email
                    HAVING COUNT(*) > 1
                """)).fetchall()

                if duplicate_check:
                    app.logger.warning(f"Найдено {len(duplicate_check)} дублированных email адресов")

                    # Для каждого дублированного email оставляем только самую старую запись
                    for row in duplicate_check:
                        email = row[0]
                        app.logger.info(f"Очистка дубликатов для email: {email}")

                        # Удаляем все записи кроме самой старой (с минимальным id)
                        conn.execute(sa_text("""
                            DELETE FROM user
                            WHERE email = :email
                            AND id NOT IN (
                                SELECT id FROM (
                                    SELECT MIN(id) as id
                                    FROM user
                                    WHERE email = :email
                                ) AS keeper
                            )
                        """), {"email": email})

                    app.logger.info("Дубликаты пользователей успешно удалены")

                # Проверяем и создаем уникальный индекс на email если его нет
                try:
                    # Проверяем существует ли уникальный индекс на email
                    indexes = conn.execute(sa_text("PRAGMA index_list(user)")).fetchall()
                    email_unique_exists = False

                    for index in indexes:
                        index_name = index[1]  # имя индекса
                        is_unique = index[2]   # уникальный ли

                        if is_unique:
                            # Проверяем колонки индекса
                            index_info = conn.execute(sa_text(f"PRAGMA index_info({index_name})")).fetchall()
                            for col_info in index_info:
                                if col_info[2] == 'email':  # название колонки
                                    email_unique_exists = True
                                    break

                    if not email_unique_exists:
                        app.logger.info("Создание уникального индекса для email")
                        conn.execute(sa_text("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_email_unique ON user (email)"))

                except Exception as idx_e:
                    app.logger.warning(f"Не удалось создать уникальный индекс на email: {idx_e}")

        except Exception as e:
            app.logger.error(f"Ошибка при очистке дубликатов пользователей: {e}")
            # Продолжаем работу, не критичная ошибка

    # ---------------------------------------------------------------------
    # Роуты
    # ---------------------------------------------------------------------

    @app.get("/")
    @login_required
    def index():  # type: ignore
        """Главная страница с опциональным предпросмотром ранее загруженного изображения."""
        # Приоритет: параметр строки запроса → сохранённый в сессии URL
        preload_url = request.args.get("image") or session.get("last_image", "")
        features = config.get("features", {})
        return render_template("index.html", preload_url=preload_url, features=features)

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

    # ----------------------------- Очередь задач -----------------------------

    def _chain_base_url_timeout() -> tuple[str, int]:
        chain_config = config.get("chain_server", {})
        chain_url = chain_config.get("url", "http://localhost:8000")
        timeout = chain_config.get("timeout", 45)
        return chain_url, timeout

    def _encode_image_to_base64(image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def _create_chain_job(image_path: str, filename: str, mode: str) -> tuple[bool, str | None, str | None]:
        """Создаёт задачу на chain‑server. Возвращает (ok, job_id, error_msg)."""
        chain_url, timeout = _chain_base_url_timeout()
        try:
            payload = {
                "image_base64": _encode_image_to_base64(image_path),
                "filename": filename,
                "params": {"mode": mode},
            }
            resp = requests.post(
                f"{chain_url}/api/v1/jobs",
                json=payload,
                timeout=timeout,
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code == 200:
                data = resp.json()
                return True, data.get("job_id"), None
            try:
                data = resp.json()
                return False, None, data.get("detail") or f"HTTP {resp.status_code}"
            except Exception:
                return False, None, f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, None, str(e)

    def _fetch_job_status(job_id: str) -> dict[str, Any] | None:
        chain_url, timeout = _chain_base_url_timeout()
        try:
            resp = requests.get(f"{chain_url}/api/v1/jobs/{job_id}", timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            return None
        except requests.RequestException:
            return None

    def _maybe_ingest_job_result(upload_record: Upload) -> None:
        """Если у загрузки есть job_id и результатов нет — подтянуть их из chain‑server и сохранить."""
        job_id = upload_record.job_id_full or upload_record.job_id_analysis
        if not job_id:
            return
        # Если анализ уже сохранён, проверим только нутриенты для полного режима
        if upload_record.ingredients_json and upload_record.ingredients_md and not upload_record.job_id_full:
            return
        status = _fetch_job_status(job_id)
        if not status or status.get("status") != "done":
            return
        result = status.get("result") or {}

        # Сохраняем анализ
        analysis_payload = result.get("analysis") or {}
        if analysis_payload and not (upload_record.ingredients_json and upload_record.ingredients_md):
            dishes = analysis_payload.get("dishes", [])
            confidence = analysis_payload.get("confidence", 0)
            md = f"**Результат анализа изображения:**\n\n"
            md += f"**Уверенность:** {confidence:.1%}\n\n"
            md += "**Обнаруженные блюда:**\n\n"
            for i, dish in enumerate(dishes, 1):
                name = dish.get("name", "Неизвестное блюдо")
                name_en = dish.get("name_en", "")
                unit_type = dish.get("unit_type", "")
                amount = dish.get("amount", 0)
                md += f"{i}. **{name}**"
                if name_en:
                    md += f" _{name_en}_"
                if unit_type and amount:
                    if unit_type == "штук":
                        md += f" — {amount:.0f} {unit_type}"
                    else:
                        md += f" — {amount} {unit_type}"
                md += "\n\n"

            upload_record.ingredients_md = md
            upload_record.ingredients_json = json.dumps(analysis_payload, indent=2, ensure_ascii=False)

        # Сохраняем нутриенты только для полного режима
        if upload_record.job_id_full and not upload_record.nutrients_json:
            nutrients = result.get("nutrients")
            if nutrients and nutrients.get("dishes") is not None:
                nutrients_data = []
                # Берём список блюд из analysis, чтобы сопоставить
                analysis_json = {}
                try:
                    if upload_record.ingredients_json:
                        analysis_json = json.loads(upload_record.ingredients_json)
                except json.JSONDecodeError:
                    analysis_json = {}
                dishes_list = analysis_json.get("dishes", []) if isinstance(analysis_json, dict) else []
                for i, dish_result in enumerate(nutrients.get("dishes", [])):
                    corresponding_dish = dishes_list[i] if i < len(dishes_list) else {}
                    nutrients_entry = {
                        "dish": corresponding_dish.get("name_en") or corresponding_dish.get("name") or f"Блюдо {i+1}",
                        "amount": corresponding_dish.get("amount", 100),
                        # Сохраняем единицу так, как есть в анализе (рус.) — UI корректно отобразит
                        "unit": corresponding_dish.get("unit_type", "грамм"),
                        "nutrients": dish_result,
                        "analyzed_at": datetime.utcnow().isoformat()
                    }
                    nutrients_data.append(nutrients_entry)
                upload_record.nutrients_json = json.dumps(nutrients_data, indent=2, ensure_ascii=False)

        db.session.commit()

    @app.post("/queue_analysis")
    @login_required
    def queue_analysis():  # type: ignore
        if not current_user.is_confirmed:
            return jsonify({"error": "Подтвердите email"}), 403
        data = request.get_json() or {}
        upload_id = data.get("upload_id")
        if not upload_id:
            return jsonify({"error": "ID загрузки не указан"}), 400
        upload_record = db.get_or_404(Upload, upload_id)
        if upload_record.user_id != current_user.id:
            return jsonify({"error": "Доступ запрещен"}), 403
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], upload_record.filename)
        if not os.path.exists(image_path):
            return jsonify({"error": "Файл изображения не найден"}), 404
        ok, job_id, err = _create_chain_job(image_path, upload_record.filename, mode="analysis")
        if not ok or not job_id:
            return jsonify({"error": err or "Не удалось создать задачу"}), 500
        upload_record.job_id_analysis = job_id
        db.session.commit()
        return jsonify({"queued": True, "job_id": job_id, "message": "Запрос отправлен. Обновите страницу позже."})

    @app.post("/queue_nutrients")
    @login_required
    def queue_nutrients():  # type: ignore
        if not current_user.is_confirmed:
            return jsonify({"error": "Подтвердите email"}), 403
        data = request.get_json() or {}
        upload_id = data.get("upload_id")
        if not upload_id:
            return jsonify({"error": "ID загрузки не указан"}), 400
        upload_record = db.get_or_404(Upload, upload_id)
        if upload_record.user_id != current_user.id:
            return jsonify({"error": "Доступ запрещен"}), 403
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], upload_record.filename)
        if not os.path.exists(image_path):
            return jsonify({"error": "Файл изображения не найден"}), 404
        ok, job_id, err = _create_chain_job(image_path, upload_record.filename, mode="full")
        if not ok or not job_id:
            return jsonify({"error": err or "Не удалось создать задачу"}), 500
        upload_record.job_id_full = job_id
        db.session.commit()
        return jsonify({"queued": True, "job_id": job_id, "message": "Запрос отправлен. Обновите страницу позже."})

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

        # Сначала подтягиваем результаты задач (если готовы), затем читаем актуальные данные
        try:
            _maybe_ingest_job_result(upload_record)
        except Exception as _:
            pass

        # Декодируем JSON если он есть (после возможного обновления)
        ingredients_json = None
        if upload_record.ingredients_json:
            ingredients_json = json.loads(upload_record.ingredients_json)

        nutrients_json = None
        if upload_record.nutrients_json:
            nutrients_json = json.loads(upload_record.nutrients_json)

        # Получим актуальные статусы задач, если есть
        job_status_analysis = None
        job_status_full = None
        if upload_record.job_id_analysis:
            status = _fetch_job_status(upload_record.job_id_analysis)
            job_status_analysis = status.get("status") if status else None
        if upload_record.job_id_full:
            status = _fetch_job_status(upload_record.job_id_full)
            job_status_full = status.get("status") if status else None

        return jsonify({
            "ingredients_md": upload_record.ingredients_md,
            "ingredients_json": ingredients_json,
            "nutrients_json": nutrients_json,
            "upload_id": upload_record.id,
            "job_id_analysis": upload_record.job_id_analysis,
            "job_id_full": upload_record.job_id_full,
            "job_status_analysis": job_status_analysis,
            "job_status_full": job_status_full
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

        health_response = requests.get(f"{chain_url}/api/v1/health", timeout=5)
        if health_response.status_code != 200:
            return jsonify({"error": "Chain-сервер недоступен"}), 503

        health_data = health_response.json()
        if not health_data.get("image_analyzer_ready"):
            return jsonify({"error": "Анализатор не готов"}), 503

        # Анализируем изображение через chain-сервер (возможен полный анализ)
        analysis_result = analyze_image_with_chain_server(image_path)
        debug_conf = config.get("debug", {})
        if debug_conf.get("api_log", False):
            print("===== chain-server /analyze processed result =====")
            print(_safe_pretty(analysis_result, int(debug_conf.get("max_print_chars", 2000))))
            print("===== /chain-server /analyze processed result =====")

        # Проверяем результат анализа
        error_msg = analysis_result.get("error")
        if error_msg:
            return jsonify({
                "success": False,
                "error": error_msg
            }), 500

        # Режимы работы
        features = config.get("features", {})
        single_request_mode = bool(features.get("single_request_mode", False))

        # В режиме single_request_mode API возвращает {analysis, nutrients}
        analysis_payload = analysis_result.get("analysis") if single_request_mode else analysis_result

        # Формируем текст ингредиентов в markdown формате
        dishes = analysis_payload.get("dishes", [])
        confidence = analysis_payload.get("confidence", 0)

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
        upload_record.ingredients_json = json.dumps(analysis_payload, indent=2, ensure_ascii=False)
        # При обновлении ingredients_json очищаем nutrients_json
        upload_record.nutrients_json = None
        db.session.commit()

        if single_request_mode:
            return jsonify({
                "success": True,
                "analysis": analysis_payload,
                "nutrients": analysis_result.get("nutrients", {}),
                "formatted_text": ingredients_text
            })
        else:
            return jsonify({
                "success": True,
                "analysis": analysis_payload,
                "formatted_text": ingredients_text
            })

    @app.post("/analyze_nutrients")
    @login_required
    def analyze_nutrients():  # type: ignore
        """
        Анализирует питательную ценность блюд через chain-сервер.
        Поддерживает как одно блюдо (для обратной совместимости), так и множественные блюда.
        """
        if not current_user.is_confirmed:
            return jsonify({"error": "Подтвердите email"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Нет данных"}), 400

        upload_id = data.get("upload_id")

        # Поддерживаем два формата: старый (одно блюдо) и новый (множественные блюда)
        dishes_list = []
        is_single_dish_request = False  # Флаг для определения типа запроса

        if "dishes" in data:
            # Новый формат: множественные блюда
            dishes_data = data["dishes"]
            if not isinstance(dishes_data, list):
                return jsonify({"error": "Поле 'dishes' должно быть списком"}), 400

            for dish_item in dishes_data:
                if not isinstance(dish_item, dict):
                    return jsonify({"error": "Каждое блюдо должно быть объектом"}), 400

                dish_name = dish_item.get("dish", "").strip()
                if not dish_name:
                    return jsonify({"error": "Не указано название блюда"}), 400

                dishes_list.append({
                    "dish": dish_name,
                    "amount": dish_item.get("amount", 100),
                    "unit": dish_item.get("unit", "gram")
                })
        else:
            # Старый формат: одно блюдо (для обратной совместимости)
            dish = data.get("dish")
            amount = data.get("amount", 100)
            unit = data.get("unit", "грамм")

            if not dish:
                return jsonify({"error": "Не указано блюдо"}), 400

            dishes_list.append({
                "dish": dish,
                "amount": amount,
                "unit": unit
            })
            is_single_dish_request = True

        # Если указан upload_id, проверяем права доступа
        upload_record = None
        if upload_id:
            upload_record = db.get_or_404(Upload, upload_id)
            if upload_record.user_id != current_user.id:
                return jsonify({"error": "Доступ запрещен"}), 403

        # Настройки chain-сервера
        chain_config = config.get("chain_server", {})
        chain_url = chain_config.get("url", "http://localhost:8000")
        timeout = chain_config.get("timeout", 45)  # Увеличиваем таймаут для множественного анализа

        # Если включен single_request_mode, этот маршрут может вызываться только для повторного расчёта,
        # но оставляем поведение прежним.

        # Проверяем, работает ли chain-сервер
        try:
            health_response = requests.get(f"{chain_url}/api/v1/health", timeout=5)
            if health_response.status_code != 200:
                return jsonify({"error": "Chain-сервер недоступен"}), 503

            health_data = health_response.json()
            if not health_data.get("nutrients_analyzer_ready"):
                return jsonify({"error": "Анализатор нутриентов не готов"}), 503
        except requests.RequestException:
            return jsonify({"error": "Chain-сервер недоступен"}), 503

        # Отправляем запрос на анализ нутриентов (одним запросом для всех блюд)
        try:
            response = requests.post(
                f"{chain_url}/api/v1/analyze-multiple-nutrients",
                json={"dishes": dishes_list},
                timeout=timeout,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                result = response.json()
                debug_conf = config.get("debug", {})
                if debug_conf.get("api_log", False):
                    print("===== chain-server /analyze-multiple-nutrients RAW response =====")
                    print(_safe_pretty(result, int(debug_conf.get("max_print_chars", 2000))))
                    print("===== /chain-server /analyze-multiple-nutrients RAW response =====")

                # Сохраняем результат в базу данных, если указан upload_id
                if upload_record:
                    # Очищаем старые данные нутриентов для новых результатов
                    upload_record.nutrients_json = None

                    if not result.get("error") and result.get("dishes"):
                        # Формируем данные для сохранения
                        nutrients_data = []
                        for i, dish_result in enumerate(result["dishes"]):
                            # Для простоты используем соответствие по индексу
                            # Поскольку порядок результатов должен соответствовать порядку запроса
                            if i < len(dishes_list):
                                corresponding_dish = dishes_list[i]
                            else:
                                # Если результатов больше чем блюд в запросе, используем последнее блюдо
                                corresponding_dish = dishes_list[-1] if dishes_list else None

                            nutrients_entry = {
                                "dish": corresponding_dish["dish"] if corresponding_dish else "Unknown",
                                "amount": corresponding_dish["amount"] if corresponding_dish else 100,
                                "unit": corresponding_dish["unit"] if corresponding_dish else "gram",
                                "nutrients": {
                                    "dish_name": dish_result.get("dish_name", ""),
                                    "calories": dish_result.get("calories", 0),
                                    "protein": dish_result.get("protein", 0),
                                    "fat": dish_result.get("fat", 0),
                                    "carbohydrates": dish_result.get("carbohydrates", 0),
                                    "fiber": dish_result.get("fiber", 0)
                                },
                                "analyzed_at": datetime.utcnow().isoformat()
                            }

                            # Если есть ошибка для этого блюда, добавляем её
                            if "error" in dish_result:
                                nutrients_entry["nutrients"]["error"] = dish_result["error"]

                            nutrients_data.append(nutrients_entry)

                        upload_record.nutrients_json = json.dumps(nutrients_data, indent=2, ensure_ascii=False)
                        db.session.commit()

                # Для обратной совместимости: если был запрос одного блюда, возвращаем только его результат
                if is_single_dish_request:
                    if result.get("dishes") and len(result["dishes"]) > 0:
                        single_result = result["dishes"][0]
                        return jsonify(single_result)
                    else:
                        return jsonify({"error": result.get("error", "Не удалось проанализировать блюдо")})

                # Для множественных блюд возвращаем полный результат
                if debug_conf.get("api_log", False):
                    print("===== chain-server /analyze-multiple-nutrients processed result =====")
                    print(_safe_pretty(result, int(debug_conf.get("max_print_chars", 2000))))
                    print("===== /chain-server /analyze-multiple-nutrients processed result =====")
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

        # Сначала пробуем подтянуть результат задачи, затем читаем из модели
        try:
            _maybe_ingest_job_result(upload_record)
        except Exception as _:
            pass

        nutrients_json = None
        if upload_record.nutrients_json:
            nutrients_json = json.loads(upload_record.nutrients_json)

        job_status_full = None
        if upload_record.job_id_full:
            status = _fetch_job_status(upload_record.job_id_full)
            job_status_full = status.get("status") if status else None

        return jsonify({
            "nutrients_json": nutrients_json,
            "upload_id": upload_record.id,
            "job_id_full": upload_record.job_id_full,
            "job_status_full": job_status_full
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

            if db.session.execute(select(User).filter_by(email=email)).first():
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

        user_row = db.session.execute(select(User).filter_by(email=email)).first()
        if not user_row:
            return "Пользователь не найден", 404
        user = user_row[0]
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
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            # Используем first() для устойчивости к возможным дубликатам
            user_row = db.session.execute(select(User).filter_by(email=email)).first()
            user = user_row[0] if user_row else None

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
                last_upload_row = db.session.execute(
                    select(Upload)
                    .filter_by(user_id=user.id)
                    .order_by(Upload.created_at.desc())
                ).first()
                last_upload = last_upload_row[0] if last_upload_row else None
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
            user_row = db.session.execute(select(User).filter_by(email=email)).first()
            user = user_row[0] if user_row else None
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

        user_row = db.session.execute(select(User).filter_by(email=email)).first()
        if not user_row:
            return "Пользователь не найден", 404
        user = user_row[0]

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