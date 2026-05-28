FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN ln -sf /app /app/AutoTrading
CMD uvicorn AutoTrading.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
