"""Веб-інтерфейс тули.

Оператор вводить дані (тип, список цілей, Threat Type, Reason, файл-доказ),
тул заводить по задачі на ціль у чергу і показує результат по кожному рядку
з кодом підтвердження або причиною помилки; невдалі можна повторити.

Запуск: python app.py (потім відкрити http://127.0.0.1:5000/).

Сама відправка форми (обробка батчу) відкриває вікно браузера, де людина
вирішує капчу і тисне Submit. Обхід капчі в тулі свідомо не реалізований.
"""
from __future__ import annotations

import secrets
import string
import threading
import uuid
from pathlib import Path

from flask import (Flask, redirect, render_template, request, url_for)

import config
from core import db, validation
from core.runner import process_batch

app = Flask(__name__)

# Які батчі зараз обробляються (щоб не запустити двічі одночасно).
_running: set[str] = set()
_running_lock = threading.Lock()


def _new_confirmation_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "CF-" + "".join(secrets.choice(alphabet) for _ in range(8))


@app.route("/")
def index():
    return render_template("index.html",
                           submission_types=config.ALLOWED_SUBMISSION_TYPES)


@app.route("/submit", methods=["POST"])
def submit():
    submission_type = request.form.get("submission_type", "").strip()
    raw_targets = request.form.get("targets", "")
    threat_type = request.form.get("threat_type", "").strip()
    reason = request.form.get("reason", "").strip()
    upload = request.files.get("evidence")

    targets = validation.parse_targets(raw_targets, submission_type)
    errors = validation.validate_batch(submission_type, targets, threat_type, reason)

    # Перевірка файлу (тип і розмір). Файл обовʼязковий за умовою форми.
    file_path = ""
    if upload and upload.filename:
        upload.stream.seek(0, 2)
        size = upload.stream.tell()
        upload.stream.seek(0)
        check = validation.validate_file(upload.filename, size)
        if not check.ok:
            errors.append(check.reason)
        else:
            Path(config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
            ext = validation.file_extension(upload.filename)
            file_path = str(config.UPLOAD_DIR / f"{uuid.uuid4().hex}.{ext}")
            upload.save(file_path)
    else:
        errors.append("Не додано файл-доказ")

    if errors:
        return render_template("index.html",
                               submission_types=config.ALLOWED_SUBMISSION_TYPES,
                               errors=errors,
                               form={"submission_type": submission_type,
                                     "targets": raw_targets,
                                     "threat_type": threat_type,
                                     "reason": reason}), 400

    db.init_db()
    batch_id = uuid.uuid4().hex[:12]
    db.add_jobs(batch_id, targets, submission_type, threat_type, reason, file_path)
    return redirect(url_for("results", batch_id=batch_id))


@app.route("/results/<batch_id>")
def results(batch_id: str):
    jobs = db.get_jobs(batch_id)
    if not jobs:
        return redirect(url_for("index"))
    with _running_lock:
        running = batch_id in _running
    return render_template("results.html", batch_id=batch_id, jobs=jobs,
                           running=running)


def _run_batch(batch_id: str) -> None:
    try:
        process_batch(batch_id)
    except Exception as exc:  # noqa: BLE001 - остання лінія захисту фонового потоку
        print(f"process_batch впав: {exc}")
    finally:
        with _running_lock:
            _running.discard(batch_id)


@app.route("/process/<batch_id>", methods=["POST"])
def process(batch_id: str):
    with _running_lock:
        if batch_id not in _running:
            _running.add(batch_id)
            threading.Thread(target=_run_batch, args=(batch_id,), daemon=True).start()
    return redirect(url_for("results", batch_id=batch_id))


@app.route("/retry/<batch_id>", methods=["POST"])
def retry(batch_id: str):
    db.reset_failed_to_pending(batch_id)
    return redirect(url_for("results", batch_id=batch_id))


# --- Локальний макет форми (щоб перевіряти тул без реального сервера) ---
# Поля збігаються з селекторами у config.FORM_FIELDS. "Капча" тут умовна:
# її заповнює людина, як і на справжній формі. Порожня капча = помилка.
@app.route("/mock-form", methods=["GET"])
def mock_form():
    return render_template("mock_form.html")


@app.route("/mock-form", methods=["POST"])
def mock_form_submit():
    if not request.form.get("captcha", "").strip():
        return render_template("mock_result.html",
                               error="Капчу не пройдено"), 200
    return render_template("mock_result.html", code=_new_confirmation_code())


if __name__ == "__main__":
    db.init_db()
    app.run(host=config.HOST, port=config.PORT, debug=False)
