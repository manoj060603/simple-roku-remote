#!/usr/bin/env python3
"""Install a checksum-verified official SDK on a remote build worker."""
import argparse,hashlib,json,pathlib,platform,subprocess,tarfile,urllib.request
parser=argparse.ArgumentParser()
parser.add_argument("directory",type=pathlib.Path)
parser.add_argument("--version",default="3.47.9")
args=parser.parse_args()
system="macos" if platform.system()=="Darwin" else "linux"
arch="arm64" if platform.machine().lower() in {"arm64","aarch64"} else "x64"
manifest_url="https://storage.googleapis.com/flutter_infra_release/releases/releases_"+system+".json"
with urllib.request.urlopen(manifest_url,timeout=60) as response:data=json.load(response)
entry=next(item for item in data["releases"] if item["version"]==args.version and item["channel"]=="stable" and item.get("dart_sdk_arch","x64")==arch)
args.directory.mkdir(parents=True,exist_ok=True)
archive=args.directory/pathlib.Path(entry["archive"]).name
with urllib.request.urlopen(data["base_url"]+"/"+entry["archive"],timeout=120) as response,archive.open("wb") as target:
    while chunk:=response.read(1024*1024):target.write(chunk)
with archive.open("rb") as file:actual=hashlib.file_digest(file,"sha256").hexdigest()
if actual!=entry["sha256"]:raise SystemExit("Official SDK checksum did not match.")
if system=="macos":subprocess.run(["ditto","-x","-k",str(archive),str(args.directory)],check=True)
else:
    with tarfile.open(archive) as file:file.extractall(args.directory,filter="data")
print(args.directory/"flutter/bin/flutter")
