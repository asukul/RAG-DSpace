FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /app/data

# Cloud Run injects PORT (defaults to 8080); fall back to 8000 locally
ENV PORT=8000
EXPOSE 8000

# Run the application — sh -c so $PORT is expanded at runtime
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
