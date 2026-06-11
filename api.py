"""
CarConnoisseur API – minimal health/status server.
Searches are managed via Supabase; this API is only used for monitoring.
"""

import json
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

logger = logging.getLogger(__name__)

_bot = None
_loop = None
_scraper = None


def set_bot(bot, loop, scraper):
    global _bot, _loop, _scraper
    _bot = bot
    _loop = loop
    _scraper = scraper
    logger.info("API: bot/loop/scraper injected")


class APIHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # suppress access logs

    def send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
        elif self.path == "/status":
            self.send_json(200, {
                "status": "ok",
                "bot_connected": _bot is not None,
                "storage": "supabase",
            })
        else:
            self.send_json(404, {"error": "Not found"})


def run_api(port: int = 8080):
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    logger.info(f"🌐 API server running on port {port}")
    server.serve_forever()


def start_api_thread(port: int = 8080):
    t = threading.Thread(target=run_api, args=(port,), daemon=True)
    t.start()
    return t
