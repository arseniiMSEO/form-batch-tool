"""Тести розбору результату форми (filler.read_result) на фейковому page,
без Playwright. Саме ця логіка (код CF або причина по рядку) - серце ТЗ."""
import config
from core.filler import read_result, TransientError


class _El:
    def __init__(self, text):
        self._t = text

    def inner_text(self):
        return self._t


class _Page:
    """Фейк сторінки: віддає елемент коду (conf) і/або помилки (err)."""

    def __init__(self, conf=None, err=None, wait_raises=False):
        self._conf = conf
        self._err = err
        self._wait_raises = wait_raises

    def wait_for_selector(self, selector, timeout=None):
        if self._wait_raises:
            raise RuntimeError("timeout")
        return True

    def query_selector(self, selector):
        if selector == config.FORM_FIELDS["error"]:
            return _El(self._err) if self._err is not None else None
        if selector == config.FORM_FIELDS["confirmation_code"]:
            return _El(self._conf) if self._conf is not None else None
        return None


def test_success_code():
    r = read_result(_Page(conf="Ваш код CF-ABCD1234"))
    assert r.status == "sent" and r.confirmation_code == "CF-ABCD1234"


def test_nonempty_error():
    r = read_result(_Page(err="Невірні дані форми"))
    assert r.status == "error" and "Невірні" in r.error


def test_empty_error_container_is_not_error():
    # Порожній контейнер помилки присутній, але код валідний: це sent, не error.
    r = read_result(_Page(conf="CF-ZZ999999", err="   "))
    assert r.status == "sent" and r.confirmation_code == "CF-ZZ999999"


def test_submitted_but_code_unrecognized():
    # Форму відправлено (елемент результату є), але код іншого формату/регістру:
    # sent_unverified, а не error, і НЕ привід слати вдруге.
    r = read_result(_Page(conf="Thank you, reference cf-1234abcd"))
    assert r.status == "sent_unverified" and "cf-1234abcd" in r.raw


def test_timeout_is_transient():
    try:
        read_result(_Page(wait_raises=True))
    except TransientError:
        return
    assert False, "мав кинути TransientError"
