FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/srv
ENV DEEPFACE_HOST=0.0.0.0
ENV DEEPFACE_PORT=8120
ENV DEEPFACE_DATA_DIR=/data/deepface
ENV DEEPFACE_ACCESS_FILE=/data/deepface/access.yaml
ENV DEEPFACE_LOG_FILE=/data/deepface/auth.log
ENV DEEPFACE_MODEL_NAME=Facenet512
ENV DEEPFACE_DETECTOR_BACKEND=opencv
ENV DEEPFACE_ENFORCE_DETECTION=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /tmp/requirements.txt

COPY . /srv/deepface_service

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data/deepface/people \
    && chown -R appuser:appuser /srv /data/deepface

USER appuser

EXPOSE 8120

CMD ["sh", "-c", "python -m uvicorn deepface_service.main:app --host ${DEEPFACE_HOST} --port ${DEEPFACE_PORT}"]
