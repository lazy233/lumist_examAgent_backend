# Lumist ExamAgent Backend - 使用 Python 3.11 以兼容 sentence-transformers 等依赖
FROM python:3.11-slim-bookworm

# 时区（可选，便于日志时间）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# 安装运行时依赖（psycopg2 等可能需要的系统库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存
COPY requirements.txt .

# 使用国内镜像加速（可选，服务器在国外可去掉 -i 行）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 复制应用代码
COPY app/ ./app/
COPY sql/ ./sql/
COPY scripts/ ./scripts/

# 设置默认环境变量（可在运行时通过 .env 文件或 docker-compose 覆盖）
ENV DATA_ROOT=/app/data \
    UPLOAD_DIR=/app/data/upload \
    LIBRARY_DIR=/app/data/library \
    DEBUG_DIR=/app/data/debug \
    API_PREFIX=/api \
    ENVIRONMENT=production \
    JWT_ALGORITHM=HS256 \
    ACCESS_TOKEN_EXPIRE_MINUTES=10080 \
    LLM_MODEL=qwen-long \
    FILE_ANALYZE_MODEL=qwen-long \
    DB_ECHO=false \
    SKIP_RAG_ANALYZE=false

# 创建数据目录（运行时也可用 volume 挂载）
RUN mkdir -p /app/data/upload /app/data/library /app/data/debug

# 暴露端口（与 uvicorn 一致）
EXPOSE 8000

# 启动命令；宿主机可通过环境变量覆盖 HOST/PORT
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
