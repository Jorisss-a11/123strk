FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Unbuffered output so logs show up in docker logs immediately
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "main.py"]
