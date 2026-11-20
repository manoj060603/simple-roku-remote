#!/usr/bin/env python3
"""Simple Roku Remote. MIT licensed. No dependencies or persistent application data."""
import argparse
import base64
import collections
import hashlib
import hmac
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

VERSION = "0.1.0"
KEYS = frozenset(("Home Back Up Down Left Right Select Play Rev Fwd InstantReplay "
                 "Info VolumeUp VolumeDown VolumeMute PowerOn PowerOff "
                 "InputHDMI1 InputHDMI2 InputHDMI3 Backspace Search").split())
APP_ID = re.compile(r"[A-Za-z0-9._-]{1,80}\Z")
COOKIE_NAME = "roku_remote_session"
MAX_BODY = 4096
SESSION_SECONDS = 12 * 3600
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))

class RemoteError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)

def validate_tv_host(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError("Use the TV's local IPv4 address, not a URL or hostname.")
    if address.version != 4 or not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError("The TV address must be a private, non-loopback IPv4 address.")
    return str(address)

def local_address(tv_host):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((tv_host, 8060))
        return sock.getsockname()[0]

class RokuClient:
    def __init__(self, host, timeout=2.5):
        self.host = validate_tv_host(host)
        self.timeout = timeout
        self.lock = threading.Lock()
        self.cached_apps = []
        self.apps_at = 0.0

    def request(self, method, path):
        with self.lock:
            connection = http.client.HTTPConnection(self.host, 8060, timeout=self.timeout)
            try:
                connection.request(method, path, body=b"" if method == "POST" else None)
                response = connection.getresponse()
                content = response.read(262145)
                if response.status != 200 or len(content) > 262144:
                    raise RemoteError(502, "The TV did not accept that request.")
                return content
            except (OSError, http.client.HTTPException):
                raise RemoteError(503, "The TV is not responding. Check its power and Wi-Fi.")
            finally:
                connection.close()

    def xml(self, path):
        try:
            return ET.fromstring(self.request("GET", path))
        except ET.ParseError:
            raise RemoteError(502, "The TV returned an unreadable response.")

    def apps(self):
        if time.monotonic() - self.apps_at > 60 or not self.cached_apps:
            root = self.xml("/query/apps")
            items = []
            for item in root.findall("app"):
                app_id = item.get("id", "")
                if APP_ID.fullmatch(app_id) and item.get("type") != "tvin":
                    items.append({"id": app_id, "name": (item.text or "App")[:100]})
            self.cached_apps, self.apps_at = items, time.monotonic()
        return list(self.cached_apps)

    def status(self):
        info = self.xml("/query/device-info")
        active = self.xml("/query/active-app").find("app")
        return {
            "model": info.findtext("model-name", "Roku TV"),
            "power": info.findtext("power-mode", "Unknown"),
            "active": (active.text or "Home") if active is not None else "Home",
            "apps": self.apps(),
            "version": VERSION,
        }

    def key(self, key):
        if key not in KEYS:
            raise RemoteError(400, "That button is not supported.")
        self.request("POST", "/keypress/" + key)

    def launch(self, app_id):
        if not isinstance(app_id, str) or not APP_ID.fullmatch(app_id):
            raise RemoteError(400, "Choose an installed app.")
        if app_id not in {app["id"] for app in self.apps()}:
            raise RemoteError(400, "That app is not installed on this TV.")
        self.request("POST", "/launch/" + app_id)

    def send_text(self, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 80 or any(ord(c) < 32 for c in value):
            raise RemoteError(400, "Enter between 1 and 80 characters on one line.")
        deadline = time.monotonic() + 10
        count = 0
        for char in value:
            if time.monotonic() > deadline:
                raise RemoteError(504, "Text entry stopped after " + str(count) + " characters. Check the TV before retrying.")
            try:
                self.request("POST", "/keypress/Lit_" + quote(char, safe=""))
            except RemoteError:
                raise RemoteError(503, "Text entry stopped after " + str(count) + " characters. Check the TV before retrying.")
            count += 1
        return count

class RemoteState:
    def __init__(self, roku, code=None):
        self.roku = roku
        self.code = code or str(secrets.randbelow(1000000)).zfill(6)
        if not re.fullmatch(r"[0-9]{6}", self.code):
            raise ValueError("The pairing code must contain six digits.")
        self.lock = threading.Lock()
        self.sessions = {}
        self.attempts = {}
        self.requests = {}

    def pair(self, address, value):
        now = time.monotonic()
        with self.lock:
            self.attempts = {k: v for k, v in self.attempts.items() if now - v[-1] < 90}
            attempts = [t for t in self.attempts.get(address, []) if now - t < 90]
            if len(attempts) >= 5:
                raise RemoteError(429, "Too many attempts. Wait 90 seconds and try again.")
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{6}", value) or not hmac.compare_digest(self.code, value):
                if len(self.attempts) < 256 or address in self.attempts:
                    self.attempts[address] = attempts + [now]
                raise RemoteError(401, "Incorrect pairing code.")
            self.sessions = {k: v for k, v in self.sessions.items() if v > now}
            if len(self.sessions) >= 64:
                raise RemoteError(429, "Too many paired devices. Restart the remote to clear them.")
            token = secrets.token_urlsafe(32)
            self.sessions[token] = now + SESSION_SECONDS
            self.attempts.pop(address, None)
            return token

    def authenticated(self, header):
        cookie = SimpleCookie()
        try:
            cookie.load(header[:8192])
            token = cookie[COOKIE_NAME].value
        except Exception:
            return False
        with self.lock:
            return self.sessions.get(token, 0) > time.monotonic()

    def unpair(self, header):
        cookie = SimpleCookie()
        try:
            cookie.load(header[:8192])
            token = cookie[COOKIE_NAME].value
        except Exception:
            return
        with self.lock:
            self.sessions.pop(token, None)

    def throttle(self, address):
        now = time.monotonic()
        with self.lock:
            self.requests = {k: v for k, v in self.requests.items() if now - v[-1] < 10}
            recent = collections.deque(t for t in self.requests.get(address, []) if now - t < 10)
            if len(recent) >= 100 or (address not in self.requests and len(self.requests) >= 256):
                raise RemoteError(429, "Please wait a moment before pressing again.")
            recent.append(now)
            self.requests[address] = recent

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b1116"><meta name="color-scheme" content="dark"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="TV Remote"><title>Simple Roku Remote</title>
<style>
:root{font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#edf3f5;background:#0b1116;font-size:16px;--panel:#17232c;--line:#2a3944;--muted:#a9b7c1;--accent:#a4f1ce}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 50% 0,#1c3039 0,transparent 65%);min-height:100dvh}button,input,textarea{font:inherit}button{cursor:pointer;-webkit-tap-highlight-color:transparent;touch-action:manipulation;color:inherit}button:disabled{opacity:.45;cursor:wait}button:active{transform:scale(.96);background:#314653}button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid var(--accent);outline-offset:4px}button,a,input,textarea{-webkit-touch-callout:none}button svg{width:24px;height:24px;stroke:currentColor;stroke-width:1.8;fill:none;stroke-linecap:round;stroke-linejoin:round}.hidden{display:none!important}.shell{width:min(100%,460px);margin:auto;padding:24px 22px max(22px,env(safe-area-inset-bottom));min-height:100dvh}.brand{font-size:.75rem;letter-spacing:.19em;font-weight:750;color:#b6c6ce;margin:0 0 25px}.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:22px}h1{font-size:2rem;line-height:1.15;letter-spacing:-.06em;margin:0 0 8px;font-weight:650}p{line-height:1.5}.status{font-size:.875rem;color:var(--muted);margin:0;display:flex;align-items:center;gap:8px}.dot{width:7px;height:7px;flex:none;background:var(--accent);border-radius:50%}.dot.offline{background:#e5b176}.icon-button{width:52px;height:52px;border-radius:50%;background:var(--panel);border:1px solid var(--line);display:grid;place-items:center;flex:none}.power{color:var(--accent)}.tabs{display:flex;padding:5px;background:#111a21;border:1px solid var(--line);border-radius:16px;gap:3px;margin-bottom:24px}.tab{flex:1;border:0;border-radius:11px;background:transparent;padding:11px 4px;font-weight:650;font-size:.9rem;color:var(--muted)}.tab[aria-selected=true]{background:#2b3d48;color:#fff}.utility{display:flex;justify-content:space-between;gap:12px;max-width:300px;margin:0 auto 17px}.utility button{width:74px;height:47px;border:1px solid var(--line);border-radius:16px;background:var(--panel);display:grid;place-items:center}.pad{width:266px;height:266px;display:grid;grid-template:repeat(3,1fr)/repeat(3,1fr);gap:3px;margin:auto;padding:13px;border:1px solid #364b58;border-radius:50%;background:linear-gradient(145deg,#273b46,#14212a);box-shadow:0 15px 35px #0005}.pad button{border:0;background:transparent;border-radius:30px;display:grid;place-items:center}.pad button:active{background:#3d5663}.pad .select{background:var(--accent);color:#12251f;box-shadow:0 3px 16px #0003;font-size:1.12rem;font-weight:800;border-radius:50%;margin:4px}.pad svg{width:27px;height:27px;stroke-width:2.3}.up{grid-area:1/2}.left{grid-area:2/1}.select{grid-area:2/2}.right{grid-area:2/3}.down{grid-area:3/2}.volume{display:grid;grid-template-columns:1fr 1.15fr 1fr;max-width:300px;margin:23px auto 15px;background:var(--panel);border:1px solid var(--line);border-radius:18px;overflow:hidden}.volume button{display:flex;align-items:center;justify-content:center;gap:8px;height:56px;border:0;background:transparent}.volume .mute{border-left:1px solid var(--line);border-right:1px solid var(--line);font-size:.875rem}.media{display:flex;justify-content:center;gap:15px;margin:0 0 27px}.media button{height:49px;width:76px;background:transparent;border:1px solid var(--line);border-radius:16px;display:grid;place-items:center}.media .play{background:#273b46;border-color:#3c5361}.section-label{font-size:.75rem;color:var(--muted);font-weight:650;letter-spacing:.14em;text-transform:uppercase;margin:0 0 12px}.shortcuts,.app-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.app-grid{grid-template-columns:repeat(2,1fr)}.app-button{border:1px solid var(--line);background:var(--panel);border-radius:16px;min-height:64px;padding:14px 8px;font-size:.875rem;line-height:1.3;font-weight:700;overflow-wrap:anywhere}.app-button.youtube{color:#ffaaa5}.app-button.netflix{color:#ff7685}.app-button.prime{color:#9bd7ff}.inputs{display:flex;gap:8px;margin:12px 0 25px}.inputs button{flex:1;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 4px;font-size:.875rem}.hint{color:var(--muted);font-size:.875rem;line-height:1.6;margin:17px 0}.pair-card{margin-top:11vh;padding:26px 23px;border:1px solid #354b56;border-radius:25px;background:#14222bea;box-shadow:0 25px 65px #0004}.pair-card h1{font-size:2rem}.pair-card p{color:var(--muted);font-size:.95rem}.pair-card label{font-size:.875rem;font-weight:650;display:block;margin:28px 0 10px}.pair-card input{display:block;width:100%;border-radius:14px;border:1px solid #3a5260;background:#0c171e;color:#edf3f5;padding:17px 12px;text-align:center;letter-spacing:.35em;font-size:1.85rem;font-weight:650;min-height:72px}.primary{width:100%;padding:16px;background:var(--accent);color:#14291f;font-weight:750;border-radius:14px;border:0;margin-top:17px;min-height:54px}.error{color:#ffc0b7!important;min-height:22px;font-size:.875rem!important}textarea{width:100%;height:155px;padding:16px;border:1px solid #415663;background:#13212a;border-radius:17px;color:#edf3f5;resize:vertical;font-size:1.05rem}.text-actions{display:flex;gap:10px;margin-top:12px}.text-actions button{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 18px;flex:1}.text-actions .primary{margin:0;background:var(--accent);color:#14291f}.footer{display:flex;justify-content:space-between;gap:10px;margin:29px 0 0;color:var(--muted);font-size:.75rem}.footer a,.link-button{color:var(--muted);text-decoration:none}.link-button{border:0;background:none;padding:0;font-size:.75rem}.toast{position:fixed;bottom:max(20px,env(safe-area-inset-bottom));left:50%;transform:translateX(-50%);width:max-content;max-width:calc(100vw - 32px);padding:13px 18px;background:#edf3f5;color:#12232b;border-radius:14px;box-shadow:0 8px 30px #0005;font-size:.875rem;z-index:10;pointer-events:none;text-align:center}.empty{color:var(--muted);font-size:.95rem;grid-column:1/-1}.refresh{margin:0 0 18px;color:var(--accent);border:1px solid var(--line);background:var(--panel);padding:10px 16px;border-radius:12px}
@media(max-height:760px){.shell{padding-top:18px}.brand{margin-bottom:18px}.head{margin-bottom:18px}.tabs{margin-bottom:18px}.pad{width:238px;height:238px}.volume{margin-top:18px}.media{margin-bottom:21px}.footer{margin-top:23px}}
@media(prefers-reduced-motion:no-preference){button{transition:background .12s,transform .1s}}
</style></head><body>
<svg style="display:none" aria-hidden="true"><defs>
<symbol id="i-up" viewBox="0 0 24 24"><path d="m6 15 6-6 6 6"/></symbol>
<symbol id="i-down" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>
<symbol id="i-left" viewBox="0 0 24 24"><path d="m15 6-6 6 6 6"/></symbol>
<symbol id="i-right" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></symbol>
<symbol id="i-power" viewBox="0 0 24 24"><path d="M12 3v8m-5-5a8 8 0 1 0 10 0"/></symbol>
<symbol id="i-home" viewBox="0 0 24 24"><path d="m3 11 9-8 9 8M6 9v12h12V9M10 21v-7h4v7"/></symbol>
<symbol id="i-back" viewBox="0 0 24 24"><path d="m9 5-7 7 7 7M3 12h12a5 5 0 0 1 5 5"/></symbol>
<symbol id="i-more" viewBox="0 0 24 24"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></symbol>
<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
<symbol id="i-minus" viewBox="0 0 24 24"><path d="M5 12h14"/></symbol>
<symbol id="i-mute" viewBox="0 0 24 24"><path d="M11 4 6 8H3v8h3l5 4V4m5 5 5 6m0-6-5 6"/></symbol>
<symbol id="i-play" viewBox="0 0 24 24"><path d="m4 5 10 7-10 7V5M18 5v14M22 5v14"/></symbol>
<symbol id="i-rew" viewBox="0 0 24 24"><path d="m11 5-9 7 9 7V5m11 0-9 7 9 7V5"/></symbol>
<symbol id="i-fwd" viewBox="0 0 24 24"><path d="m2 5 9 7-9 7V5m11 0 9 7-9 7V5"/></symbol>
</defs></svg>
<main class="shell">
<p class="brand">SIMPLE ROKU REMOTE</p>
<section id="pair-view">
<form class="pair-card" id="pair-form">
<h1>TV time.<br>Remote optional.</h1>
<p>Pair your phone and settle in.</p>
<label for="pair-code">Six-digit pairing code</label>
<input id="pair-code" name="code" type="password" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" required aria-describedby="pair-help pair-error">
<button class="primary" type="submit" id="pair-button">Connect to TV</button>
<p id="pair-error" class="error" role="alert"></p>
<p class="hint" id="pair-help">Use the code shown on your Mac. Keep your phone, Mac, and TV on the same Wi-Fi.</p>
</form>
</section>
<section id="remote-view" class="hidden">
<header class="head"><div><h1>Living room</h1><p class="status" role="status"><span class="dot" id="status-dot"></span><span id="connection-label">Connecting</span></p></div><button class="icon-button power" id="power" aria-label="Turn TV off"><svg><use href="#i-power"/></svg></button></header>
<div class="tabs" role="tablist" aria-label="Remote sections">
<button class="tab" id="tab-remote" role="tab" aria-selected="true" aria-controls="panel-remote" data-tab="remote">Remote</button>
<button class="tab" id="tab-apps" role="tab" aria-selected="false" aria-controls="panel-apps" data-tab="apps">Apps</button>
<button class="tab" id="tab-type" role="tab" aria-selected="false" aria-controls="panel-type" data-tab="type">Type</button>
</div>
<section id="panel-remote" role="tabpanel" aria-labelledby="tab-remote">
<div class="utility"><button data-key="Back" aria-label="Back"><svg><use href="#i-back"/></svg></button><button data-key="Home" aria-label="Home"><svg><use href="#i-home"/></svg></button><button data-key="Info" aria-label="Options"><svg><use href="#i-more"/></svg></button></div>
<div class="pad" aria-label="Directional controls">
<button class="up" data-key="Up" aria-label="Up"><svg><use href="#i-up"/></svg></button><button class="left" data-key="Left" aria-label="Left"><svg><use href="#i-left"/></svg></button><button class="select" data-key="Select" aria-label="Select">OK</button><button class="right" data-key="Right" aria-label="Right"><svg><use href="#i-right"/></svg></button><button class="down" data-key="Down" aria-label="Down"><svg><use href="#i-down"/></svg></button>
</div>
<div class="volume"><button data-key="VolumeDown" aria-label="Volume down"><svg><use href="#i-minus"/></svg></button><button class="mute" data-key="VolumeMute" aria-label="Mute"><svg><use href="#i-mute"/></svg><span>Mute</span></button><button data-key="VolumeUp" aria-label="Volume up"><svg><use href="#i-plus"/></svg></button></div>
<div class="media"><button data-key="Rev" aria-label="Rewind"><svg><use href="#i-rew"/></svg></button><button class="play" data-key="Play" aria-label="Play or pause"><svg><use href="#i-play"/></svg></button><button data-key="Fwd" aria-label="Fast forward"><svg><use href="#i-fwd"/></svg></button></div>
<p class="section-label">A little less browsing</p><div class="shortcuts" id="shortcuts"></div>
</section>
<section id="panel-apps" class="hidden" role="tabpanel" aria-labelledby="tab-apps">
<p class="section-label">TV inputs</p><div class="inputs"><button data-key="InputHDMI1">HDMI 1</button><button data-key="InputHDMI2">HDMI 2</button><button data-key="InputHDMI3">HDMI 3</button></div>
<p class="section-label">Your installed apps</p><div id="app-grid" class="app-grid"></div>
</section>
<section id="panel-type" class="hidden" role="tabpanel" aria-labelledby="tab-type">
<p class="hint">Select a search or text field on the TV, then type here. Text entry depends on the TV app.</p>
<label for="tv-text" class="section-label" style="display:block">Send text to TV</label>
<textarea id="tv-text" maxlength="80" rows="4" placeholder="What would you like to watch?" autocomplete="off" autocapitalize="off" spellcheck="false"></textarea>
<div class="text-actions"><button data-key="Backspace">Delete</button><button class="primary" id="send-text">Send text</button></div>
<p class="hint">Up to 80 characters. Text is sent to the TV and is not saved.</p>
</section>
<footer class="footer"><a href="https://github.com/manoj060603/simple-roku-remote" target="_blank" rel="noopener noreferrer">Open source · MIT</a><button id="unpair" class="link-button">Disconnect phone</button></footer>
<p class="hint" style="font-size:.75rem;margin-top:14px">Keep this Mac awake while using the remote.</p>
</section>
</main><div id="toast" class="toast hidden" role="status"></div>
<script>
"use strict";
const byId=function(id){return document.getElementById(id);};
const state={paired:false,power:"Unknown",apps:[],busy:Promise.resolve(),queued:0,toast:null};
async function api(path,body){
 const controller=new AbortController();
 const timeout=setTimeout(function(){controller.abort();},path==="text"?16000:12000);
 let response,result;
 try{response=await fetch("/api/"+path,{method:body===undefined?"GET":"POST",credentials:"same-origin",headers:body===undefined?{}:{"Content-Type":"application/json","X-Remote-Request":"1"},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});result=await response.json();}
 catch(error){if(error.name==="AbortError")throw new Error("Connection timed out. Check the TV before retrying.");throw error;}
 finally{clearTimeout(timeout);}
 if(!response.ok){const error=new Error(result.error||"Please try again.");error.status=response.status;throw error;}
 return result;
}
function toast(message){byId("toast").textContent=message;byId("toast").classList.remove("hidden");clearTimeout(state.toast);state.toast=setTimeout(function(){byId("toast").classList.add("hidden");},2800);}
function showPaired(value){state.paired=value;byId("pair-view").classList.toggle("hidden",value);byId("remote-view").classList.toggle("hidden",!value);}
function offline(){byId("connection-label").textContent="TV unavailable · check Wi-Fi";byId("status-dot").classList.add("offline");}
function appStyle(name){const n=name.toLowerCase();return n.includes("youtube")?"youtube":n.includes("netflix")?"netflix":n.includes("prime")?"prime":"";}
function appButton(app){const button=document.createElement("button");button.className="app-button "+appStyle(app.name);button.textContent=app.name;button.addEventListener("click",function(){enqueue(async function(){await api("launch",{id:app.id});toast("Opening "+app.name);});});return button;}
function renderApps(){
 const grid=byId("app-grid");grid.replaceChildren();state.apps.forEach(function(app){grid.appendChild(appButton(app));});
 const shortcuts=byId("shortcuts");shortcuts.replaceChildren();
 ["youtube","netflix","prime"].forEach(function(name){const app=state.apps.find(function(item){return item.name.toLowerCase().includes(name);});if(app)shortcuts.appendChild(appButton(app));});
 if(!state.apps.length){const empty=document.createElement("p");empty.className="empty";empty.textContent="No apps found. Check the TV connection.";grid.appendChild(empty);}
}
async function refresh(){
 try{const info=await api("status");showPaired(true);state.power=info.power;byId("connection-label").textContent=(info.power==="PowerOn"?"Connected":"Standby")+" · "+info.model;byId("status-dot").classList.remove("offline");byId("power").setAttribute("aria-label",info.power==="PowerOn"?"Turn TV off":"Turn TV on");const signature=JSON.stringify(info.apps);if(signature!==JSON.stringify(state.apps)){state.apps=info.apps;renderApps();}}
 catch(error){if(error.status===401)showPaired(false);else if(error.status===502||error.status===503){showPaired(true);offline();}else if(state.paired)offline();}
}
function enqueue(action){
 if(state.queued>=6){toast("Let the TV catch up for a moment.");return false;}
 state.queued++;
 state.busy=state.busy.then(action).catch(function(error){if(error.status===401)showPaired(false);toast(error.name==="TimeoutError"?"Connection timed out. Check the TV before retrying.":error.message||"Check the Mac and Wi-Fi connection.");}).finally(function(){state.queued--;});
 return true;
}
function key(value){if(navigator.vibrate)navigator.vibrate(9);enqueue(function(){return api("key",{key:value});});}
document.querySelectorAll("[data-key]").forEach(function(button){button.addEventListener("click",function(){key(button.dataset.key);});});
document.querySelectorAll("[data-tab]").forEach(function(button){button.addEventListener("click",function(){document.querySelectorAll("[data-tab]").forEach(function(tab){tab.setAttribute("aria-selected",String(tab===button));});["remote","apps","type"].forEach(function(name){byId("panel-"+name).classList.toggle("hidden",name!==button.dataset.tab);});});});
byId("pair-form").addEventListener("submit",async function(event){event.preventDefault();byId("pair-button").disabled=true;byId("pair-error").textContent="";try{await api("pair",{code:byId("pair-code").value});byId("pair-code").value="";showPaired(true);await refresh();}catch(error){byId("pair-error").textContent=error.message||"Could not connect. Check the Mac and Wi-Fi.";}finally{byId("pair-button").disabled=false;}});
byId("power").addEventListener("click",function(){enqueue(async function(){const value=state.power==="PowerOn"?"PowerOff":"PowerOn";await api("key",{key:value});state.power=value==="PowerOn"?"PowerOn":"Ready";byId("power").setAttribute("aria-label",state.power==="PowerOn"?"Turn TV off":"Turn TV on");byId("connection-label").textContent=value==="PowerOn"?"Waking the TV…":"Standby";setTimeout(refresh,1200);});});
byId("send-text").addEventListener("click",function(){const input=byId("tv-text");if(!input.value.trim()){toast("Type something first.");return;}const value=input.value;byId("send-text").disabled=true;const accepted=enqueue(async function(){try{const result=await api("text",{text:value});if(input.value===value)input.value="";toast("Sent "+result.sent+" characters.");}finally{byId("send-text").disabled=false;}});if(!accepted)byId("send-text").disabled=false;});
byId("unpair").addEventListener("click",function(){enqueue(async function(){await api("unpair",{});showPaired(false);});});
document.addEventListener("keydown",function(event){if(!state.paired||/INPUT|TEXTAREA/.test(event.target.tagName)||event.ctrlKey||event.metaKey||event.altKey)return;const map={ArrowUp:"Up",ArrowDown:"Down",ArrowLeft:"Left",ArrowRight:"Right",Enter:"Select",Escape:"Back"," ":"Play"};if(map[event.key]){event.preventDefault();key(map[event.key]);}});
document.addEventListener("visibilitychange",function(){if(!document.hidden)refresh();});
setInterval(function(){if(state.paired&&!document.hidden&&state.queued===0)refresh();},20000);
refresh();
</script></body></html>"""

SCRIPT = re.search(r"<script>(.*?)</script>", PAGE, re.S).group(1)
SCRIPT_HASH = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
CSP = ("default-src 'self'; script-src 'sha256-" + SCRIPT_HASH + "'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

class RemoteServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, address, state):
        super().__init__(address, RemoteHandler)
        self.state = state
        host, port = self.server_address
        self.allowed_hosts = {host + ":" + str(port)}
        if host == "127.0.0.1":
            self.allowed_hosts.add("localhost:" + str(port))

class RemoteHandler(BaseHTTPRequestHandler):
    server_version = "SimpleRokuRemote/" + VERSION
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        pass

    def send_bytes(self, status, body, content_type="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, status, value, extra=None):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode(), extra=extra)

    def check_host(self):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            raise RemoteError(400, "Open the remote using the address shown on the Mac.")

    def require_auth(self):
        if not self.server.state.authenticated(self.headers.get("Cookie", "")):
            raise RemoteError(401, "Pair this phone to continue.")

    def read_json(self):
        if self.headers.get("X-Remote-Request") != "1":
            raise RemoteError(403, "Open the remote page to use these controls.")
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.netloc != self.headers.get("Host"):
                raise RemoteError(403, "This request came from another site.")
        if self.headers.get_content_type() != "application/json":
            raise RemoteError(415, "Use a JSON request.")
        if self.headers.get("Transfer-Encoding"):
            raise RemoteError(400, "Invalid request encoding.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise RemoteError(400, "Invalid request length.")
        if not 0 < length <= MAX_BODY:
            raise RemoteError(413, "Request is too large or empty.")
        self.connection.settimeout(5)
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, OSError):
            raise RemoteError(400, "Invalid request.")
        if not isinstance(data, dict):
            raise RemoteError(400, "Use a JSON object.")
        return data

    def do_GET(self):
        try:
            self.check_host()
            path = urlsplit(self.path).path
            if path == "/":
                return self.send_bytes(200, PAGE.encode(), "text/html; charset=utf-8")
            if path == "/favicon.ico":
                return self.send_bytes(204, b"", "image/x-icon")
            if path != "/api/status":
                raise RemoteError(404, "Not found.")
            self.require_auth()
            self.server.state.throttle(self.client_address[0])
            self.send_json(200, self.server.state.roku.status())
        except RemoteError as error:
            self.send_json(error.status, {"error": error.message})

    def do_POST(self):
        try:
            self.check_host()
            path = urlsplit(self.path).path
            if path not in {"/api/pair", "/api/key", "/api/launch", "/api/text", "/api/unpair"}:
                raise RemoteError(404, "Not found.")
            data = self.read_json()
            state = self.server.state
            if path == "/api/pair":
                token = state.pair(self.client_address[0], data.get("code"))
                return self.send_json(200, {"paired": True}, {"Set-Cookie": COOKIE_NAME + "=" + token + "; HttpOnly; SameSite=Strict; Path=/; Max-Age=" + str(SESSION_SECONDS)})
            self.require_auth()
            state.throttle(self.client_address[0])
            if path == "/api/key":
                value = data.get("key")
                if not isinstance(value, str) or value not in KEYS:
                    raise RemoteError(400, "That button is not supported.")
                state.roku.key(value)
            elif path == "/api/launch":
                state.roku.launch(data.get("id"))
            elif path == "/api/text":
                return self.send_json(200, {"sent": state.roku.send_text(data.get("text"))})
            elif path == "/api/unpair":
                state.unpair(self.headers.get("Cookie", ""))
                return self.send_json(200, {"paired": False}, {"Set-Cookie": COOKIE_NAME + "=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            self.send_json(200, {"ok": True})
        except RemoteError as error:
            self.send_json(error.status, {"error": error.message})

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tv-host", required=True, help="TV's private IPv4 address")
    parser.add_argument("--bind", help="Local interface address; default: interface that reaches TV")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--keep-awake", action="store_true", help="Prevent idle sleep while running on macOS")
    parser.add_argument("--json", action="store_true", help="Print machine-readable startup information")
    args = parser.parse_args(argv)
    try:
        host = validate_tv_host(args.tv_host)
        bind = args.bind or local_address(host)
        address = ipaddress.ip_address(bind)
        if address.version != 4 or not (address.is_loopback or any(address in network for network in PRIVATE_NETWORKS)):
            raise ValueError("Bind to a local private IPv4 address.")
        state = RemoteState(RokuClient(host))
        server = RemoteServer((str(address), args.port), state)
    except (ValueError, OSError) as error:
        parser.exit(2, "Could not start: " + str(error) + "\n")
    url = "http://" + str(address) + ":" + str(server.server_port)
    awake = None
    if args.keep_awake and os.path.isfile("/usr/bin/caffeinate"):
        awake = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if args.json:
        print(json.dumps({"url": url, "pairing_code": state.code, "pid": os.getpid(), "version": VERSION}), flush=True)
    else:
        print("\nSimple Roku Remote " + VERSION + "\nOpen on your phone: " + url + "\nPairing code: " + state.code + "\nKeep this computer awake. Press Ctrl+C to stop.\n", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if awake is not None:
            awake.terminate()

if __name__ == "__main__":
    main()
