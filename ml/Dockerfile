FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY ml/requirements.inference.txt /app/requirements.inference.txt
RUN pip install --no-cache-dir -r /app/requirements.inference.txt

COPY . /app

EXPOSE 8000

CMD ["uvicorn", "ml.model_api_server:app", "--host", "0.0.0.0", "--port", "8000"]
