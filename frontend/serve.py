"""
serve.py — EgerBot local development server
Run this instead of double-clicking index.html

Usage:
  python serve.py

Then open: http://localhost:8080
"""

import http.server
import socketserver
import webbrowser
import os
import sys

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        # Suppress noisy request logs, only show errors
        if args[1] not in ("200", "304"):
            super().log_message(format, *args)

    def end_headers(self):
        # Add CORS headers so the frontend can call localhost:5000
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


def main():
    os.chdir(DIRECTORY)

    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}/index.html"
        print()
        print("  ╔══════════════════════════════════════════╗")
        print("  ║         EgerBot Frontend Server          ║")
        print("  ╠══════════════════════════════════════════╣")
        print(f"  ║  URL:  {url:<34}║")
        print(f"  ║  Dir:  {DIRECTORY[:34]:<34}║")
        print("  ║                                          ║")
        print("  ║  Press Ctrl+C to stop the server        ║")
        print("  ╚══════════════════════════════════════════╝")
        print()

        # Auto-open browser
        webbrowser.open(url)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
            sys.exit(0)


if __name__ == "__main__":
    main()
