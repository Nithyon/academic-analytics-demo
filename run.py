"""One-click start: builds the synthetic database if needed, starts the backend and opens
the demo in your browser.   python run.py
"""
import threading
import webbrowser

import uvicorn

from backend import config, data_generator

HOST, PORT = "127.0.0.1", 8000

if __name__ == "__main__":
    if not config.DB_PATH.exists():
        print("Building the synthetic star schema ...", data_generator.build(config.DEFAULT_SEED))
    url = f"http://{HOST}:{PORT}"
    print(f"\n  Demo running at {url}  (Ctrl+C to stop)\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False)
