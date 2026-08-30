FROM python:3.11-slim-bookworm

# Dependências de sistema para pynacl / coincurve / bip-utils
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala deps primeiro (melhor cache de camada)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Código da aplicação
COPY . .

# Railway injeta PORT; o main.py sobe health check nessa porta
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

CMD ["python", "main.py"]
