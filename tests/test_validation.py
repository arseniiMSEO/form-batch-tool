"""Тести валідації: детерміновані, без мережі і браузера."""
import config
from core import validation


def test_parse_targets_strips_empties_and_dupes():
    raw = "example.com\n  example.net \n\nEXAMPLE.COM\n203.0.113.10\n"
    assert validation.parse_targets(raw) == [
        "example.com", "example.net", "203.0.113.10",
    ]


def test_parse_targets_empty():
    assert validation.parse_targets("\n  \n") == []


def test_validate_file_good():
    assert validation.validate_file("evidence.png", 1024).ok


def test_validate_file_bad_ext():
    res = validation.validate_file("evidence.gif", 1024)
    assert not res.ok and "Недозволений" in res.reason


def test_validate_file_too_big():
    res = validation.validate_file("evidence.pdf", config.MAX_FILE_BYTES + 1)
    assert not res.ok and "більший" in res.reason


def test_validate_file_empty():
    assert not validation.validate_file("evidence.pdf", 0).ok


def test_validate_batch_collects_errors():
    errors = validation.validate_batch("Wrong", [], "", "")
    assert len(errors) == 4


def test_parse_targets_domain_case_insensitive():
    # Для доменів регістр не важливий: дублі склеюються.
    assert validation.parse_targets("EXAMPLE.COM\nexample.com", "Domain") == ["EXAMPLE.COM"]


def test_parse_targets_url_case_sensitive():
    # Для URL шлях чутливий до регістру: це РІЗНІ цілі, не склеювати.
    raw = "http://x.com/A\nhttp://x.com/a"
    assert validation.parse_targets(raw, "URL") == ["http://x.com/A", "http://x.com/a"]
