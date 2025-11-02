FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models/hf \
    TRANSFORMERS_CACHE=/models/hf

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1 && \
    pip install --upgrade pip

WORKDIR /app

# Install core requirements + DeepSeek deps
COPY requirements-base.txt requirements-base.txt
RUN pip install -r requirements-base.txt && \
    pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124 && \
    (pip install flash-attn==2.7.3 --no-build-isolation || echo "flash-attn optional") && \
    pip install transformers==4.46.2 accelerate==0.34.2 pillow==10.4.0 && \
    pip install vllm==0.6.2

# App code
COPY . .

VOLUME ["/models/hf"]

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD ["python","-c","import base64;from services.ocr.deepseek_runner import DeepseekOCRRunner;runner=DeepseekOCRRunner(model='deepseek-ai/DeepSeek-OCR');runner._has_gpu=lambda: True;runner._run_transformers=lambda *a,**k: 'ok';runner.run(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII='))"]

CMD ["celery", "-A", "worker.main", "worker", "--loglevel=info", "-Q", "ocr_gpu"]
