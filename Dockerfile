FROM python:3.12-slim

# System dependency for phoneme conversion
RUN apt-get update && \
    apt-get install -y --no-install-recommends espeak-ng && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (torch first — largest layer, cached separately)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.server.txt .
RUN pip install --no-cache-dir -r requirements.server.txt

# Install spaCy English model (avoids the silent pip crash at runtime)
RUN pip install --no-cache-dir \
    en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

COPY kokoro_sdk.py server.py db.py cache.py ./
COPY static/ ./static/

EXPOSE 8880

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8880", "--log-level", "warning"]
