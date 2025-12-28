import sys
from pathlib import Path

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

if __name__ == "__main__":
    from src.app import app, startup_checks
    import os
    startup_checks()
    HOST = os.environ.get("SERVER_HOST", "localhost")
    PORT = int(os.environ.get("SERVER_PORT", "5000"))
    app.run(HOST, PORT, debug=True, use_reloader=False)
