"""Заповнення однієї форми через браузер (Playwright).

Свідоме рішення: капчу тул НЕ обходить. 2captcha та подібні сервіси тут не
використовуються. Браузер відкривається видимим (HEADLESS=false), людина
вирішує капчу і натискає Submit у вікні. Кожна скарга - це юридичне твердження,
тому фінальну відправку завжди підтверджує людина, а не скрипт.

Заповнення (fill_form) і читання результату (read_result) розділені навмисно:
якщо після заповнення людина довго вирішує капчу, повтор має лише ще раз
почекати результат на ТІЙ САМІЙ сторінці, а не перезаповнювати форму і стирати
вже введену капчу.

Статуси результату:
- sent: форму відправлено, код підтвердження розпізнано;
- sent_unverified: форму відправлено, але код не вдалось розпізнати (інший
  формат) - рядок НЕ повторюється, щоб не подати скаргу вдруге; сира відповідь
  зберігається для ручної звірки оператором;
- error: форма показала непорожню помилку - рядок можна повторити вручну.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import config


class TransientError(Exception):
    """Тимчасовий стан (таймаут очікування результату, мережа, 5xx): можна
    почекати/повторити читання результату."""


@dataclass
class FillResult:
    status: str            # 'sent' | 'sent_unverified' | 'error'
    confirmation_code: str = ""
    error: str = ""
    raw: str = ""          # сирий текст відповіді, коли код не розпізнано


def fill_form(page, job) -> None:
    """Відкриває форму і заповнює поля. Капчу і Submit робить людина далі.
    Збої відкриття/заповнення вважаємо тимчасовими (сервер міг не відповісти)."""
    f = config.FORM_FIELDS
    try:
        page.goto(config.FORM_URL, timeout=30000)
        page.select_option(f["submission_type"], job.submission_type)
        page.fill(f["target"], job.target)
        page.fill(f["threat_type"], job.threat_type)
        page.fill(f["reason"], job.reason)
        if job.file_path:
            page.set_input_files(f["file"], job.file_path)
    except Exception as exc:  # noqa: BLE001
        raise TransientError(f"не вдалося відкрити або заповнити форму: {exc}") from exc


def read_result(page) -> FillResult:
    """Чекає результат після того, як людина вирішила капчу і натиснула Submit.

    Таймаут очікування = людина не встигла (або сервер мовчить): TransientError,
    щоб почекати ще на ТІЙ САМІЙ сторінці, не перезаповнюючи форму.
    """
    f = config.FORM_FIELDS
    timeout_ms = config.HUMAN_CONFIRM_TIMEOUT * 1000
    try:
        page.wait_for_selector(
            f"{f['confirmation_code']}, {f['error']}", timeout=timeout_ms
        )
    except Exception as exc:  # noqa: BLE001
        raise TransientError(
            "не дочекались результату: капчу не вирішено або Submit не натиснуто вчасно"
        ) from exc

    # Помилкою вважаємо лише НЕПОРОЖНІЙ текст у елементі помилки. Багато форм
    # тримають завжди присутній порожній контейнер помилки, і його наявність не
    # означає збій.
    err = page.query_selector(f["error"])
    err_text = (err.inner_text() if err else "") or ""
    err_text = err_text.strip()
    if err_text:
        return FillResult(status="error", error=err_text)

    code_el = page.query_selector(f["confirmation_code"])
    if code_el is not None:
        text = ((code_el.inner_text() or "")).strip()
        match = re.search(config.CONFIRMATION_CODE_PATTERN, text)
        if match:
            return FillResult(status="sent", confirmation_code=match.group(0))
        # Форму відправлено (елемент результату зʼявився), але код не впізнано.
        # НЕ помилка і НЕ привід слати вдруге: позначаємо sent_unverified.
        return FillResult(status="sent_unverified", raw=text or "(порожній результат)")

    # Ні тексту помилки, ні елемента з кодом: результат незрозумілий, але Submit
    # уже відбувся. Безпечний бік - не повторювати.
    return FillResult(status="sent_unverified", raw="(результат не розпізнано)")
