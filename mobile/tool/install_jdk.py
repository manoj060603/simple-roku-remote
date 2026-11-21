#!/usr/bin/env python3
"""Install a checksum-verified full Temurin JDK on a Linux build worker."""
import argparse,hashlib,pathlib,tarfile,urllib.request
parser=argparse.ArgumentParser()
parser.add_argument("directory",type=pathlib.Path)
args=parser.parse_args()
url="https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.21.1%2B2/OpenJDK17U-jdk_x64_linux_hotspot_17.0.21.1_2.tar.gz"
expected="0b0ac5eab6db6abaec68c9913bcddb31321e5da411c45073d520d9c125e6f7b4"
args.directory.mkdir(parents=True,exist_ok=True)
if (args.directory/"bin/javac").is_file():print(args.directory);raise SystemExit(0)
archive=args.directory.parent/"jdk.tar.gz"
with urllib.request.urlopen(url,timeout=120) as response,archive.open("wb") as target:
    while chunk:=response.read(1024*1024):target.write(chunk)
with archive.open("rb") as file:actual=hashlib.file_digest(file,"sha256").hexdigest()
if actual!=expected:raise SystemExit("JDK checksum mismatch.")
with tarfile.open(archive) as file:
    top=pathlib.PurePosixPath(file.getmembers()[0].name).parts[0]
    for member in file:
        parts=pathlib.PurePosixPath(member.name).parts
        if not parts or parts[0]!=top or ".." in parts:raise SystemExit("Unexpected JDK path.")
        if len(parts)==1:continue
        member.name=str(pathlib.PurePosixPath(*parts[1:]))
        file.extract(member,args.directory,filter="data")
print(args.directory)
