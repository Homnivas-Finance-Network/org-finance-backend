FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT at runtime — do not hardcode 8080 in code, only here as a default
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
