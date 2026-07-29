import os
import subprocess
import sys
from pathlib import Path


def test_offline_alembic_migrations_accept_a_percent_encoded_database_url() -> None:
    api_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+psycopg://edu_grader:encoded%2Fpassword@postgres:5432/edu_grader"
    )

    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "0001", "--sql"],
        cwd=api_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "invalid interpolation syntax" not in completed.stderr
