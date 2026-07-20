FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY packages/processor-policy /tmp/processor-policy
COPY services/grader/pyproject.toml ./
COPY services/grader/src ./src
COPY services/grader/scripts ./scripts
RUN python -m pip install --no-cache-dir /tmp/processor-policy .

ARG ENGLISH_EMBEDDING_MODEL_ID=sentence-transformers/all-MiniLM-L6-v2
ARG ENGLISH_EMBEDDING_MODEL_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
ARG ENGLISH_EMBEDDING_MODEL_DIGEST=sha256:84714cdabb16d132cbe6e1a4cbd21167abd09eccbdaf69dd053136ae68cc7c17
ENV ENGLISH_EMBEDDING_MODEL_DIRECTORY=/opt/english-model \
    ENGLISH_EMBEDDING_MODEL_ID=${ENGLISH_EMBEDDING_MODEL_ID} \
    ENGLISH_EMBEDDING_MODEL_REVISION=${ENGLISH_EMBEDDING_MODEL_REVISION} \
    ENGLISH_EMBEDDING_MODEL_DIGEST=${ENGLISH_EMBEDDING_MODEL_DIGEST}
RUN python scripts/prefetch_english_model.py \
    --model-id "$ENGLISH_EMBEDDING_MODEL_ID" \
    --revision "$ENGLISH_EMBEDDING_MODEL_REVISION" \
    --expected-digest "$ENGLISH_EMBEDDING_MODEL_DIGEST" \
    --output "$ENGLISH_EMBEDDING_MODEL_DIRECTORY"

EXPOSE 8010
CMD ["uvicorn", "edu_grader.main:app", "--host", "0.0.0.0", "--port", "8010"]
