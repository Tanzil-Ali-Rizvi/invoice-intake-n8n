FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 INTAKE_DB=/data/intake.db
COPY service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -m intake && mkdir /data && chown intake /data
COPY service/intake ./service/intake
COPY prompts ./prompts
COPY dataset/truth.json ./dataset/truth.json
USER intake
WORKDIR /app/service
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "intake.api:app", "--host", "0.0.0.0", "--port", "8000"]
