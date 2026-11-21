#!/usr/bin/env python3
"""Temporarily expose only finished, public release artifacts for GitHub packaging."""
import argparse,hashlib,json,mimetypes,pathlib,re,subprocess,threading,time,urllib.parse,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
parser=argparse.ArgumentParser()
parser.add_argument("directory",type=pathlib.Path)
parser.add_argument("--worker",required=True,type=pathlib.Path)
args=parser.parse_args()
root=args.directory.resolve()
allowed={"manifest.json","SHA256SUMS","simple-roku-remote-android.apk","mobile-connect.png","mobile-remote.png","mobile-keyboard.png"}
if not (root/"simple-roku-remote-android.apk").is_file():raise SystemExit("No completed Android artifact.")
binary=args.worker/"cloudflared"
url="https://github.com/cloudflare/cloudflared/releases/download/2026.11.1/cloudflared-linux-amd64"
expected="97bb3b02d23a5980fc9c15a1a270e692da1923f103f920d5b16d4931d5ab55e7"
if not binary.exists():
    with urllib.request.urlopen(url,timeout=120) as response,binary.open("wb") as file:
        while chunk:=response.read(1024*1024):file.write(chunk)
with binary.open("rb") as file:actual=hashlib.file_digest(file,"sha256").hexdigest()
if actual!=expected:raise SystemExit("Tunnel binary integrity check failed.")
binary.chmod(0o700)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        name=urllib.parse.urlsplit(self.path).path
        if not name.startswith("/") or name[1:] not in allowed:
            self.send_error(404);return
        file=root/name[1:]
        if not file.is_file():self.send_error(404);return
        self.send_response(200)
        self.send_header("Content-Length",str(file.stat().st_size))
        self.send_header("Content-Type",mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.end_headers()
        with file.open("rb") as data:
            while chunk:=data.read(1024*1024):self.wfile.write(chunk)
server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
server.daemon_threads=True
threading.Thread(target=server.serve_forever,daemon=True).start()
log_path=args.worker/"artifact-share.log"
stop=args.worker/"artifact-share.stop"
stop.unlink(missing_ok=True)
with log_path.open("w") as log:
    process=subprocess.Popen([str(binary),"tunnel","--no-autoupdate","--protocol","http2","--edge-ip-version","4","--url","http://127.0.0.1:"+str(server.server_port)],stdout=log,stderr=subprocess.STDOUT)
    try:
        origin=None
        for _ in range(90):
            match=re.search(r"https://[a-z0-9-]+\.trycloudflare\.com",log_path.read_text())
            if match:origin=match.group(0);break
            if process.poll() is not None:raise SystemExit("Artifact tunnel stopped.")
            time.sleep(1)
        if not origin:raise SystemExit("Artifact tunnel was not ready.")
        status={"origin":origin,"expires_in_seconds":900}
        (args.worker/"artifact-share.json").write_text(json.dumps(status))
        print(json.dumps(status),flush=True)
        for _ in range(900):
            if stop.exists() or process.poll() is not None:break
            time.sleep(1)
    finally:
        process.terminate()
        server.shutdown()
        server.server_close()
