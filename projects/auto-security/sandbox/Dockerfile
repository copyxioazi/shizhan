# 自动化安全评估沙箱镜像 ase-sandbox:1.0
# 构建（在仓库根目录执行）：
#   docker build -f sandbox/Dockerfile -t ase-sandbox:1.0 .
FROM python:3.11-slim

RUN groupadd -g 1000 sandbox \
    && useradd -u 1000 -g sandbox -m -s /usr/sbin/nologin sandbox

COPY sandbox/helper.py /opt/sandbox/helper.py
RUN chmod 0555 /opt/sandbox/helper.py

USER 1000:1000
WORKDIR /workspace

# 容器由后端以 --network none、--cap-drop ALL、--security-opt no-new-privileges 运行
CMD ["sleep", "infinity"]
