"""Local organization viewer and explicit chat entry point. Run: python -m company.viewer."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import unquote, urlparse

from company.config import PROJECT_ROOT
from company.actions import ReflectionService
from company.activity import recent_activity
from company.chat import ChatService
from company.store import Store

ASSETS = Path(__file__).with_name("web")


def snapshot(store: Store) -> dict:
    tables = {row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    versions = [dict(row) for row in store.db.execute("SELECT * FROM versions ORDER BY created_at DESC")]
    for row in versions:
        row["manifest"] = json.loads(row["manifest"])
    result = {"active": store.active(), "runs": store.history(), "versions": versions,
              "proposals": [], "reflections": [], "reflection_memory": [], "activations": [], "audits": [],
              "chat_threads": [], "chat_turns": [], "actions": []}
    for table, fields in {
        "proposals": ("document", "evaluation"),
        "reflections": ("evidence_ids", "memory_ids", "usage", "response"),
        "reflection_memory": ("evidence",),
        "activations": (),
        "audits": ("plan", "report"),
        "chat_threads": (),
        "actions": ("result",),
    }.items():
        if table in tables:
            rows = [dict(row) for row in store.db.execute(f"SELECT * FROM {table} ORDER BY created_at DESC")]
            for row in rows:
                for field in fields:
                    if row.get(field) is not None:
                        row[field] = json.loads(row[field])
            result[table] = rows
    if "chat_turns" in tables:
        result["chat_turns"] = store.chat_turns()
        for turn in result["chat_turns"]:
            if turn["status"] == "running":
                turn["activity"] = recent_activity(store, turn["run_id"]) if turn["run_id"] else []
    return result


def handler_for(db_path: Path):
    chat = ChatService(db_path)
    reflection = ReflectionService(db_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path not in ("/api/chat", "/api/chat/delete", "/api/chat/stop", "/api/reflect"):
                self.send_error(404)
                return
            # Only an explicit request from this local UI can start paid inference.
            port = self.server.server_port
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{port}", f"localhost:{port}"} or self.headers.get("Origin") != f"http://{host}":
                self.send_error(403, "Actions must originate from this local viewer")
                return
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Expected application/json")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 40000:
                    raise ValueError("Invalid message size")
                payload = json.loads(self.rfile.read(size))
                if self.path == "/api/reflect":
                    if payload != {}:
                        raise ValueError("Reflection uses the active version and fixed policy; no overrides accepted")
                    result = reflection.submit()
                elif self.path == "/api/chat/delete":
                    result = chat.delete(payload)
                elif self.path == "/api/chat/stop":
                    result = chat.stop(payload)
                else:
                    result = chat.submit(payload)
                status = 200 if self.path == "/api/chat/delete" else 202
            except (ValueError, UnicodeError) as error:
                result, status = {"error": str(error)}, 400
            except RuntimeError as error:
                result, status = {"error": str(error)}, 409
            except Exception:
                result, status = {"error": "Unable to start action; check local server configuration"}, 500
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path.startswith("/api/"):
                    # The viewer never creates a schema, mutates records, or starts inference.
                    store = Store.__new__(Store)
                    store.db = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
                    store.db.row_factory = sqlite3.Row
                    try:
                        if path == "/api/state":
                            payload = snapshot(store)
                            payload["chat_control"] = chat.control()
                        elif path.startswith("/api/runs/") and len(path.split("/")) == 4:
                            payload = store.replay(path.rsplit("/", 1)[-1])
                        else:
                            self.send_error(404)
                            return
                    finally:
                        store.close()
                    data, content_type = json.dumps(payload).encode(), "application/json"
                else:
                    assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
                    if path not in assets:
                        self.send_error(404)
                        return
                    filename, content_type = assets[path]
                    data = (ASSETS / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, sqlite3.Error):
                self.send_error(404, "Record or initialized database not available")
            except (BrokenPipeError, ConnectionResetError):
                pass  # The browser navigated away while a read was in flight.

        def log_message(self, format, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data/company.sqlite3")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    store = Store(args.db)
    try:
        with store.controller():
            store.recover_interrupted()
    except RuntimeError:
        pass  # A CLI operation may already own the company; reading remains available.
    finally:
        store.close()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(args.db))
    print(f"Company viewer: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
