FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RECEIPTS_MODE=production \
    RECEIPTS_DATABASE_PATH=/data/receipts.db

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt \
    && useradd --system --create-home --uid 10001 receipts \
    && mkdir -p /data \
    && chown receipts:receipts /data
COPY app ./app

USER receipts
EXPOSE 8099
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8099"]
