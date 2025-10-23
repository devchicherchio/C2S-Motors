# Imagem base
FROM python:3.12-slim

# Evita cache e escrita de .pyc
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Instala dependências do sistema (para psycopg2 etc.)
RUN apt-get update && apt-get install -y build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

# Define pasta de trabalho
WORKDIR /app

# Copia requirements e instala dependências Python dentro do container
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copia todo o projeto
COPY . /app/

# Expõe a porta padrão
EXPOSE 8000

# Comando padrão: aplica migrações e sobe o servidor Django
CMD bash -lc "python manage.py migrate && uvicorn c2s_motors.asgi:application --host 0.0.0.0 --port 8000 --reload"
