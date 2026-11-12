"""Тести черги: масовість, ідемпотентність, статуси, повтор.

Браузер, заповнення і читання підставлені фейками (fill_fn/read_fn), тож тест
перевіряє саме логіку черги, а не Playwright.
"""
import config
from core import db
from core import runner
from core.filler import FillResult, TransientError


class _FakePage:
    def close(self):
        pass


class _FakeCtx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def new_page(self):
        return _FakePage()


def _factory():
    return _FakeCtx()


def _ok_fill(page, job):
    return None


def _setup(tmp_path):
    config.DB_PATH = tmp_path / "test.db"
    config.RATE_LIMIT_SECONDS = 0
    config.MAX_ATTEMPTS = 3
    db.init_db()


def test_mass_one_job_per_target(tmp_path):
    _setup(tmp_path)
    added = db.add_jobs("b1", ["example.com", "example.net", "example.com"],
                        "Domain", "spam", "reason", "")
    assert added == 2  # дубль не додався

    s = runner.process_batch(
        "b1", browser_factory=_factory, fill_fn=_ok_fill,
        read_fn=lambda p: FillResult(status="sent", confirmation_code="CF-ABCD1234"),
        log=lambda m: None)
    assert s == {"processed": 2, "sent": 2, "sent_unverified": 0, "failed": 0}
    assert all(j.status == db.SENT for j in db.get_jobs("b1"))


def test_sent_not_reprocessed(tmp_path):
    _setup(tmp_path)
    db.add_jobs("b2", ["example.com"], "Domain", "spam", "reason", "")
    runner.process_batch(
        "b2", browser_factory=_factory, fill_fn=_ok_fill,
        read_fn=lambda p: FillResult(status="sent", confirmation_code="CF-11111111"),
        log=lambda m: None)
    s = runner.process_batch(
        "b2", browser_factory=_factory, fill_fn=_ok_fill,
        read_fn=lambda p: FillResult(status="sent", confirmation_code="CF-22222222"),
        log=lambda m: None)
    assert s["processed"] == 0
    assert db.get_jobs("b2")[0].confirmation_code == "CF-11111111"


def test_form_error_then_retry(tmp_path):
    _setup(tmp_path)
    db.add_jobs("b3", ["example.com"], "Domain", "spam", "reason", "")
    runner.process_batch(
        "b3", browser_factory=_factory, fill_fn=_ok_fill,
        read_fn=lambda p: FillResult(status="error", error="форма повернула помилку"),
        log=lambda m: None)
    assert db.get_jobs("b3")[0].status == db.FAILED

    assert db.reset_failed_to_pending("b3") == 1
    runner.process_batch(
        "b3", browser_factory=_factory, fill_fn=_ok_fill,
        read_fn=lambda p: FillResult(status="sent", confirmation_code="CF-OK000001"),
        log=lambda m: None)
    assert db.get_jobs("b3")[0].status == db.SENT


def test_sent_unverified_not_reprocessed(tmp_path):
    """Форму подано, але код не розпізнано: статус sent_unverified і повторно НЕ
    надсилається (щоб не подати скаргу двічі)."""
    _setup(tmp_path)
    db.add_jobs("b4", ["example.com"], "Domain", "spam", "reason", "")
    s = runner.process_batch(
        "b4", browser_factory=_factory, fill_fn=_ok_fill,
        read_fn=lambda p: FillResult(status="sent_unverified", raw="Thank you, ref cf-xyz"),
        log=lambda m: None)
    assert s["sent_unverified"] == 1
    assert db.get_jobs("b4")[0].status == db.SENT_UNVERIFIED

    s2 = runner.process_batch(
        "b4", browser_factory=_factory, fill_fn=_ok_fill,
        read_fn=lambda p: FillResult(status="sent", confirmation_code="CF-SHOULD00"),
        log=lambda m: None)
    assert s2["processed"] == 0
    assert db.get_jobs("b4")[0].status == db.SENT_UNVERIFIED


def test_timeout_exhausts_then_reset_retry(tmp_path, monkeypatch):
    _setup(tmp_path)
    config.MAX_ATTEMPTS = 2
    monkeypatch.setattr(runner.time, "sleep", lambda *a: None)
    db.add_jobs("b5", ["example.com"], "Domain", "spam", "reason", "")

    def timeout_read(p):
        raise TransientError("не дочекались результату")

    runner.process_batch("b5", browser_factory=_factory, fill_fn=_ok_fill,
                         read_fn=timeout_read, log=lambda m: None)
    job = db.get_jobs("b5")[0]
    assert job.status == db.FAILED and job.attempts == 2

    # "Почати обробку" знову НЕ бере вичерпаний рядок (attempts >= MAX).
    s = runner.process_batch("b5", browser_factory=_factory, fill_fn=_ok_fill,
                             read_fn=timeout_read, log=lambda m: None)
    assert s["processed"] == 0

    # Після явного скидання - бере і проходить.
    db.reset_failed_to_pending("b5")
    runner.process_batch(
        "b5", browser_factory=_factory, fill_fn=_ok_fill,
        read_fn=lambda p: FillResult(status="sent", confirmation_code="CF-RETRY001"),
        log=lambda m: None)
    assert db.get_jobs("b5")[0].status == db.SENT


def test_fill_failure_marks_failed_not_crash(tmp_path):
    _setup(tmp_path)
    db.add_jobs("b6", ["example.com"], "Domain", "spam", "reason", "")

    def bad_fill(page, job):
        raise TransientError("форма не відкрилась")

    runner.process_batch(
        "b6", browser_factory=_factory, fill_fn=bad_fill,
        read_fn=lambda p: FillResult(status="sent", confirmation_code="CF-NONE0000"),
        log=lambda m: None)
    assert db.get_jobs("b6")[0].status == db.FAILED


def test_browser_launch_failure_marks_pending_failed(tmp_path):
    """Якщо браузер не стартував, батч не вмирає мовчки: рядки стають failed."""
    _setup(tmp_path)
    db.add_jobs("b7", ["example.com", "example.net"], "Domain", "spam", "reason", "")

    class _BrokenCtx:
        def __enter__(self):
            raise RuntimeError("chromium не стартував")

        def __exit__(self, *exc):
            return False

    s = runner.process_batch("b7", browser_factory=lambda: _BrokenCtx(),
                             fill_fn=_ok_fill,
                             read_fn=lambda p: FillResult(status="sent", confirmation_code="CF-X0000000"),
                             log=lambda m: None)
    assert s["failed"] == 2
    assert all(j.status == db.FAILED for j in db.get_jobs("b7"))
