FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY shortforge ./shortforge
RUN pip install --no-cache-dir .
EXPOSE 8787
CMD ["shortforge-backend"]
