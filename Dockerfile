FROM python:3.12-slim

LABEL maintainer="apu-saha-990"
LABEL project="WalletDNA"
LABEL description="Behavioural wallet fingerprinting and cluster detection"

# System deps
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY walletdna/ ./walletdna/
COPY pyproject.toml .

# Non-root user
RUN useradd -m -u 1000 walletdna && chown -R walletdna:walletdna /app
USER walletdna

CMD ["python", "-m", "walletdna", "dashboard"]
