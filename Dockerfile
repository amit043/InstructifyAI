FROM python:3.11-slim

# Build-time toggles for ML and model prefetch
ARG INSTALL_ML=1          # 1 installs ML deps for api/gen/trainer
ARG ML_VARIANT=cpu        # cpu | gpu
ARG HF_PREFETCH=0         # 1 to prefetch model at build
ARG HF_MODEL=Phi-3-mini-4k-instruct

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONPATH=/app \
    HF_HOME=/opt/hf \
    TRANSFORMERS_CACHE=/opt/hf

WORKDIR /app

# Install minimal OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    cmake \
  && rm -rf /var/lib/apt/lists/*

# Base Python deps (runtime only)
COPY requirements-base.txt requirements-base.txt
RUN pip install --no-cache-dir -r requirements-base.txt

# Optional: ML deps (torch etc.) controlled by INSTALL_ML + ML_VARIANT
COPY requirements-ml-common.txt requirements-ml-common.txt
RUN /bin/sh -lc '\
  if [ "$INSTALL_ML" = "1" ]; then \
    echo "Installing ML common deps (variant=$ML_VARIANT)"; \
    pip install --no-cache-dir -r requirements-ml-common.txt; \
    if [ "$ML_VARIANT" = "gpu" ]; then \
      echo "Installing PyTorch CUDA wheels"; \
      pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio; \
      pip install bitsandbytes; \
    else \
      echo "Installing PyTorch CPU wheel"; \
      pip install --no-cache-dir torch; \
    fi; \
  fi'

# Optional: prefetch HF model into image for fast startup
# Note: Avoid heredocs for Podman/Buildah compatibility. Keep python -c on one line.
RUN /bin/sh -lc "if [ \"$INSTALL_ML\" = \"1\" ] && [ \"$HF_PREFETCH\" = \"1\" ]; then python -c \"import os; from huggingface_hub import snapshot_download; model=os.environ.get('HF_MODEL','Phi-3-mini-4k-instruct'); cache_dir=os.environ.get('HF_HOME','/opt/hf'); print('[build] Prefetching HF model: %s -> %s' % (model, cache_dir)); snapshot_download(repo_id=model, resume_download=True, local_dir=cache_dir, local_dir_use_symlinks=False); print('[build] Prefetch complete')\"; fi"

# App source
COPY . .

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

