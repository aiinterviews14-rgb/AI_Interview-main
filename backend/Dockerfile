# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file first for better caching
COPY requirements.txt .

# Mitigate "Bus Error" / Errno 5 during large wheel extraction by moving pip temp folder
ENV TMPDIR=/var/tmp

# Install Python dependencies with a retry loop to handle unstable network connections.
# We let pip cache the files while retrying, then clean them up manually to keep the image slim.
RUN pip install --default-timeout=1000 --upgrade pip setuptools wheel
RUN for i in 1 2 3 4 5; do \
        pip install --default-timeout=1000 -r requirements.txt && break || sleep 5; \
    done && rm -rf /root/.cache/pip

# Copy the rest of the backend application code
COPY . .

# Expose the port the app runs on
EXPOSE 5000

# Gunicorn: default 1 worker (in-memory interview state is not shared across workers).
# Concurrency: gthread worker with multiple threads. Override: GUNICORN_WORKERS, GUNICORN_THREADS.
# See backend/deploy/README.md and app_config.py.
ENV GUNICORN_WORKERS=1
ENV GUNICORN_THREADS=4

# Run the application
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:5000 -k gthread --threads ${GUNICORN_THREADS:-4} --workers ${GUNICORN_WORKERS:-1} --timeout 120 api:app"]
