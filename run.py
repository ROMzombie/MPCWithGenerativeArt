import sys
import os
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import uvicorn
import webbrowser
import threading
import time

def open_browser(url: str):
    time.sleep(1.2)
    print(f"Opening web application in browser: {url}")
    webbrowser.open(url)

def main():
    host = "127.0.0.1"
    port = 8000
    url = f"http://{host}:{port}"
    print("=" * 60)
    print(" 🎴 MPCWithGenerativeArt - Deck Creator Server")
    print(f" Web Interface: {url}")
    print("=" * 60)

    # Launch browser automatically
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    uvicorn.run("backend.app:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    main()
