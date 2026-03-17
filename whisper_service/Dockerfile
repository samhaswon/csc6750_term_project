FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/srv
ENV TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124
ENV WHISPER_HOST=0.0.0.0
ENV WHISPER_PORT=8100
ENV WHISPER_MODEL=turbo
ENV WHISPER_MODEL_DIR=/models/whisper
ENV WHISPER_DEVICE=auto
ENV MAX_UPLOAD_MB=50

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --upgrade pip setuptools wheel \
    && python3 -m pip install --index-url "${TORCH_INDEX_URL}" torch \
    && python3 -m pip install -r /tmp/requirements.txt

COPY . /srv/whisper_service

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /models/whisper \
    && chown -R appuser:appuser /srv /models/whisper

USER appuser

EXPOSE 8100

CMD ["sh", "-c", "python3 -m uvicorn whisper_service.main:app --host ${WHISPER_HOST} --port ${WHISPER_PORT}"]
