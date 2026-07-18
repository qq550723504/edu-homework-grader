FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

EXPOSE 8010
CMD ["uvicorn", "edu_grader.main:app", "--host", "0.0.0.0", "--port", "8010"]
