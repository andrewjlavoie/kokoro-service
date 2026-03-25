FROM python:3.12-slim

# System dependencies for phoneme conversion (espeak-ng covers en/es/fr/hi/it/pt)
# Build tools needed for pyopenjtalk (Japanese) compilation
RUN apt-get update && \
    apt-get install -y --no-install-recommends espeak-ng build-essential cmake && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (torch first — largest layer, cached separately)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.server.txt .
RUN pip install --no-cache-dir -r requirements.server.txt

# Install spaCy English model
RUN pip install --no-cache-dir \
    en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# Download unidic dictionary for Japanese
RUN python -m unidic download

# Download NLTK data for Korean
RUN python -c "import nltk; nltk.download('averaged_perceptron_tagger_eng', quiet=True)"

COPY kokoro_sdk.py server.py db.py cache.py ./
COPY static/ ./static/

EXPOSE 8880

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8880", "--log-level", "warning"]
