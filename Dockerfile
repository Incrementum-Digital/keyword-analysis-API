FROM python:3.11-slim

WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Railway provides PORT env var - default to 8000 for local dev
ENV PORT=8000

# Use shell form to expand $PORT variable
CMD uvicorn app:app --host 0.0.0.0 --port $PORT
