FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install critical audio system dependencies
# This permanently solves the FFmpeg/libsndfile DLL nightmares we had on Windows!
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    libsndfile1-dev \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency list
COPY requirements.txt .

# Install standard dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install GCP Core and tricky AI dependencies natively
RUN pip install --no-cache-dir \
    google-cloud-storage \
    google-cloud-pubsub \
    mt3-infer \
    "transformers<4.30.0"

# Copy the entire backend
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Run Uvicorn server (can be overridden by Pub/Sub worker command later)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
