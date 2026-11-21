#!/usr/bin/env python3
"""Run checks and build on an ARC/other Linux worker, never on the phone user's laptop."""
import argparse,hashlib,json,os,pathlib,secrets,shutil,subprocess,sys
from prepare import prepare
parser=argparse.ArgumentParser()
parser.add_argument("--work",required=True,type=pathlib.Path)
parser.add_argument("--flutter",required=True)
parser.add_argument("--android-sdk",required=True,type=pathlib.Path)
parser.add_argument("--check-only",action="store_true")
parser.add_argument("--java-home",type=pathlib.Path)
args=parser.parse_args()
source=pathlib.Path(__file__).resolve().parents[1]
work=args.work.resolve();work.mkdir(parents=True,exist_ok=True)
project=work/"app"
prepare(source,project,args.flutter)
env=os.environ.copy()
env.update({"ANDROID_HOME":str(args.android_sdk),"ANDROID_SDK_ROOT":str(args.android_sdk),"PUB_CACHE":str(work/"pub-cache"),"GRADLE_USER_HOME":str(work/"gradle-cache"),"CI":"true","FLUTTER_SUPPRESS_ANALYTICS":"true","ROKU_FLUTTER_SDK":str(pathlib.Path(args.flutter).resolve().parents[1])})
if args.java_home:env["JAVA_HOME"]=str(args.java_home)
def run(command):subprocess.run(command,cwd=project,env=env,check=True)
run([args.flutter,"pub","get"])
dart=str(pathlib.Path(args.flutter).with_name("dart"))
if args.check_only:run([dart,"format","lib","test"])
run([args.flutter,"test","--reporter","expanded","--dart-define=CAPTURE_SCREENSHOTS=true"])
if args.check_only:
    for name in ["lib","test"]:
        for file in (project/name).rglob("*.dart"):
            target=source/file.relative_to(project);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
    shutil.copy2(project/"pubspec.lock",source/"pubspec.lock")
    raise SystemExit(0)
signing=pathlib.Path.home()/".local/share/simple-roku-remote-signing"
signing.mkdir(mode=0o700,parents=True,exist_ok=True)
password_file=signing/"password.txt"
if not password_file.exists():
    password_file.write_text(secrets.token_urlsafe(32));password_file.chmod(0o600)
key=signing/"personal.jks"
env["ROKU_KEYSTORE"]=str(key)
env["ROKU_STORE_PASSWORD"]=password_file.read_text().strip()
if not key.exists():
    subprocess.run(["keytool","-genkeypair","-keystore",str(key),"-alias","roku","-keyalg","RSA","-keysize","3072","-validity","10000","-dname","CN=Simple Roku Remote","-storepass:env","ROKU_STORE_PASSWORD","-keypass:env","ROKU_STORE_PASSWORD"],env=env,check=True)
    key.chmod(0o600)
run([args.flutter,"build","apk","--release"])
out=work/"artifacts";out.mkdir(exist_ok=True)
apk=out/"simple-roku-remote-android.apk"
shutil.copy2(project/"build/app/outputs/flutter-apk/app-release.apk",apk)
for image in (project/"screenshots").glob("*.png"):shutil.copy2(image,out/image.name)
commit=subprocess.check_output(["git","-C",str(source.parent),"rev-parse","HEAD"],text=True).strip()
hashes={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(out.iterdir()) if file.is_file() and file.suffix in {".png",".apk"}}
(out/"SHA256SUMS").write_text("".join(value+"  "+name+"\n" for name,value in hashes.items()))
(out/"manifest.json").write_text(json.dumps({"version":"0.2.0","source_commit":commit,"files":hashes},indent=2)+"\n")
print(json.dumps({"built":str(apk),"bytes":apk.stat().st_size,"source_commit":commit,"sha256":hashes[apk.name]}),flush=True)
