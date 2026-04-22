import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path.cwd()))

# Simulate collision in environment
os.environ["MB_PROXY"] = "http://some-proxy-url"
os.environ["MB_PROXY__ENABLED"] = "false"
os.environ["MB_BOT__TOKEN"] = "test-token"
os.environ["MB_DATABASE__URL"] = "sqlite+aiosqlite:///:memory:"

try:
    from config.settings import Settings
    settings = Settings()
    print(f"proxy.enabled: {settings.proxy.enabled}")
    print("Success: MB_PROXY collision handled robustly!")
except Exception as e:
    print(f"Failed: {e}")
    import traceback
    traceback.print_exc()
