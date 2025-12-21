FROM python:3.13-alpine

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY voice.json .
COPY create_superuser.py .

# Create necessary directories
RUN mkdir -p /app/instance /app/uploads /app/audio

# Expose Flask port
EXPOSE 5002

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "app/app.py"]
