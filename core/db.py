"""Стан у SQLite. Одна таблиця задач. Стан переживає перезапуск тули.

Ключова деталь для ідемпотентності: UNIQUE(batch_id, target). У межах одного
батчу та сама ціль не заводиться двічі. Разом з перевіркою статусу перед
відправкою (див. runner) це не дає відправити ту саму скаргу повторно.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import config

# Статуси задачі.
PENDING = "pending"                  # ще не відправлено
SENT = "sent"                        # відправлено, є код підтвердження
SENT_UNVERIFIED = "sent_unverified"  # відправлено, код не розпізнано (НЕ повторювати)
FAILED = "failed"                    # помилка, можна повторити
SKIPPED = "skipped"                  # пропущено (вже було відправлено раніше)

# Статуси, які означають "вже подано на сервер": їх НІКОЛИ не повторюємо,
# бо скарга - юридичне твердження, і подати її двічі не можна.
SUBMITTED = (SENT, SENT_UNVERIFIED)


@dataclass
class Job:
    id: int
    batch_id: str
    target: str
    submission_type: str
    threat_type: str
    reason: str
    file_path: str
    status: str
    confirmation_code: str
    error: str
    attempts: int


def _connect() -> sqlite3.Connection:
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    # closing закриває зʼєднання, внутрішній `with conn` робить commit.
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                target TEXT NOT NULL,
                submission_type TEXT NOT NULL,
                threat_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                file_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                confirmation_code TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(batch_id, target)
            )
            """
        )


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"], batch_id=row["batch_id"], target=row["target"],
        submission_type=row["submission_type"], threat_type=row["threat_type"],
        reason=row["reason"], file_path=row["file_path"], status=row["status"],
        confirmation_code=row["confirmation_code"], error=row["error"],
        attempts=row["attempts"],
    )


def add_jobs(batch_id: str, targets: list[str], submission_type: str,
             threat_type: str, reason: str, file_path: str) -> int:
    """Заводить по задачі на ціль. Дублі в межах батчу тихо ігноруються
    (UNIQUE). Повертає, скільки задач реально додано."""
    now = time.time()
    added = 0
    with closing(_connect()) as conn, conn:
        for target in targets:
            try:
                conn.execute(
                    """INSERT INTO jobs (batch_id, target, submission_type,
                       threat_type, reason, file_path, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (batch_id, target, submission_type, threat_type, reason,
                     file_path, now, now),
                )
                added += 1
            except sqlite3.IntegrityError:
                continue  # та сама ціль у цьому батчі вже є
    return added


def get_jobs(batch_id: str) -> list[Job]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE batch_id = ? ORDER BY id", (batch_id,)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def pending_jobs(batch_id: str) -> list[Job]:
    """Лише ще не чіпані рядки (pending)."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE batch_id = ? AND status = ? ORDER BY id",
            (batch_id, PENDING),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def jobs_to_process(batch_id: str) -> list[Job]:
    """Задачі, які ще треба відправити: pending, або failed, що ще НЕ вичерпали
    спроби. Уже подані (sent / sent_unverified) не чіпаємо (ідемпотентність), а
    failed з вичерпаними спробами беруться лише після явного скидання
    (reset_failed_to_pending), щоб не відкривати порожню вкладку даремно."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE batch_id = ? AND "
            "(status = ? OR (status = ? AND attempts < ?)) ORDER BY id",
            (batch_id, PENDING, FAILED, config.MAX_ATTEMPTS),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def update_job(job_id: int, *, status: str, confirmation_code: str = "",
               error: str = "", attempts: int | None = None) -> None:
    with closing(_connect()) as conn, conn:
        if attempts is None:
            conn.execute(
                """UPDATE jobs SET status=?, confirmation_code=?, error=?,
                   updated_at=? WHERE id=?""",
                (status, confirmation_code, error, time.time(), job_id),
            )
        else:
            conn.execute(
                """UPDATE jobs SET status=?, confirmation_code=?, error=?,
                   attempts=?, updated_at=? WHERE id=?""",
                (status, confirmation_code, error, attempts, time.time(), job_id),
            )


def reset_failed_to_pending(batch_id: str) -> int:
    """Повернути всі failed у pending, щоб повторити. Лічильник спроб скидаємо
    на 0, інакше рядок, що вичерпав MAX_ATTEMPTS, не піде на повтор. Уже подані
    рядки (sent / sent_unverified) не чіпаємо. Повертає кількість повернених."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE jobs SET status=?, error='', attempts=0, updated_at=? "
            "WHERE batch_id=? AND status=?",
            (PENDING, time.time(), batch_id, FAILED),
        )
        return cur.rowcount
