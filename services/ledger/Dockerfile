FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# The SQLite application copy lives here; Fly mounts a volume over it.
RUN mkdir -p /data

ENV DATABASE_PATH=/data/ledger.db \
    PYTHONUNBUFFERED=1

EXPOSE 8088

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
