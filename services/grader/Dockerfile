FROM python:3.13-slim AS model

WORKDIR /app
COPY packages/processor-policy /tmp/processor-policy
COPY services/grader/pyproject.toml ./
RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu
RUN printf 'torch==2.13.0+cpu\n' > /tmp/torch-constraints.txt \
    && PIP_CONSTRAINT=/tmp/torch-constraints.txt python -c "import subprocess, sys, tomllib; dependencies = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '/tmp/processor-policy', *dependencies])"

COPY services/grader/scripts ./scripts

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

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=model /usr/local /usr/local
COPY --from=model /opt/english-model /opt/english-model
COPY services/grader/pyproject.toml ./
COPY services/grader/src ./src
RUN python -m pip install --no-deps .

ARG ENGLISH_EMBEDDING_MODEL_ID=sentence-transformers/all-MiniLM-L6-v2
ARG ENGLISH_EMBEDDING_MODEL_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
ARG ENGLISH_EMBEDDING_MODEL_DIGEST=sha256:84714cdabb16d132cbe6e1a4cbd21167abd09eccbdaf69dd053136ae68cc7c17
ENV ENGLISH_EMBEDDING_MODEL_DIRECTORY=/opt/english-model \
    ENGLISH_EMBEDDING_MODEL_ID=${ENGLISH_EMBEDDING_MODEL_ID} \
    ENGLISH_EMBEDDING_MODEL_REVISION=${ENGLISH_EMBEDDING_MODEL_REVISION} \
    ENGLISH_EMBEDDING_MODEL_DIGEST=${ENGLISH_EMBEDDING_MODEL_DIGEST}

EXPOSE 8010
CMD ["uvicorn", "edu_grader.main:app", "--host", "0.0.0.0", "--port", "8010"]
