FROM python:3.13-alpine

# Set working directory
WORKDIR /app

# 使用清华源替换 Alpine 镜像源（关键步骤）
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apk/repositories && \
    # 清理缓存（避免镜像过大）
    rm -rf /var/cache/apk/* && \
    # 更新包列表（使用清华源）
    apk update && \
    # 安装 FFmpeg（带 --no-cache 优化镜像大小）
    apk add --no-cache ffmpeg

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
