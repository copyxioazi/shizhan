FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CN_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc

WORKDIR /app

# 中文字体用于示例合同生成；libgl/libglib 供 OpenCV（RapidOCR）使用。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY frontend ./frontend
COPY scripts ./scripts
COPY sample_contracts ./sample_contracts
COPY pyproject.toml README.md ./

RUN mkdir -p /app/data

EXPOSE 8000
STOPSIGNAL SIGTERM

# 每次启动先做幂等初始化（建表、种子规则、Mock 数据、补齐示例合同）。
CMD ["sh", "-c", "python scripts/init_db.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
