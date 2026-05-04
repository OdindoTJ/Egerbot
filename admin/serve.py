"""
serve.py — EgerBot Admin Dashboard local server
Run: python serve.py
Opens: http://localhost:8081
"""
import http.server, socketserver, webbrowser, os, sys

PORT = 8081
DIR  = os.path.dirname(os.path.abspath(__file__))

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw): super().__init__(*a, directory=DIR, **kw)
    def log_message(self, f, *a):
        if a[1] not in ("200","304"): super().log_message(f, *a)
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Cache-Control","no-cache")
        super().end_headers()

with socketserver.TCPServer(("", PORT), H) as s:
    url = f"http://localhost:{PORT}/index.html"
    print(f"\n  EgerBot Admin  →  {url}\n  Ctrl+C to stop\n")
    webbrowser.open(url)
    try: s.serve_forever()
    except KeyboardInterrupt: print("\nStopped."); sys.exit(0)
