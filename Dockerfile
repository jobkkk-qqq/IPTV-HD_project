FROM python:3.11-slim

# 国内镜像加速 apt
RUN sed -i 's|http://deb.debian.org|http://mirrors.zju.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY docker/server.py /app/server.py
COPY docker/entrypoint.sh /app/entrypoint.sh
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh /app/entrypoint.sh

EXPOSE 3568

ENTRYPOINT ["/app/entrypoint.sh"]
