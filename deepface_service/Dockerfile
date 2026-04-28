FROM tensorflow/tensorflow:2.16.1-gpu

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/srv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH
ENV DEEPFACE_HOST=0.0.0.0
ENV DEEPFACE_PORT=8120
ENV DEEPFACE_DATA_DIR=/data/deepface
ENV DEEPFACE_ACCESS_FILE=/data/deepface/access.yaml
ENV DEEPFACE_LOG_FILE=/data/deepface/auth.log
ENV DEEPFACE_MODEL_NAME=Facenet512
ENV DEEPFACE_DETECTOR_BACKEND=opencv
ENV DEEPFACE_ENFORCE_DETECTION=false
ENV DEEPFACE_MYSQL_HOST=
ENV DEEPFACE_MYSQL_PORT=3306
ENV DEEPFACE_MYSQL_DATABASE=
ENV DEEPFACE_MYSQL_USER=
ENV DEEPFACE_MYSQL_PASSWORD=
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV TF_FORCE_GPU_ALLOW_GROWTH=true

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt /tmp/requirements.txt
RUN python -m venv --system-site-packages ${VIRTUAL_ENV} \
    && python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /tmp/requirements.txt

COPY . /srv/deepface_service

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data/deepface/people \
    && chown -R appuser:appuser /srv /data/deepface

USER appuser

EXPOSE 8120

CMD ["sh", "-c", "python -m uvicorn deepface_service.main:app --host ${DEEPFACE_HOST} --port ${DEEPFACE_PORT}"]
