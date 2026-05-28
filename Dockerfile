FROM python:3.11-slim

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# 升級 pip + setuptools 避免舊版 build-backend 問題
RUN pip install --upgrade pip setuptools

# 先複製依賴定義，利用 Docker layer cache
COPY requirements.txt pyproject.toml ./

# 安裝依賴
RUN pip install --no-cache-dir -r requirements.txt

# 複製全部程式碼
COPY . ./autotrading/

# 以 editable 方式安裝 package (讓 relative import 正常運作)
RUN pip install --no-cache-dir -e ./autotrading/

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

CMD ["python", "-m", "autotrading.backend.server"]
