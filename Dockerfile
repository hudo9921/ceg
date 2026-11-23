# --- Estágio 1: compila o Tailwind (Node só existe neste estágio) -------------------
FROM node:20-alpine AS css
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tailwind.config.js ./
COPY static/src ./static/src
COPY templates ./templates
COPY apps ./apps
RUN npm run build:css

# --- Estágio 2: aplicação Django --------------------------------------------------
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

# Copia a aplicação e o CSS compilado no estágio 1
COPY . /app/
COPY --from=css /build/static/css/tailwind.css /app/static/css/tailwind.css

# Garante permissão de execução no entrypoint
RUN chmod +x /app/entrypoint.sh

# Coleta arquivos estáticos
# Valores descartáveis só para o build: o .env real não entra na imagem (.dockerignore).
RUN DEBUG=True TAILWIND_MODE=build SECRET_KEY=build-only-collectstatic python manage.py collectstatic --no-input

# Roda sem root: uma falha na aplicação não vira controle total do container.
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
