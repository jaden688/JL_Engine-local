FROM python:3.11-slim

# Prevent Python from writing .pyc files and using buffered stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create app directory
WORKDIR /app

# System dependencies for audio/Tk builds and basic tooling
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        python3-tk \
        tk-dev \
        libasound2-dev \
        portaudio19-dev \
        ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency file(s) first to leverage docker layer cache
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source code
COPY . /app

# Cloud Run expects the app to listen on PORT (default 8080)
ENV PORT=8080

# Expose the port (useful for local docker run; Cloud Run ignores EXPOSE)
EXPOSE 8080

# Start the FastAPI monetization API
CMD ["sh", "-c", "uvicorn api_server:app --host 0.0.0.0 --port ${PORT:-8080}"]
