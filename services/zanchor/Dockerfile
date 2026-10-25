FROM python:3.12-slim

WORKDIR /svc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN useradd -m svc && mkdir -p /svc/data && chown -R svc /svc
USER svc

ENV ZANCHOR_DB=/svc/data/zanchor.db
EXPOSE 8092
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8092"]
