from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Final, Set

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
from sqlalchemy import inspect, text as sa_text

# ----------------------------------------------------------------------------
# Конфигурация
# ----------------------------------------------------------------------------

UPLOAD_FOLDER: Final[str] = "uploads"
ALLOWED_EXTENSIONS: Final[Set[str]] = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_CONTENT_LENGTH: Final[int] = 16 * 1024 * 1024  # 16 MB

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
    # Фейковый распознанный текст (пока заполнено заглушкой)
    text = db.Column(db.String(255), default="", nullable=False)
    # Контрольная сумма файла — пригодится для поиска дубликатов
    crc = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

@login_manager.user_loader  # type: ignore
def load_user(user_id: str):
    return User.query.get(int(user_id))

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
    app.config.update(
        UPLOAD_FOLDER=UPLOAD_FOLDER,
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        # Безопасность и БД
        SECRET_KEY=os.getenv("SECRET_KEY", _get_or_create_secret_key()),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///app.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # Настройки cookie «Запомнить меня» на 7 дней
        REMEMBER_COOKIE_DURATION=timedelta(days=7),
        # Настройки почты (можно переопределить через переменные среды)
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.example.com"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", 465)),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME", "username"),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", "password"),
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER", "noreply@example.com"),
    )

    # Инициализируем расширения
    db.init_app(app)
    login_manager.init_app(app)

    # Регистрируем фильтры
    app.add_template_filter(_ru_weekday, name="ru_weekday")
    app.add_template_filter(_format_datetime_ru, name="ru_dt")

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
        if "text" not in upload_cols:
            # DEFAULT '', иначе ошибка из-за NOT NULL существующих строк
            alter_stmts.append("ALTER TABLE upload ADD COLUMN text VARCHAR(255) NOT NULL DEFAULT '';")
        if "crc" not in upload_cols:
            alter_stmts.append("ALTER TABLE upload ADD COLUMN crc VARCHAR(16) NOT NULL DEFAULT '';")

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
            text="",  # пока заглушка
        )
        db.session.add(upload_record)
        db.session.commit()

        file_url = url_for("uploaded_file", filename=unique_name, _external=False)
        # Запоминаем в сессии, чтобы отображать после переходов по сайту
        session["last_image"] = file_url
        return jsonify({"url": file_url})

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str):  # type: ignore
        """Отдаёт сохранённое изображение."""
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

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

            if User.query.filter_by(email=email).first():
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

        user = User.query.filter_by(email=email).first_or_404()
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
            user = User.query.filter_by(email=email).first()

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
                last_upload = (
                    Upload.query.filter_by(user_id=user.id)
                    .order_by(Upload.created_at.desc())
                    .first()
                )
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
        uploads = (
            Upload.query.filter_by(user_id=current_user.id)
            .order_by(Upload.created_at.asc())
            .all()
        )
        return render_template("history.html", uploads=uploads)

    @app.get("/use/<int:upload_id>")
    @login_required
    def use_upload(upload_id: int):  # type: ignore
        """Возвращает пользователя на главную с выбранным изображением."""
        upload_rec = Upload.query.get_or_404(upload_id)
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
        upload_rec = Upload.query.get_or_404(upload_id)
        if upload_rec.user_id != current_user.id:
            return "Forbidden", 403

        # Пытаемся удалить сам файл – не критично, если его нет.
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], upload_rec.filename))
        except FileNotFoundError:
            pass

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
            user = User.query.filter_by(email=email).first()
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

        user = User.query.filter_by(email=email).first_or_404()

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
    create_app().run(host="0.0.0.0", port=5001, debug=True)