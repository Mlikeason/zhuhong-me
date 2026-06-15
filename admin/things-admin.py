#!/usr/bin/env python3
"""Things admin server — local-only tool to manage the Things grid in index.html.

Run from the repo root:
    python3 admin/things-admin.py

It opens http://127.0.0.1:8765/ in your browser and lets you:
  - drag-reorder items
  - edit captions inline
  - upload new images (saved to assets/things/)
  - delete items (the image file stays on disk; only the entry is removed)
  - Save writes back to index.html (does not git commit — review and commit yourself)

Stop the server with Ctrl-C.
"""

import http.server
import socketserver
import json
import re
import base64
import os
import sys
import html
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # zhuhong_me/
INDEX = ROOT / "index.html"
THINGS_DIR = ROOT / "assets" / "things"
DEFAULT_PORT = 8766

# ---- index.html parsing / writing ----

# Match a single things-item line. Tolerates extra attributes on the inner img and outer div.
ITEM_RE = re.compile(
    r'<div class="things-item"[^>]*>\s*'
    r'<img[^>]*src="\./assets/things/([^"]+)"[^>]*>\s*'
    r'<div class="things-caption">\s*<span>([^<]*)</span>\s*</div>\s*'
    r'</div>'
)

# Match the things-grid block: opening div, inner content, closing </div> followed by whitespace then <footer.
GRID_RE = re.compile(
    r'(<div class="things-grid">)(.*?)(\n\s*</div>\s*\n\s*<footer)',
    re.DOTALL,
)

def read_things():
    text = INDEX.read_text(encoding='utf-8')
    m = GRID_RE.search(text)
    items = []
    if m:
        for itm in ITEM_RE.finditer(m.group(2)):
            items.append({"file": itm.group(1), "caption": html.unescape(itm.group(2))})
    return items

def write_things(items):
    text = INDEX.read_text(encoding='utf-8')
    lines = []
    for i, it in enumerate(items):
        caption = html.escape(it["caption"], quote=False)
        fname = html.escape(it["file"], quote=True)
        lines.append(
            f'            <div class="things-item" data-index="{i}">'
            f'<img src="./assets/things/{fname}" alt="">'
            f'<div class="things-caption"><span>{caption}</span></div>'
            f'</div>'
        )
    new_inner = '\n' + '\n'.join(lines) + '\n          '

    def replace(m):
        return m.group(1) + new_inner + m.group(3)

    new_text, n = GRID_RE.subn(replace, text, count=1)
    if n == 0:
        raise RuntimeError("could not locate things-grid block in index.html")
    INDEX.write_text(new_text, encoding='utf-8')

def next_filename(content_type, original_name=""):
    ext_map = {
        'image/jpeg': 'jpg',
        'image/jpg': 'jpg',
        'image/png': 'png',
        'image/webp': 'webp',
        'image/heic': 'heic',
    }
    ext = ext_map.get(content_type.lower(), '')
    if not ext and original_name:
        original_ext = original_name.rsplit('.', 1)[-1].lower()
        if original_ext in ('jpg', 'jpeg', 'png', 'webp', 'heic'):
            ext = 'jpg' if original_ext == 'jpeg' else original_ext
    if not ext:
        ext = 'jpg'

    nums = []
    for f in THINGS_DIR.iterdir():
        m = re.match(r'things-(\d+)\.', f.name)
        if m:
            nums.append(int(m.group(1)))
    next_n = max(nums, default=0) + 1
    return f'things-{next_n:02d}.{ext}'

# ---- HTTP handler ----

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # quieter logging
        if '/api/' in self.path or self.path == '/':
            sys.stderr.write("[admin] %s %s\n" % (self.command, self.path))

    def do_GET(self):
        if self.path == '/api/things':
            self._json(200, read_things())
            return
        if self.path == '/':
            self.path = '/admin/index.html'
        return super().do_GET()

    def do_POST(self):
        try:
            if self.path == '/api/things':
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                items = json.loads(body)
                if not isinstance(items, list):
                    raise ValueError("expected list")
                write_things(items)
                self._json(200, {"ok": True, "count": len(items)})
                return
            if self.path == '/api/upload':
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                data = json.loads(body)
                content_type = data.get('content_type', 'image/jpeg')
                original = data.get('original_name', '')
                raw = base64.b64decode(data['data_base64'])
                fn = next_filename(content_type, original)
                (THINGS_DIR / fn).write_bytes(raw)
                self._json(200, {"file": fn})
                return
        except Exception as e:
            sys.stderr.write(f"[admin] error: {e}\n")
            self._json(500, {"error": str(e)})
            return
        self._json(404, {"error": "not found"})

    def _json(self, code, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

# ---- main ----

def main():
    if not INDEX.exists():
        sys.exit(f"index.html not found at {INDEX}")
    if not THINGS_DIR.exists():
        sys.exit(f"assets/things not found at {THINGS_DIR}")

    # CLI: --port N (or -p N)
    port = DEFAULT_PORT
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a in ('-p', '--port') and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                sys.exit(f"invalid port: {args[i + 1]}")
        elif a in ('-h', '--help'):
            print(__doc__)
            print(f"Usage: python3 admin/things-admin.py [--port N]  (default {DEFAULT_PORT})")
            return

    os.chdir(ROOT)
    url = f"http://127.0.0.1:{port}/"
    print(f"Things admin: {url}")
    print(f"Items detected: {len(read_things())}")
    print("Stop with Ctrl-C")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nstopped")
    except OSError as e:
        if 'Address already in use' in str(e) or getattr(e, 'errno', None) == 48:
            sys.exit(
                f"\nPort {port} is already in use.\n"
                f"Try a different port: python3 admin/things-admin.py --port 9876"
            )
        raise

if __name__ == '__main__':
    main()
