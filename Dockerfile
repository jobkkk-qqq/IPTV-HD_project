FROM python:3.11-slim

# 使用国内镜像加速 apt（宿主机可用 mirrors.zju.edu.cn）
RUN sed -i 's|http://deb.debian.org|http://mirrors.zju.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY docker/server.py /app/server.py
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh

EXPOSE 3568
CMD ["python3", "/app/server.py"]
