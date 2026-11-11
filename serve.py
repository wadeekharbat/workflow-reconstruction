"""Serve the local workflow analyzer and its browser interface."""

import argparse
import csv
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from reconstruct import read_cases, reconstruct


ROOT = Path(__file__).resolve().parent
MAX_BYTES = 64 * 1024 * 1024
FILES = {
    "/": ("web/index.html", "text/html; charset=utf-8"),
    "/app.css": ("web/app.css", "text/css; charset=utf-8"),
    "/app.js": ("web/app.js", "text/javascript; charset=utf-8"),
    "/sample.csv": ("examples/ci.csv", "text/csv; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        self.send_bytes(status, "application/json; charset=utf-8",
                        json.dumps(payload, ensure_ascii=True).encode("utf-8"))

    def local_request(self):
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") == host and self.headers.get("Origin") in (None, f"http://{host}"):
            return True
        self.send_json(403, {"error": "Open the local address printed by the server."})
        return False

    def do_GET(self):
        if not self.local_request():
            return
        asset = FILES.get(urlsplit(self.path).path)
        if asset is None:
            self.send_json(404, {"error": "Page not found."})
            return
        name, content_type = asset
        self.send_bytes(200, content_type, (ROOT / name).read_bytes())

    def do_POST(self):
        if not self.local_request():
            return
        request = urlsplit(self.path)
        if request.path not in {"/api/columns", "/api/analyze"}:
            self.send_json(404, {"error": "Endpoint not found."})
            return
        if self.headers.get_content_type() != "application/octet-stream":
            self.send_json(415, {"error": "Expected a CSV upload."})
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
            if not 0 < size <= MAX_BYTES:
                raise ValueError("Choose a non-empty CSV up to 64 MiB.")
            with io.TextIOWrapper(io.BytesIO(self.rfile.read(size)), encoding="utf-8-sig",
                                  newline="") as stream:
                if request.path == "/api/columns":
                    columns = next(csv.reader(stream, strict=True), [])
                    if not columns or any(not name.strip() for name in columns):
                        raise ValueError("The CSV needs a header with named columns.")
                    if len(set(columns)) != len(columns):
                        raise ValueError("The CSV header contains duplicate column names.")
                    self.send_json(200, {"columns": columns})
                    return
                settings = parse_qs(request.query, max_num_fields=8)
                case, stage, time = (settings.get(key, [""])[0] for key in ("case", "stage", "time"))
                if not all((case, stage, time)):
                    raise ValueError("Map the case ID, stage and timestamp columns.")
                cases = read_cases(stream, case, stage, time,
                                   settings.get("format", [None])[0],
                                   settings.get("order", [None])[0])
                if not cases:
                    raise ValueError("The CSV has a header but no data records.")
                report = reconstruct(cases, unknown_stages=settings.get("unknown", []),
                                     include_examples=True)
        except UnicodeDecodeError:
            self.send_json(400, {"error": "Save the CSV as UTF-8 and try again."})
            return
        except (ValueError, csv.Error) as error:
            self.send_json(400, {"error": str(error)})
            return
        self.send_json(200, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Open http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
