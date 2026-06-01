"""
CarConnoisseur API – receives searches from the website and saves them
"""

import json
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

from config import Config
from search_manager import SearchManager

logger = logging.getLogger(__name__)
config = Config()
search_manager = SearchManager(config.DATA_DIR)


class APIHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        logger.info(f"API: {format % args}")

    def send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        # GET /searches?chat_id=123456
        if parsed.path == "/searches":
            params = parse_qs(parsed.query)
            chat_id = params.get("chat_id", [None])[0]
            if not chat_id:
                self.send_json(400, {"error": "chat_id required"})
                return
            searches = search_manager.get_searches(chat_id)
            result = []
            for sid, s in searches.items():
                result.append({
                    "id": sid,
                    "name": s.get("name", ""),
                    "manufacturer": s.get("manufacturer", ""),
                    "model": s.get("model", ""),
                    "price_min": s.get("price_min"),
                    "price_max": s.get("price_max"),
                    "year_min": s.get("year_min"),
                    "year_max": s.get("year_max"),
                    "km_max": s.get("km_max"),
                })
            self.send_json(200, {"searches": result})
            return

        # GET /health
        if parsed.path == "/health":
            self.send_json(200, {"status": "ok"})
            return

        self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)

        # POST /searches – add a new search
        if parsed.path == "/searches":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except Exception:
                self.send_json(400, {"error": "Invalid JSON"})
                return

            chat_id = str(data.get("chat_id", "")).strip()
            name = str(data.get("name", "")).strip()

            if not chat_id or not name:
                self.send_json(400, {"error": "chat_id and name are required"})
                return

            search = {
                "name": name,
                "manufacturer": data.get("manufacturer", "").strip(),
                "model": data.get("model", "").strip(),
                "price_min": int(data["price_min"]) if data.get("price_min") else None,
                "price_max": int(data["price_max"]) if data.get("price_max") else None,
                "year_min": int(data["year_min"]) if data.get("year_min") else None,
                "year_max": int(data["year_max"]) if data.get("year_max") else None,
                "km_max": int(data["km_max"]) if data.get("km_max") else None,
            }

            sid = search_manager.add_search(chat_id, search)
            logger.info(f"New search '{name}' added for chat_id {chat_id}")
            self.send_json(201, {"id": sid, "message": "Search added successfully"})
            return

        self.send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)

        # DELETE /searches/<search_id>?chat_id=123456
        if parsed.path.startswith("/searches/"):
            sid = parsed.path.split("/searches/")[1]
            params = parse_qs(parsed.query)
            chat_id = params.get("chat_id", [None])[0]
            if not chat_id or not sid:
                self.send_json(400, {"error": "chat_id and search id required"})
                return
            search_manager.delete_search(chat_id, sid)
            self.send_json(200, {"message": "Search deleted"})
            return

        self.send_json(404, {"error": "Not found"})


def run_api(port: int = 8080):
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    logger.info(f"🌐 API server running on port {port}")
    server.serve_forever()


def start_api_thread(port: int = 8080, sm=None):
    global search_manager
    if sm is not None:
        search_manager = sm
    t = threading.Thread(target=run_api, args=(port,), daemon=True)
    t.start()
    return t
