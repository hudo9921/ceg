FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências nativas
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia a aplicação
COPY . /app/

# Garante permissão de execução no entrypoint
RUN chmod +x /app/entrypoint.sh

# Coleta arquivos estáticos
# Valores descartáveis só para o build: o .env real não entra na imagem (.dockerignore).
RUN DEBUG=True SECRET_KEY=build-only-collectstatic python manage.py collectstatic --no-input

# Roda sem root: uma falha na aplicação não vira controle total do container.
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
