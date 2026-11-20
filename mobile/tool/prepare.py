#!/usr/bin/env python3
"""Generate pinned Flutter platform shells, then apply tracked application inputs."""
import argparse,json,pathlib,plistlib,shutil,struct,subprocess,zlib
ANDROID="http://schemas.android.com/apk/res/android"
def icon_png(size):
    pixels=bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            u,v=(x+.5)/size,(y+.5)/size
            frame=(.16<u<.84 and .21<v<.65 and not (.21<u<.79 and .26<v<.60))
            stand=(.47<u<.53 and .65<v<.74) or (.34<u<.66 and .74<v<.79)
            play=.40<u<.64 and abs(v-.43)<(.64-u)*.70
            pixels.extend((164,241,206) if frame or stand or play else (11,17,22))
    def chunk(name,data):return struct.pack(">I",len(data))+name+data+struct.pack(">I",zlib.crc32(name+data)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",size,size,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(bytes(pixels),9))+chunk(b"IEND",b"")

def prepare(source,dest,flutter):
    import xml.etree.ElementTree as ET
    if source.resolve()==dest.resolve():raise SystemExit("Choose a separate generated-project directory.")
    if dest.exists() and any(dest.iterdir()) and not (dest/".simple-roku-generated").exists():
        raise SystemExit("Destination is not an owned generated project.")
    dest.mkdir(parents=True,exist_ok=True)
    if not (dest/"android").exists() or not (dest/"ios").exists():
        subprocess.run([flutter,"create","--platforms=android,ios","--project-name=simplerokuremote","--org=io.github.manoj060603","--no-pub",str(dest)],check=True)
    (dest/".simple-roku-generated").touch()
    for name in ["lib","test"]:
        target=dest/name
        if target.exists():shutil.rmtree(target)
        shutil.copytree(source/name,target)
    for name in ["pubspec.yaml","pubspec.lock"]:
        if (source/name).exists():shutil.copy2(source/name,dest/name)
    ET.register_namespace("android",ANDROID)
    manifest=dest/"android/app/src/main/AndroidManifest.xml"
    tree=ET.parse(manifest);root=tree.getroot()
    permission="{"+ANDROID+"}name"
    if not any(x.get(permission)=="android.permission.INTERNET" for x in root.findall("uses-permission")):
        ET.SubElement(root,"uses-permission",{permission:"android.permission.INTERNET"})
    application=root.find("application")
    application.set("{"+ANDROID+"}label","Simple Roku Remote")
    application.set("{"+ANDROID+"}networkSecurityConfig","@xml/network_security_config")
    application.set("{"+ANDROID+"}allowBackup","false")
    tree.write(manifest,encoding="utf-8",xml_declaration=True)
    config=dest/"android/app/src/main/res/xml/network_security_config.xml"
    config.parent.mkdir(parents=True,exist_ok=True)
    config.write_text('<?xml version="1.0" encoding="utf-8"?><network-security-config><base-config cleartextTrafficPermitted="true"/></network-security-config>')
    gradle=dest/"android/app/build.gradle.kts"
    content=gradle.read_text().replace("compileSdk = flutter.compileSdkVersion","compileSdk = 36").replace("targetSdk = flutter.targetSdkVersion","targetSdk = 36")
    content=content.replace('android {', 'val rokuKeystore = System.getenv("ROKU_KEYSTORE")\n\nandroid {\n    signingConfigs {\n        if (rokuKeystore != null) {\n            create("personal") {\n                storeFile = file(rokuKeystore)\n                storePassword = System.getenv("ROKU_STORE_PASSWORD")\n                keyAlias = "roku"\n                keyPassword = System.getenv("ROKU_STORE_PASSWORD")\n            }\n        }\n    }\n',1)
    content=content.replace('signingConfigs.getByName("debug")','signingConfigs.getByName(if (rokuKeystore != null) "personal" else "debug")')
    gradle.write_text(content)
    plist=dest/"ios/Runner/Info.plist"
    with plist.open("rb") as file: info=plistlib.load(file)
    info["CFBundleDisplayName"]="Simple Roku Remote"
    info["NSLocalNetworkUsageDescription"]="Connect directly to your Roku TV over Wi-Fi so you can control it without a laptop."
    info["NSAppTransportSecurity"]={"NSAllowsLocalNetworking":True}
    with plist.open("wb") as file:plistlib.dump(info,file,sort_keys=False)
    for folder,size in [("mdpi",48),("hdpi",72),("xhdpi",96),("xxhdpi",144),("xxxhdpi",192)]:
        path=dest/("android/app/src/main/res/mipmap-"+folder+"/ic_launcher.png")
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(icon_png(size))
    catalog=dest/"ios/Runner/Assets.xcassets/AppIcon.appiconset"
    for entry in json.loads((catalog/"Contents.json").read_text())["images"]:
        if "filename" in entry:
            size=round(float(entry["size"].split("x")[0])*float(entry.get("scale","1x")[:-1]))
            (catalog/entry["filename"]).write_bytes(icon_png(size))
    for path in (dest/"android/app/src/main/res").glob("drawable*/launch_background.xml"):
        path.write_text(path.read_text().replace("@android:color/white","#0b1116"))
    properties=dest/"android/gradle.properties"
    value=properties.read_text()
    if "org.gradle.workers.max" not in value:value+="\norg.gradle.workers.max=4\n"
    properties.write_text(value)
    print("Prepared "+str(dest))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("destination",type=pathlib.Path)
    parser.add_argument("--flutter",default=shutil.which("flutter") or "flutter")
    args=parser.parse_args()
    prepare(pathlib.Path(__file__).resolve().parents[1],args.destination,args.flutter)
