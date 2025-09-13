FROM python:3.11-slim

# Install Tesseract OCR and its dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    && apt-get clean

WORKDIR /app
ENV PYTHONPATH=/app

# Install Python dependencies (allow optional llama-cpp-python)
COPY requirements.txt requirements.txt
# Install all deps except llama-cpp-python first
RUN grep -v '^llama-cpp-python' requirements.txt > /tmp/requirements.base.txt && \
    pip install --no-cache-dir -r /tmp/requirements.base.txt

# Optional: build/install llama-cpp-python (CPU) if enabled
ARG ENABLE_LLAMA_CPP=0
RUN if [ "$ENABLE_LLAMA_CPP" = "1" ]; then \
      pip install --no-cache-dir llama-cpp-python; \
    else \
      echo "Skipping llama-cpp-python install (ENABLE_LLAMA_CPP=$ENABLE_LLAMA_CPP)"; \
    fi

COPY . .

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

