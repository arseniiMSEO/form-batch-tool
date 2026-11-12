"""Перевірка вхідних даних: список цілей, тип подачі, файл-доказ.

Валідація детермінована і без мережі: її легко покрити тестами.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import config


@dataclass
class FileCheck:
    ok: bool
    reason: str = ""


def parse_targets(raw: str, submission_type: str | None = None) -> list[str]:
    """З тексту (по одній цілі на рядок) робить чистий список.

    Прибирає порожні рядки і пробіли, відсікає дублі, зберігаючи порядок першої
    появи. Дедуп - це перший рівень захисту від подвійної відправки на ту саму
    ціль. Для Domain/IP регістр не важливий (хост нечутливий), тож дедуп без
    урахування регістру; для URL шлях і query чутливі до регістру (RFC 3986),
    тож два URL, що відрізняються лише регістром, - це РІЗНІ цілі, і їх не
    склеюємо.
    """
    case_sensitive = submission_type == "URL"
    seen: set[str] = set()
    targets: list[str] = []
    for line in raw.splitlines():
        value = line.strip()
        if not value:
            continue
        key = value if case_sensitive else value.lower()
        if key in seen:
            continue
        seen.add(key)
        targets.append(value)
    return targets


def validate_submission_type(value: str) -> bool:
    return value in config.ALLOWED_SUBMISSION_TYPES


def file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_file(filename: str, size_bytes: int) -> FileCheck:
    """Перевіряє тип і розмір файлу-доказу. Нічого не зберігає, лише судить."""
    if not filename:
        return FileCheck(False, "Файл не вибрано")
    ext = file_extension(filename)
    if ext not in config.ALLOWED_FILE_EXT:
        allowed = ", ".join(sorted(config.ALLOWED_FILE_EXT))
        return FileCheck(False, f"Недозволений тип файлу .{ext}. Можна: {allowed}")
    if size_bytes <= 0:
        return FileCheck(False, "Файл порожній")
    if size_bytes > config.MAX_FILE_BYTES:
        mb = config.MAX_FILE_BYTES / (1024 * 1024)
        return FileCheck(False, f"Файл більший за {mb:.0f} МБ")
    return FileCheck(True)


def validate_batch(submission_type: str, targets: list[str], threat_type: str,
                   reason: str) -> list[str]:
    """Повертає список помилок рівня всього батчу (без перевірки файлу)."""
    errors: list[str] = []
    if not validate_submission_type(submission_type):
        errors.append("Невідомий Submission Type")
    if not targets:
        errors.append("Список цілей порожній")
    if not threat_type.strip():
        errors.append("Не вказано Threat Type")
    if not reason.strip():
        errors.append("Не вказано Reason")
    return errors
