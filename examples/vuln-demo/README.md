# vuln-demo

一个仅依赖 Python 标准库的小型示例项目，内置 5 类用于演示的漏洞。

## 启动

```text
python app.py
```

默认监听 `127.0.0.1:8000`，可用 `PORT` 环境变量覆盖。

## 接口

| 路径 | 参数 | 演示的漏洞类别 |
| --- | --- | --- |
| `/search` | `q` | SQL 注入 |
| `/ping` | `host` | 命令注入 |
| `/download` | `filename` | 路径穿越 |
| `/orders` | `order_id` | 越权访问（IDOR） |

硬编码密钥位于 `config.py`。

## 验证脚本

`verify/` 下的脚本由评估系统在沙箱内执行：

```text
python -B /src/verify/sql_injection.py
```

成功时输出 `VULN_CONFIRMED` 并以 0 退出。脚本仅使用标准库，不通过 `subprocess` 启动目标应用。
