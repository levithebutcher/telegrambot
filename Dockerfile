FROM python:3.11-slim

# Install system dependencies including ffmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose Render health port
EXPOSE 10000

# Start the bot
CMD ["python", "bot.py"]
