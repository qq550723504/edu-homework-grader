FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY packages/processor-policy /tmp/processor-policy
COPY services/grader/pyproject.toml ./
COPY services/grader/src ./src
RUN python -m pip install --no-cache-dir /tmp/processor-policy .

EXPOSE 8010
CMD ["uvicorn", "edu_grader.main:app", "--host", "0.0.0.0", "--port", "8010"]
