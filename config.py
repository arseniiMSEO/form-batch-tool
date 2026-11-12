"""Налаштування тули. Значення беруться зі змінних середовища (.env), з безпечними
значеннями за замовчуванням (локальний макет форми).

Селектори форми винесені сюди навмисно: щоб націлити тул на реальну форму,
правиш лише цей файл, а не код.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "jobs.db"


def _get(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val is not None and val != "" else default


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    return _get(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


# Де лежить форма. За замовчуванням - локальний макет (безпечно).
FORM_URL = _get("FORM_URL", "http://127.0.0.1:5000/mock-form")

# Вікно браузера видно (людина вирішує капчу). Для реальної форми не ставити true.
HEADLESS = _get_bool("HEADLESS", False)

RATE_LIMIT_SECONDS = _get_int("RATE_LIMIT_SECONDS", 3)
MAX_ATTEMPTS = _get_int("MAX_ATTEMPTS", 3)
HUMAN_CONFIRM_TIMEOUT = _get_int("HUMAN_CONFIRM_TIMEOUT", 180)
PORT = _get_int("PORT", 5000)
# Адреса, на якій слухає веб-сервер. Локально 127.0.0.1; у Docker ставимо
# 0.0.0.0 (через environment у docker-compose), інакше проброс порту не працює.
HOST = _get("HOST", "127.0.0.1")

# Дозволені типи і розмір файлу-доказу.
ALLOWED_FILE_EXT = {"jpg", "jpeg", "png", "pdf"}
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 МБ

ALLOWED_SUBMISSION_TYPES = ("Domain", "IP", "URL")

# Селектори полів форми. Для макета вони вже збігаються.
# Для реальної форми: відкрити її, подивитись реальні name/селектори і вписати сюди.
FORM_FIELDS = {
    "submission_type": 'select[name="submission_type"]',
    "target": 'input[name="target"]',
    "threat_type": 'input[name="threat_type"]',
    "reason": 'textarea[name="reason"]',
    "file": 'input[type="file"][name="evidence"]',
    "submit": 'button[type="submit"]',
    # Елемент, у якому після успішної відправки зʼявляється код підтвердження CF-XXXXXXXX.
    "confirmation_code": ".confirmation-code",
    # Елемент з текстом помилки (якщо форма показує помилку).
    "error": ".form-error",
}

# Формат коду підтвердження, який парсимо з результату.
CONFIRMATION_CODE_PATTERN = r"CF-[A-Z0-9]{8}"
