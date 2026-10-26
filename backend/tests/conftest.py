import os

# 在导入 app.core.config 前提供测试用密钥（长度 >= 32）
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789")
os.environ.setdefault("JWT_EXPIRE_HOURS", "24")
