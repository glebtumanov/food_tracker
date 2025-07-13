#!/usr/bin/env python3
"""
Скрипт для тестирования отправки писем
Запуск: python test_email.py
"""

import yaml
import sys
import ssl
import smtplib
from email.message import EmailMessage

def test_email_config():
    """Тестирует отправку тестового письма"""

    # Загружаем конфигурацию
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("❌ Файл config.yaml не найден. Скопируйте config.example.yaml в config.yaml")
        return False
    except yaml.YAMLError as e:
        print(f"❌ Ошибка в файле config.yaml: {e}")
        return False

    mail_config = config.get('mail', {})

    # Проверяем наличие необходимых настроек
    required_fields = ['server', 'port', 'username', 'password', 'default_sender']
    missing_fields = []

    for field in required_fields:
        if not mail_config.get(field):
            missing_fields.append(field)

    if missing_fields:
        print(f"❌ Отсутствуют обязательные настройки почты: {', '.join(missing_fields)}")
        return False

    # Проверяем, что настройки не являются примерами
    if mail_config['username'] == 'your-email@gmail.com':
        print("❌ Настройки почты не изменены. Укажите реальные данные в config.yaml")
        return False

    print("🔧 Тестирование SMTP соединения...")
    print(f"   Сервер: {mail_config['server']}:{mail_config['port']}")
    print(f"   Пользователь: {mail_config['username']}")
    print(f"   TLS: {mail_config.get('use_tls', True)}")
    print(f"   SSL: {mail_config.get('use_ssl', False)}")

    # Тестируем отправку письма
    try:
        msg = EmailMessage()
        msg["Subject"] = "Тест настройки почты - Food Tracker"
        msg["From"] = mail_config['default_sender']
        msg["To"] = mail_config['username']  # Отправляем самому себе

        msg.set_content("""
        Это тестовое письмо от Food Tracker.

        Если вы получили это письмо, значит настройки почты работают корректно!

        Настройки:
        - Сервер: {}
        - Порт: {}
        - Пользователь: {}

        Food Tracker готов к работе!
        """.format(
            mail_config['server'],
            mail_config['port'],
            mail_config['username']
        ))

        context = ssl.create_default_context()

        if mail_config.get('use_ssl', False):
            print("🔗 Подключение через SSL...")
            with smtplib.SMTP_SSL(mail_config['server'], mail_config['port'], context=context) as smtp:
                smtp.login(mail_config['username'], mail_config['password'])
                smtp.send_message(msg)
        else:
            print("🔗 Подключение через TLS...")
            with smtplib.SMTP(mail_config['server'], mail_config['port']) as smtp:
                if mail_config.get('use_tls', True):
                    smtp.starttls(context=context)
                smtp.login(mail_config['username'], mail_config['password'])
                smtp.send_message(msg)

        print("✅ Тестовое письмо отправлено успешно!")
        print(f"   Проверьте почту: {mail_config['username']}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("❌ Ошибка аутентификации:")
        print("   - Проверьте логин и пароль")
        print("   - Для Gmail используйте пароль приложения, не основной пароль")
        print("   - Убедитесь, что включена двухфакторная аутентификация")
        return False

    except smtplib.SMTPConnectError:
        print("❌ Ошибка подключения:")
        print("   - Проверьте адрес сервера и порт")
        print("   - Убедитесь в наличии интернет-соединения")
        return False

    except smtplib.SMTPServerDisconnected:
        print("❌ Сервер разорвал соединение:")
        print("   - Попробуйте изменить настройки TLS/SSL")
        print("   - Проверьте правильность порта")
        return False

    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

def main():
    """Главная функция"""
    print("📧 Тестирование настроек почты Food Tracker")
    print("=" * 50)

    if test_email_config():
        print("\n✅ Настройки почты работают корректно!")
        print("   Теперь можно использовать регистрацию и сброс пароля")
    else:
        print("\n❌ Настройки почты требуют исправления")
        print("   Проверьте config.yaml и документацию")

    print("\n📖 Помощь:")
    print("   - Документация: README.md")
    print("   - Пример: config.example.yaml")

if __name__ == "__main__":
    main()