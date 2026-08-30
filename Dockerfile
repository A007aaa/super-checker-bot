FROM python:3.11.9-slim

# Evita buffering em logs e acelera pip
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# Instala dependências do sistema necessárias para builds Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential gcc libffi-dev libgmp-dev git curl && \
    rm -rf /var/lib/apt/lists/*

# Copia apenas arquivos de dependências para usar cache de layer
COPY requirements.txt . 2>/dev/null || true
COPY pyproject.toml poetry.lock* . 2>/dev/null || true

# Instala dependências: pip se requirements.txt existir, senão Poetry se pyproject.toml existir
RUN if [ -f "./requirements.txt" ]; then \
        python -m pip install --upgrade pip && \
        pip install -r requirements.txt; \
    elif [ -f "./pyproject.toml" ]; then \
        python -m pip install --upgrade pip && \
        pip install poetry && \
        poetry install --no-dev --no-interaction; \
    else \
        echo "Nenhum arquivo requirements.txt ou pyproject.toml encontrado — nenhuma dependência será instalada"; \
    fi

# Copia todo o código
COPY . .

# Exponha porta se necessário (não obrigatório para polling)
# EXPOSE 8080

# Comando padrão para iniciar seu bot
CMD ["python", "main.py"]
