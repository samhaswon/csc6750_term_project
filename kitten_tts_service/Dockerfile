FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/srv
ENV KITTEN_HOST=0.0.0.0
ENV KITTEN_PORT=8110
ENV KITTEN_MODEL=KittenML/kitten-tts-nano-0.8
ENV KITTEN_MODEL_DIR=/models/kitten_tts
ENV KITTEN_CACHE_DB=/data/kitten_tts/cache.sqlite3
ENV KITTEN_DEVICE=auto
ENV KITTEN_DEFAULT_VOICE=Bella
ENV MAX_INPUT_CHARS=5000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        espeak-ng \
        ffmpeg \
        libgomp1 \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /tmp/requirements.txt \
    && python -m pip install --no-deps \
        https://github.com/KittenML/KittenTTS/releases/download/0.8.1/kittentts-0.8.1-py3-none-any.whl

COPY . /srv/kitten_tts_service

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data/kitten_tts /models/kitten_tts \
    && chown -R appuser:appuser /srv /data/kitten_tts /models/kitten_tts

USER appuser

EXPOSE 8110

CMD ["sh", "-c", "python -m uvicorn kitten_tts_service.main:app --host ${KITTEN_HOST} --port ${KITTEN_PORT}"]
