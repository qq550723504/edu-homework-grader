from email.message import EmailMessage
from typing import Self

import pytest

from edu_grader_api.cli import production_alert as alert


class RecordingSmtp:
    def __init__(self) -> None:
        self.logged_in: tuple[str, str] | None = None
        self.message: EmailMessage | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def login(self, sender: str, authorization_code: str) -> None:
        self.logged_in = (sender, authorization_code)

    def send_message(self, message: EmailMessage) -> None:
        self.message = message


@pytest.fixture(autouse=True)
def alert_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALERT_PUBLIC_URL", "https://public.example.test/")
    monkeypatch.setenv("ALERT_API_URL", "http://api.example.test/infrastructure-ready")
    monkeypatch.setenv("ALERT_GRADER_URL", "http://grader.example.test/health")
    monkeypatch.setenv("ALERT_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("ALERT_SMTP_PORT", "465")
    monkeypatch.setenv("ALERT_SMTP_SENDER", "operator@example.test")
    monkeypatch.setenv("ALERT_SMTP_RECIPIENT", "recipient@example.test")
    monkeypatch.setenv("ALERT_SMTP_AUTH_CODE", "test-only-authorization-code")


def test_healthy_checks_do_not_open_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alert, "check_http", lambda _name, _url: None)
    monkeypatch.setattr(alert, "check_database", lambda: None)

    def fail_if_called(*_args: object, **_kwargs: object) -> RecordingSmtp:
        raise AssertionError("SMTP must not be contacted for a healthy alert run")

    monkeypatch.setattr(alert.smtplib, "SMTP_SSL", fail_if_called)

    assert alert.run() == 0


def test_requested_delivery_test_sends_email_after_healthy_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smtp = RecordingSmtp()
    monkeypatch.setenv("ALERT_TEST_NOTIFICATION", "true")
    monkeypatch.setattr(alert, "check_http", lambda _name, _url: None)
    monkeypatch.setattr(alert, "check_database", lambda: None)
    monkeypatch.setattr(alert.smtplib, "SMTP_SSL", lambda *_args, **_kwargs: smtp)

    assert alert.run() == 0
    assert smtp.message is not None
    assert smtp.message["Subject"] == "Production alert test"
    assert "test requested" in smtp.message.get_content()


def test_http_check_rejects_non_success_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnavailableResponse:
        status = 503

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(alert, "urlopen", lambda *_args, **_kwargs: UnavailableResponse())

    with pytest.raises(RuntimeError, match="grader returned HTTP 503"):
        alert.check_http("grader", "http://grader.example.test/health")


def test_database_check_executes_only_select_one(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[str] = []

    class Connection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object) -> None:
            executed.append(str(statement))

    class Engine:
        def connect(self) -> Connection:
            return Connection()

    monkeypatch.setattr(alert, "engine", Engine())

    alert.check_database()

    assert executed == ["SELECT 1"]


def test_failed_check_sends_redacted_email_and_returns_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_api(name: str, _url: str) -> None:
        if name == "api":
            raise OSError("connection refused")

    smtp = RecordingSmtp()
    monkeypatch.setattr(alert, "check_http", fail_api)
    monkeypatch.setattr(alert, "check_database", lambda: None)
    monkeypatch.setattr(alert.smtplib, "SMTP_SSL", lambda *_args, **_kwargs: smtp)

    assert alert.run() == 1
    assert smtp.logged_in == ("operator@example.test", "test-only-authorization-code")
    assert smtp.message is not None
    assert smtp.message["Subject"] == "Production alert: api"
    body = smtp.message.get_content()
    assert "api" in body
    assert "postgresql://" not in body
    assert "test-only-authorization-code" not in body
    assert "connection refused" not in body
