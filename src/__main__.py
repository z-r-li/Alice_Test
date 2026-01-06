"""
Alice Test 入口模块

支持通过 python -m src 方式运行程序。

使用方法：
    python -m src --config config.yaml
    python -m src --help
"""
from .main import main

if __name__ == "__main__":
    main()
