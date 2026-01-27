FROM python:3.11-slim

ENV PYTHONUNBUFFERED=TRUE
WORKDIR /app
COPY main.py /app/main.py
COPY static /app/static
EXPOSE 8090
CMD ["python", "/app/main.py"]
