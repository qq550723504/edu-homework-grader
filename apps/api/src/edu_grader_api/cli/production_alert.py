import os
import smtplib
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..db import engine


def environment_value(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be configured")
    return value


def check_http(name: str, url: str) -> None:
    with urlopen(url, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"{name} returned HTTP {response.status}")


def check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def send_email(subject: str, body: str) -> None:
    sender = environment_value("ALERT_SMTP_SENDER")
    recipient = environment_value("ALERT_SMTP_RECIPIENT")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP_SSL(
        environment_value("ALERT_SMTP_HOST"),
        int(environment_value("ALERT_SMTP_PORT")),
        timeout=10,
    ) as smtp:
        smtp.login(sender, environment_value("ALERT_SMTP_AUTH_CODE"))
        smtp.send_message(message)


def send_failure_email(failures: list[str]) -> None:
    send_email(
        f"Production alert: {', '.join(failures)}",
        f"Failed checks: {', '.join(failures)}",
    )


def test_notification_requested() -> bool:
    return os.environ.get("ALERT_TEST_NOTIFICATION", "").casefold() == "true"


def run() -> int:
    failures: list[str] = []
    for name, variable_name in (
        ("public", "ALERT_PUBLIC_URL"),
        ("api", "ALERT_API_URL"),
        ("grader", "ALERT_GRADER_URL"),
    ):
        try:
            check_http(name, environment_value(variable_name))
        except (HTTPError, OSError, RuntimeError, URLError, ValueError):
            failures.append(name)
    try:
        check_database()
    except (SQLAlchemyError, OSError, RuntimeError):
        failures.append("postgres")

    if not failures:
        if test_notification_requested():
            send_email("Production alert test", "Availability checks passed; test requested.")
        return 0
    send_failure_email(failures)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
