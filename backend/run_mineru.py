"""根据 config/mineru.yml 启动 mineru-api"""
import subprocess
import sys
from pathlib import Path
import yaml

config_path = Path(__file__).parent / "config" / "mineru.yml"
cfg = yaml.safe_load(open(config_path, encoding="utf-8"))["mineru"]

host = cfg["host"]
port = cfg["port"]

print(f"启动 mineru-api: http://{host}:{port}")
subprocess.run([sys.executable, "-m", "mineru.cli.fast_api",
                "--host", host, "--port", str(port)])
