FROM python:3.10-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-async.txt ./
# requirements.txt is UTF-16 and contains a Windows-only terminal dependency.
RUN pip install --no-cache-dir --upgrade pip && \
    python -c "from pathlib import Path; p=Path('requirements.txt'); p.write_text('\n'.join(line for line in p.read_text(encoding='utf-16').splitlines() if not line.startswith('pywinpty==')) + '\n', encoding='utf-8')" && \
    pip install --no-cache-dir -r requirements.txt -r requirements-async.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    FLASK_ENV=production

EXPOSE 5000

CMD ["python", "app.py"]
