"""Обробка батчу: детермінована черга задач, по одній відправці на ціль.

Чому не LLM: масовість - це точна, повторювана робота (заповнити N разів ту саму
форму). LLM тут був би джерелом помилок і витрат. Тому це звичайний цикл з
чергою, паузами, повтором лише читання результату і захистом від подвійної
відправки (ідемпотентність).

Один запуск = один відкритий браузер. Для кожної задачі відкривається вкладка:
тул заповнює форму, людина вирішує капчу і тисне Submit, тул читає результат і
пише в базу. Заповнення робиться ОДИН раз; якщо людина довго вирішує капчу, тул
лише ще раз чекає результат на тій самій сторінці, не перезаповнюючи форму.
"""
from __future__ import annotations

import time
from typing import Callable

import config
from core import db
from core.filler import TransientError, fill_form, read_result


def _process_job(page, job, fill_fn, read_fn) -> None:
    """Заповнити форму один раз, потім дочекатись результату (з повтором лише
    читання на тій самій сторінці). Будь-яка несподівана помилка -> failed з
    причиною, щоб один збій не вбивав увесь батч."""
    # 1) Заповнення - один раз.
    try:
        fill_fn(page, job)
    except TransientError as exc:
        db.update_job(job.id, status=db.FAILED,
                      error=str(exc), attempts=job.attempts + 1)
        return
    except Exception as exc:  # noqa: BLE001
        db.update_job(job.id, status=db.FAILED,
                      error=f"несподівана помилка заповнення: {exc}",
                      attempts=job.attempts + 1)
        return

    # 2) Читання результату - на ТІЙ САМІЙ сторінці, з backoff лише на таймаут.
    attempts = job.attempts
    delay = 2.0
    while attempts < config.MAX_ATTEMPTS:
        attempts += 1
        try:
            result = read_fn(page)
        except TransientError as exc:
            if attempts < config.MAX_ATTEMPTS:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            db.update_job(job.id, status=db.FAILED, error=str(exc), attempts=attempts)
            return
        except Exception as exc:  # noqa: BLE001
            db.update_job(job.id, status=db.FAILED,
                          error=f"несподівана помилка читання: {exc}", attempts=attempts)
            return

        if result.status == "sent":
            db.update_job(job.id, status=db.SENT,
                          confirmation_code=result.confirmation_code, attempts=attempts)
        elif result.status == "sent_unverified":
            db.update_job(job.id, status=db.SENT_UNVERIFIED,
                          error=f"відправлено, код не розпізнано: {result.raw}",
                          attempts=attempts)
        else:
            db.update_job(job.id, status=db.FAILED, error=result.error, attempts=attempts)
        return


def process_batch(batch_id: str, browser_factory: Callable | None = None,
                  fill_fn: Callable | None = None, read_fn: Callable | None = None,
                  log: Callable[[str], None] = print) -> dict:
    """Пройти всі задачі батчу, що ще потребують відправки.

    browser_factory, fill_fn, read_fn - для тестів можна підставити фейкові.
    У бою використовується Playwright і filler.fill_form / filler.read_result.
    """
    jobs = db.jobs_to_process(batch_id)
    if not jobs:
        log("Немає задач на відправку (усі вже подані або батч порожній).")
        return {"processed": 0, "sent": 0, "sent_unverified": 0, "failed": 0}

    factory = browser_factory or _default_browser
    do_fill = fill_fn or fill_form
    do_read = read_fn or read_result

    try:
        with factory() as ctx:
            for i, job in enumerate(jobs):
                if i > 0:
                    time.sleep(config.RATE_LIMIT_SECONDS)
                page = ctx.new_page()
                log(f"[{i + 1}/{len(jobs)}] {job.target}: заповнюю, чекаю на людину (капча + Submit)")
                _process_job(page, job, do_fill, do_read)
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        # Збій рівня браузера/контексту (не стартував chromium, закрито вікно тощо).
        # Позначаємо ще не чіпані рядки, щоб батч не вмер мовчки.
        log(f"Збій браузера: {exc}")
        for job in db.pending_jobs(batch_id):
            db.update_job(job.id, status=db.FAILED,
                          error=f"збій браузера: {exc}", attempts=job.attempts + 1)

    fresh = db.get_jobs(batch_id)
    done = {j.id for j in jobs}
    sent = sum(1 for j in fresh if j.id in done and j.status == db.SENT)
    unverified = sum(1 for j in fresh if j.id in done and j.status == db.SENT_UNVERIFIED)
    failed = sum(1 for j in fresh if j.id in done and j.status == db.FAILED)
    for j in fresh:
        if j.id in done and j.status == db.SENT:
            log(f"    ok: {j.confirmation_code}")
        elif j.id in done and j.status == db.SENT_UNVERIFIED:
            log(f"    відправлено, код не розпізнано")
        elif j.id in done and j.status == db.FAILED:
            log(f"    збій: {j.error}")
    return {"processed": len(jobs), "sent": sent,
            "sent_unverified": unverified, "failed": failed}


class _PlaywrightContext:
    """Обгортка, щоб у process_batch був один простий інтерфейс: new_page()."""

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=config.HEADLESS)
        self._context = self._browser.new_context()
        return self._context

    def __exit__(self, *exc):
        try:
            self._context.close()
            self._browser.close()
        finally:
            self._pw.stop()
        return False


def _default_browser():
    return _PlaywrightContext()


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Використання: python -m core.runner <batch_id>")
        raise SystemExit(1)
    db.init_db()
    summary = process_batch(sys.argv[1])
    print(f"Готово: відправлено {summary['sent']}, "
          f"без коду {summary['sent_unverified']}, збоїв {summary['failed']}")
