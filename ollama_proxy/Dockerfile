FROM python:3.11-slim

ENV PYTHONUNBUFFERED=TRUE
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /tmp/requirements.txt
COPY main.py /app/main.py
COPY static /app/static
EXPOSE 8090
CMD ["python", "/app/main.py"]
