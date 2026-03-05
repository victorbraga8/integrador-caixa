FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates     wget     gnupg     libnss3     libatk1.0-0     libatk-bridge2.0-0     libcups2     libdrm2     libxkbcommon0     libxcomposite1     libxdamage1     libxfixes3     libxrandr2     libgbm1     libasound2     libpangocairo-1.0-0     libpango-1.0-0     libgtk-3-0     libxshmfence1     libxss1     libxtst6     libglib2.0-0     libdbus-1-3     fonts-liberation   && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -m playwright install --with-deps chromium

COPY app ./app

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
