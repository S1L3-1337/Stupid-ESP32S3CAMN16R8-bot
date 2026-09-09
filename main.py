import time
import ntptime
import network
import uasyncio
import ujson
import logger
import aiohttp
import urequests
import jpeg
import os
import gc
import esp32
from machine import WDT, soft_reset
from camera import Camera, PixelFormat, FrameSize, GrabMode
from machine import RTC, reset, lightsleep, reset_cause, deepsleep
from logger import original_print
from microdot import Microdot
from microdot.websocket import with_websocket

cam = Camera(
    data_pins=[11, 9, 8, 10, 12, 18, 17, 16],
    vsync_pin=6, href_pin=7, sda_pin=4, scl_pin=5,
    pclk_pin=13, xclk_pin=15,
    xclk_freq=20000000,
    powerdown_pin=-1, reset_pin=-1,
    pixel_format=PixelFormat.RGB565,
    frame_size=FrameSize.VGA,
    fb_count=2,
    grab_mode=GrabMode.LATEST,
    init=False
)
cam.init()
time.sleep(5)

enc = jpeg.Encoder(
    width=640,
    height=480,
    pixel_format="RGB565_BE",
    quality=85,
    rotation=0
)

def capture_image():
    frame = cam.capture()
    if frame:
        rgb565_bytes = bytes(frame)
        print(f"[INFO] [CAM] Captured {len(rgb565_bytes)} bytes of raw RGB565")
        jpeg = enc.encode(rgb565_bytes)
        print(f"[INFO] [CAM] file encoded Successfully! image size: {len(jpeg)} bytes")
        cam.free_buffer()
        now = time.gmtime()
        return jpeg, "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            now[0], now[1], now[2], now[3], now[4], now[5]
        )
    else:
        print("[ERROR] [CAM] capture failed...")
        return None


app = Microdot()
print = logger.custom_log_print

@app.route('/')
async def index(request):
    html_page = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ESP32-S3 Control Center</title>
    <style>
        :root {
            --bg-primary: #0f1115; --bg-secondary: #161b22; --bg-terminal: #0d1117;
            --text-primary: #c9d1d9; --text-secondary: #8b949e; --accent-primary: #58a6ff;
            --accent-success: #2ea043; --accent-warning: #d29922; --accent-danger: #da3633;
            --border-color: #30363d;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background-color: var(--bg-primary); color: var(--text-primary); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 20px; line-height: 1.5; }
        .container { max-width: 1000px; margin: 0 auto; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 1px solid var(--border-color); }
        h1 { font-size: 1.5rem; font-weight: 600; color: #ffffff; }
        h3 { font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); margin-bottom: 12px; }
        .status-badge { padding: 6px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--accent-danger); transition: all 0.3s ease; }
        .status-badge.connected { color: var(--accent-success); border-color: var(--accent-success); }
        .dashboard { display: grid; grid-template-columns: 300px 1fr; gap: 20px; }
        @media (max-width: 768px) { .dashboard { grid-template-columns: 1fr; } }
        .control-panel { background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 8px; padding: 20px; height: fit-content; }
        .button-grid { display: grid; gap: 10px; margin-bottom: 24px; }
        .input-group { margin-bottom: 16px; }
        .input-group label { display: block; font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 6px; }
        .input-row { display: flex; gap: 8px; }
        input[type="number"] { flex: 1; background: var(--bg-primary); border: 1px solid var(--border-color); color: var(--text-primary); padding: 8px 12px; border-radius: 6px; font-family: monospace; font-size: 0.9rem; }
        input[type="number"]:focus { outline: none; border-color: var(--accent-primary); }
        button { width: 100%; padding: 10px 16px; border: 1px solid transparent; border-radius: 6px; font-weight: 600; font-size: 0.9rem; cursor: pointer; transition: all 0.2s ease; display: flex; align-items: center; justify-content: center; gap: 8px; }
        button:active { transform: translateY(1px); }
        .btn-primary { background: var(--accent-primary); color: #ffffff; }
        .btn-primary:hover { background: #79c0ff; }
        .btn-success { background: var(--accent-success); color: #ffffff; }
        .btn-warning { background: var(--accent-warning); color: #ffffff; }
        .btn-danger { background: var(--accent-danger); color: #ffffff; }
        .btn-secondary { background: var(--bg-primary); border-color: var(--border-color); color: var(--text-primary); }
        .btn-secondary:hover { background: var(--border-color); }
        .terminal-container { background: var(--bg-terminal); border: 1px solid var(--border-color); border-radius: 8px; display: flex; flex-direction: column; height: 60vh; overflow: hidden; }
        .terminal-header { background: var(--bg-secondary); padding: 10px 15px; border-bottom: 1px solid var(--border-color); font-size: 0.85rem; color: var(--text-secondary); display: flex; justify-content: space-between; align-items: center; }
        #terminal { flex: 1; padding: 15px; overflow-y: auto; font-family: 'Courier New', Courier, monospace; font-size: 0.85rem; line-height: 1.6; color: #e6edf3; }
        #terminal::-webkit-scrollbar { width: 8px; }
        #terminal::-webkit-scrollbar-track { background: var(--bg-terminal); }
        #terminal::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
        .log-line { margin: 2px 0; word-break: break-all; white-space: pre-wrap; }
        .log-line.error { color: var(--accent-danger); }
        .log-line.warn { color: var(--accent-warning); }
        .log-line.info { color: var(--accent-primary); }
        .log-line.cmd { color: var(--accent-success); font-style: italic; }
        .image-preview { margin-top: 20px; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 8px; padding: 15px; text-align: center; }
        .image-preview img { max-width: 100%; border-radius: 4px; border: 1px solid var(--border-color); display: none; }
        .image-preview p { color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎥 ESP32-S3 Control Center</h1>
            <span id="status" class="status-badge">Disconnected</span>
        </header>
        <div class="dashboard">
            <div class="control-panel">
                <h3>System Controls</h3>
                <div class="button-grid">
                    <button class="btn-primary" onclick="sendCommand('!capture')">📸 Trigger Capture</button>
                    <button class="btn-warning" onclick="sendCommand('!sreset')">🔄 Soft Reset</button>
                    <button class="btn-danger" onclick="sendCommand('!hreset')">⚠️ Hard Reset</button>
                </div>
                <h3>Sleep Controls</h3>
                <div class="input-group">
                    <label>Duration (milliseconds)</label>
                    <div class="input-row">
                        <input type="number" id="sleepDuration" value="30000" min="1000" step="1000">
                    </div>
                </div>
                <div class="button-grid">
                    <button class="btn-secondary" onclick="sendSleepCommand('!lsleep')">💤 Light Sleep</button>
                    <button class="btn-danger" onclick="sendSleepCommand('!dsleep')">🔌 Deep Sleep</button>
                </div>
            </div>
            <div>
                <div class="terminal-container">
                    <div class="terminal-header">
                        <span>System Diagnostic Console</span>
                        <span style="font-size: 0.75rem; color: var(--text-secondary);">Auto-scrolls unless paused</span>
                    </div>
                    <div id="terminal"></div>
                </div>
                <div class="image-preview">
                    <p>Latest Capture Preview</p>
                    <img id="cameraPreview" src="" alt="Camera Preview">
                </div>
            </div>
        </div>
    </div>
    <script>
        const terminal = document.getElementById('terminal');
        const statusBadge = document.getElementById('status');
        const cameraPreview = document.getElementById('cameraPreview');
        let isUserScrolling = false;

        terminal.addEventListener('scroll', () => {
            const diff = terminal.scrollHeight - terminal.clientHeight - terminal.scrollTop;
            isUserScrolling = diff > 50;
        });

        function appendLog(text, type = 'info') {
            const line = document.createElement('div');
            line.className = `log-line ${type}`;
            line.textContent = text;
            terminal.appendChild(line);
            if (!isUserScrolling) { terminal.scrollTop = terminal.scrollHeight; }
        }

        function sendCommand(cmd) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(cmd);
                appendLog(`[CMD SENT] ${cmd}`, 'cmd');
            } else {
                appendLog('[ERROR] WebSocket is not connected.', 'error');
            }
        }

        function sendSleepCommand(cmd) {
            const duration = document.getElementById('sleepDuration').value;
            sendCommand(`${cmd} ${duration}`);
        }

        function refreshImage() {
            // Cache-busting trick to force the browser to fetch a fresh image
            cameraPreview.src = `/snapshot?t=${new Date().getTime()}`;
            cameraPreview.style.display = 'block';
            appendLog('[INFO] Fetching latest image snapshot...', 'info');
        }

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

        ws.onopen = () => {
            statusBadge.textContent = 'Connected';
            statusBadge.classList.add('connected');
            appendLog('[INFO] [WEBSOCKET] Connected to ESP32-S3.', 'info');
        };

        ws.onmessage = (event) => {
            // If the server sends the literal string "!REFRESH_IMAGE", update the preview
            if (event.data === "!REFRESH_IMAGE") {
                refreshImage();
            } else {
                // Otherwise, treat it as a standard log line
                let type = 'info';
                if (event.data.includes('[ERROR]')) type = 'error';
                else if (event.data.includes('[WARN]')) type = 'warn';
                else if (event.data.includes('[CMD]')) type = 'cmd';
                appendLog(event.data, type);
            }
        };

        ws.onclose = () => {
            statusBadge.textContent = 'Disconnected';
            statusBadge.classList.remove('connected');
            appendLog('[ERROR] [WEBSOCKET] Connection lost to camera server.', 'error');
            setTimeout(() => location.reload(), 3000); // Auto-reconnect
        };
    </script>
</body>
</html>"""
    return html_page, 200, {'Content-Type': 'text/html'}

@app.route('/snapshot')
async def snapshot(request):
    result = capture_image()
    if result:
        return result[0], 200, {'Content-Type': 'image/jpeg'}
    else:
        return "Capture Failed", 500

@app.route("/ws")
@with_websocket
async def ws_log_stream(request, ws):
    logger.active_connections.add(ws)
    print(f"[INFO] [WEBSOCKET] Diagnostic client attached. Total open web sockets: {len(logger.active_connections)}")

    if rtc_json["boot_log"]:
        uasyncio.create_task(ws.send("[INFO] [MAIN] *--- LOADED HISTORY [LAST 50] ---*"))

        for log in rtc_json["boot_log"]:
            uasyncio.create_task(ws.send(log))

        uasyncio.create_task(ws.send("[INFO] [MAIN] *--- BOOT HISTORY [LAST 50] ---*"))

    try:
        while True:
            data: str = await ws.receive()
            if not data:
                break
            else:
                if data.startswith("!capture"):
                    jpeg = capture_image()
                    if jpeg:
                        print(f"[INFO] [CAM] Capture successful. Refreshing preview...")
                        uasyncio.create_task(ws.send("!REFRESH_IMAGE"))
                    else:
                        print("[WARNING] [WEBSOCKET] image send failed.")

                elif data.startswith("!sreset"):
                    print("[INFO] [WEBSOCKET] Soft reset initiated...")
                    c_cmnd["comm"] = "sreset"
                elif data.startswith("!hreset"):
                    print("[INFO] [WEBSOCKET] Hard reset initiated...")
                    c_cmnd["comm"] = "hreset"
                elif data.startswith("!lsleep"):
                    parts = data.split()
                    print(f"[INFO] [WEBSOCKET] light sleep initiated for {parts[1]} seconds... ")
                    c_cmnd["comm"] = "lsleep"
                    c_cmnd["dur"] = int(parts[1])
                elif data.startswith("!dsleep"):
                    parts = data.split()
                    print(f"[INFO] [WEBSOCKET] deep sleep initiated for {parts[1]} seconds... ")
                    c_cmnd["comm"] = "dsleep"
                    c_cmnd["dur"] = int(parts[1])
                else:
                    print(f"[WARNING] [WEBSOCKET] unknown command: {data}")
    except:
        pass
    finally:
        logger.active_connections.remove(ws)
        original_print("[WARNING] [WEBSOCKET] websocket client detached.") # it doesn't causes loop

print(f"[INFO] [INITIAL] initial free available memory: {gc.mem_free()}")
print(f"[INFO] [INITIAL] latest reset caused by: {reset_cause()}")

rtc_json = {"config": {}, "auth": {}, "l_offset": "", "boot_log": []}
if rtc_content := RTC().memory():
    try:
        print("[INFO] [INITIAL] RTC memory valid. Loading config from RTC...")
        loaded_data = ujson.loads(rtc_content)
        rtc_json["config"] = loaded_data.get("config", {})
        rtc_json["auth"] = loaded_data.get("auth", {})
        rtc_json["l_offset"] = loaded_data.get("l_offset", "")
        rtc_json["boot_log"] = loaded_data.get("boot_log", [])
    except Exception:
        print("[WARN] [INITIAL] RTC memory corrupted. Falling back to alternatives.")
else:
    print("[WARN] [INITIAL] RTC memory invalid. Loading configurations from other options...")
if not rtc_json["config"]:
    try:
        with open("config.json") as f:
            rtc_json["config"] = ujson.load(f)
    except OSError as e:
        print("[WARN] [INITIAL] config.json read error:", e)
        rtc_json["config"] = {
            "ssid": "Py",
            "password": "11111111",
            "token": "***",
        }
if not rtc_json["auth"]:
    try:
        with open("authorized.json", mode='r') as f:
            rtc_json["auth"] = ujson.load(f)
    except OSError as e:
        print("[ERROR] [INITIAL] authorized.json missing or corrupted. Panic!")
        raise e

config = rtc_json["config"]
AUTH_USERS = rtc_json["auth"]["user_id"]
ADMINS = rtc_json["auth"]["user_admin"]
TOKEN = config.get("token")
URL = f"https://botapi.rubika.ir/v3/{TOKEN}"
SSID = config.get("ssid")
PASSWORD = config.get("password")
LAST_FETCH = time.ticks_ms()
LAST_PUSH = time.ticks_ms()
HEADERS = {'Content-Type': 'application/json'}
_BOOT_TICK = time.ticks_ms()
BASE_OFFSET = "6a94b3b0577044b7a9bba2ab"
LOG_MAX = 50
wlan = network.WLAN(network.STA_IF)
idle_count = 1
session = aiohttp.ClientSession()
latest_offset = rtc_json["l_offset"]
c_cmnd = {"comm": "", "dur": 0} # command, duration(ms)

def connect_wifi():
    global wlan
    wlan.active(True)
    if not wlan.isconnected():
        print("[INFO] [WIFI] connecting", end="")
        wlan.connect(SSID, PASSWORD)
    else:
        wlan.disconnect()
        wlan.connect()
    while not wlan.isconnected():
        time.sleep_ms(500)
        original_print(".", end="")
    print("[INFO] [WIFI] Connected! IP: ", wlan.ifconfig()[0])

async def find_last_offset(base_offset: str):
    print("[DEBUG] trying to find latest offset...")
    depth = 0
    GETUPDATES_URL = URL + "/getUpdates"
    while True:
        print(f"[DEBUG] checking depth={depth}")
        try:
            async with session.post(
                url=GETUPDATES_URL,
                data=ujson.dumps({"offset_id": base_offset}).encode('utf-8'),
                headers=HEADERS
            ) as response:
                result = await response.json()
                if "data" in result or result.get("status") == "OK":
                    data = result.get("data", result)
                    if (not ("next_offset_id" in data)) or (not data.get("updates", [])):
                        print(f"[DEBUG] latest_offset FOUND in depth={depth}. returning...")
                        return base_offset
                    else:
                        base_offset = data.get("next_offset_id")
                        depth += 1
                        continue
                else:
                    print("[ERROR] [FIND_OFFSET] an error happened during POST request to fetch offset.")
                    raise Exception("None offset_id exception")
        except Exception as e:
            print("[ERROR] [FIND_OFFSET] an error happened during find_last_offset operation.")
            raise e

if not rtc_json["l_offset"]:
        latest_offset = uasyncio.run(find_last_offset(BASE_OFFSET))


wdt = WDT(timeout=151000) # ~2.51min ~ 151s

def get_uptime(unit: str = 'D'):
    uptime_ms = time.ticks_diff(time.ticks_ms(), _BOOT_TICK)
    if unit == 'D':
        return uptime_ms / 86_400_000
    elif unit == 'H':
        return uptime_ms / 3_600_000
    else:
        print("[ERROR] [UPTIME] unknown unit.")
        raise ValueError

async def update_offset(offset_id: str):
    global rtc_json
    try:
        rtc_json['l_offset'] = offset_id
        RTC().memory(ujson.dumps(rtc_json).encode('utf-8'))
    except Exception as e:
        print("[ERROR] [OFFSET] an error occured during write operation on RTC memory.")

async def get_updates(offset_id: str, lim: int = 10):
    global idle_count
    global latest_offset
    global LAST_FETCH
    if time.ticks_diff(time.ticks_ms(), LAST_FETCH) >= 5000:
        payload = {
            "offset_id": offset_id,
            "limit": lim,
        }
        try:
            print(f"[INFO] [UPDATES] polling new updates... [idle_count: {idle_count}/100]")
            async with session.request('POST', f"{URL}/getUpdates", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                data = await response.json()
                updates_data = data.get("data", data)
                next_offset = updates_data.get("next_offset_id", offset_id)
                if next_offset != offset_id:
                    idle_count = 0
                    updates = updates_data.get("updates", [])
                    latest_offset = next_offset
                    await update_offset(next_offset)
                    for update in updates:
                        msgtype = update.get("type")
                        if msgtype == "NewMessage":
                            new_msg = update.get("new_message", {})
                            chat_id = update.get("chat_id")
                            text = new_msg.get("text", "").strip()
                            sender_id = new_msg.get("sender_id")
                            message_id = new_msg.get("message_id")
                        elif msgtype == "StartedBot":
                            chat_id = update.get("chat_id")
                            text = None
                            sender_id = None
                            message_id = None
                        else:
                            continue
                        await command_routing(msgtype, chat_id, text, sender_id, message_id)
                else:
                    idle_count += 1
                    if idle_count > 100:
                        print("[INFO] [UPDATES] idle_count reached 100. entering lightsleep for 5 minutes...")
                        wdt.feed()
                        lightsleep(300000)
                        print("[INFO] [UPDATES] lightsleep finished.")
                        wlan.disconnect()
                        connect_wifi()
                        idle_count = 0

            LAST_FETCH = time.ticks_ms()
        except Exception as e:
            print(f"[ERROR] [UPDATES] polling failed: {e}")
    else:
        print("[ERROR] [UPDATES] ratelimit exhausted. wait for 5s to finish.")

async def command_routing(msgtype: str, chat_id: str, text: str|None, sender_id: str|None, message_id: str|None):
    global c_cmnd
    if msgtype == "StartedBot" and not (text or sender_id) and str(chat_id) not in AUTH_USERS:
        print(f"[INFO] [COMMAND] new /start received in {chat_id}")
        print(f"[INFO] [COMMAND] UNAUTHORIZED ACCESS IN {chat_id}. BLOCKING USER.../!")

    elif msgtype == "NewMessage" and text == "/start" and str(sender_id) in AUTH_USERS:
        print(f"[INFO] [COMMAND] /start received from {sender_id} in {chat_id}")
        print(f"[INFO] [COMMAND] user {sender_id} is already authorized")
        await send_text_message(chat_id, "Your already authorized.\n use /capture to recieve new photos.\n use /info to get MCU's stats and info.")

    elif msgtype == "NewMessage" and text == "/capture" and str(sender_id) in AUTH_USERS:
        print(f"[COMMAND] /capture received from {sender_id} in {chat_id}")
        await send_images(chat_id, message_id)

    elif msgtype == "NewMessage" and text == "/info" and str(sender_id) in AUTH_USERS:
        print(f"[INFO] [COMMAND] /info received from {sender_id} in {chat_id}")
        await send_text_message(chat_id, await get_info_str(chat_id))

    elif msgtype == "NewMessage" and text == "/sreset" and str(sender_id) in ADMINS:
        print(f"[INFO] [COMMAND] /sreset received from {sender_id} in {chat_id}")
        await send_text_message(chat_id, "control command: /sreset received.\n soft resetting will happen in the next iteration.")
        c_cmnd["comm"] = "sreset"

    elif msgtype == "NewMessage" and text == "/hreset" and str(sender_id) in ADMINS:
        print(f"[INFO] [COMMAND] /hreset received from admin {sender_id} in {chat_id}")
        await send_text_message(chat_id, "control command: /rreset received.\n HARD resetting will happen in the next iteration.")
        c_cmnd["comm"] = "hreset"

    elif msgtype == "NewMessage" and text.startswith("/lsleep") and str(sender_id) in ADMINS:
        print(f"[INFO] [COMMAND] /lsleep received from admin {sender_id} in {chat_id}")
        duration = text.split()[1]
        try:
            duration = int(duration)
        except ValueError:
            await send_text_message(chat_id, f"invalid duration specified. try again.")
            duration = None
        if duration and duration <= 150: # shortcircuit
            await send_text_message(chat_id, f"control command: /lsleep received.\n light sleep for {duration}s will happen in the next iteration.")
            c_cmnd["comm"] = "lsleep"
            c_cmnd["dur"] = duration * 1000
        elif duration: # surpasses WDT limit.
            await send_text_message(chat_id, f"specified duration surpasses WDT limit. valid range: [1, 150] seconds. try again.")

    elif msgtype == "NewMessage" and text.startswith("/dsleep") and str(sender_id) in ADMINS:
        print(f"[INFO] [COMMAND] /dsleep received from admin {sender_id} in {chat_id}")
        duration = text.split()[1]
        try:
            duration = int(duration)
        except ValueError:
            await send_text_message(chat_id, f"invalid duration specified. try again.")
            duration = None
        if duration and duration <= 150: # shortcircuit
            await send_text_message(chat_id, f"control command: /dsleep received.\n deep sleep for {duration}s will happen in the next iteration.")
            c_cmnd["comm"] = "dsleep"
            c_cmnd["dur"] = duration * 1000
        elif duration: # surpasses WDT limit.
            await send_text_message(chat_id, f"specified duration surpasses WDT limit. valid range: [1, 150] seconds. try again.")

    elif msgtype == "NewMessage" and (str(sender_id) not in AUTH_USERS):
        print(f"[INFO] [MESSAGE] message received from an unauthorized user: {sender_id} in {chat_id}")

    else:
        await send_text_message(chat_id, "unknown command!\n*---* Users: use /capture to capture new photos\nuse /info to get MCU's stats and info.\n\n*---*Admins: use /sreset to soft reset the MCU.\nuse /hreset to hard reset the MCU.\nuse /lsleep {seconds} to send the MCU to lightsleep for specified duration\nuse /dsleep {seconds} to send MCU to deepsleep for specified duration")

async def send_text_message(chat_id: str, msg: str):
        payload = {
            "chat_id": chat_id,
            "text": msg,
        }
        try:
            async with session.request('POST', f"{URL}/sendMessage", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                result = await response.json()
                if not ("data" in result or result.get("status") == "OK"):
                    print(f"[WARN] [MESSAGE] sending message to {chat_id} failed.")
        except Exception as e:
            print(f"[ERROR] [MESSAGE] network failure")
            raise e

async def get_info_str(chat_id: str):
    now = time.gmtime()
    vfs = os.statvfs("/")
    free_kb = (vfs[0] * vfs[3]) // 1024
    ssid = wlan.config('ssid')
    channel = wlan.config('channel')
    gmt_time = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(now[0], now[1], now[2], now[3], now[4], now[5])
    return f"time(GMT):\n{gmt_time}\n-*-*- DEVICE INFO -*-*-\nFree RAM: {gc.mem_free()}b\nAllocated RAM: {gc.mem_alloc()}b\nFree FLASH: {free_kb}KB\nTemperature: {esp32.mcu_temperature()}°C\n-*- *-* -*-\nWi-Fi active: {wlan.active()}\nConnected: {wlan.isconnected()}\nIP: {wlan.ifconfig()[0]}\nSSID: {ssid}\nWiFi Channel: {channel}\nLink Status: {wlan.status()}\n-*- *-* -*-"

async def send_images(chat_id, reply_message_id):
    global session
    global LAST_PUSH
    if time.ticks_diff(time.ticks_ms(), LAST_PUSH) >= 5000:
        try:
            upload_url = ""
            async with session.request('POST', f"{URL}/requestSendFile", data=ujson.dumps({"type":"Image"}).encode("utf-8"), headers=HEADERS) as response:
                result = await response.json()
                if "data" in result or result.get("status") == "OK":
                    data = result.get("data", result)
                    upload_url = data.get("upload_url")
                else:
                    print(f"[WARN] [IMAGE] POST request to FETCH upload_url failed. ERRORNO=0")
                    await send_text_message(chat_id, "an error occured during capture upload operation.\n Please try again. ERRNO=0")
        except Exception as e:
            print(f"[ERROR] [IMAGE] network failure ERRNO=0: ")
            return

        if not upload_url:
            print("[WARN] [IMAGE] upload_url is Empty. ERRNO=3")
            await send_text_message(chat_id, "POST request to server failed. please try again.")
            return

        capture_data = capture_image()
        if not capture_data:
            await send_text_message(chat_id, "Camera capture failed. Please try again. ERRNO=5")
            return

        try:
            file_id = None
            fdata = handle_encoding(capture_data[0])
            response = urequests.post(upload_url, data=fdata[0], headers=fdata[1])
            try:
                result = response.json()
            except Exception:
                result = {"raw_error": response.text, "status": response.status_code}

            if "data" in result or result.get("status") == "OK":
                file_id = result.get("data", {}).get("file_id")
            else:
                print(f"[WARN] [IMAGE] Both upload methods failed. Server replied: {result}\n ERRNO=1")
                await send_text_message(chat_id, "Upload failed. ERRNO=1")
                return
            response.close()

        except Exception as e:
            print(f"[ERROR] [IMAGE] Upload failed: {e}")
            await send_text_message(chat_id, "Network error during upload. ERRNO=1")
            return

        if not file_id:
            print("[WARN] [IMAGE] file_id is Empty. ERRNO=4")
            await send_text_message(chat_id, "POST request to upload file failed. please try again.")
            return

        payload = {
            "chat_id": chat_id,
            "file_id": file_id,
            "text": f"captured at: {capture_data[1]}",
            "reply_to_message_id": reply_message_id,
        }

        try:
            async with session.request('POST', URL+"/sendFile", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                result = await response.json()
                if "data" in result or result.get("status") == "OK":
                    LAST_PUSH = time.ticks_ms()
                else:
                    print(f"[WARN] [IMAGE] POST request to send captured image to user failed. ERRORNO=2")
                    await send_text_message(chat_id, "an error occured during capture upload operation.\n Please try again. ERRNO=2")
        except Exception as e:
            print(f"[ERROR] [IMAGE] network failure ERRRNO=2: ")
            return

        del capture_data

    else:
        print("[ERROR] [IMAGE] capture ratelimit exhausted. wait for 5s to finish.")
        await send_text_message(chat_id, "capture ratelimit exhausted. wait 5s before requesting another capture.")

def handle_encoding(image_bytes): # --- BEGINNING OF AI-ASSISTED PART ---
    boundary = "MicroPythonUploadBoundary123"
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="image.jpg"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode('utf-8')

    footer = f"\r\n--{boundary}--\r\n".encode('utf-8')

    full_payload = header + image_bytes + footer

    custom_headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(full_payload))
    }

    return full_payload, custom_headers # --- END OF AI-ASSISTED PART

def ctrl_command_check():
    global c_cmnd
    if c_cmnd["comm"] == "sreset":
        soft_reset()
    elif c_cmnd["comm"] == "hreset":
        reset()
    elif c_cmnd["comm"] == "lsleep":
        lightsleep(c_cmnd["dur"])
        c_cmnd["comm"] = ""
        c_cmnd["dur"] = 0
    elif c_cmnd["comm"] == "dsleep":
        deepsleep(c_cmnd["dur"])
    else:
        pass

async def main():
    print("[INITIAL] [WEBSOCKET] starting WEBSOCKET...")
    connect_wifi()
    ntptime.host = "ntp.time.ir"
    try:
        ntptime.settime()
    except Exception as e:
        print(f"[ERROR] [MAIN] NTP Synchronization failed:\n{e}\nTimestamps may be inaccurate")

    uasyncio.create_task(app.start_server(host='0.0.0.0', port=80))

    print("[INITIAL] [MAIN] starting main program...")
    while True:
        try:
            ctrl_command_check()
            wdt.feed()
            await get_updates(latest_offset, 50)
            gc.collect()
            gc.collect()
            await uasyncio.sleep(5)
            print(f"[INFO] [MAIN] free available memory: {gc.mem_free()}")
            if get_uptime() > 6:
                print("[INFO] [MAIN] 6 days limit reached. hardresetting...")
                await session.close()
                reset()
            if len(logger.rtc_json["boot_log"]) > LOG_MAX:
                print("[INFO] [MAIN] removing old logs...")
                del logger.rtc_json["boot_log"][:50]
                RTC().memory(ujson.dumps(logger.rtc_json).encode("utf-8"))
        except Exception as e:
            if isinstance(e, KeyboardInterrupt):
                print("[NOTICE] [MAIN] KeyboardInterrupt detected...")
                print("[NOTICE] [MAIN] graceful shutdown...")
                RTC().memory(b'')
                gc.collect()
                gc.collect()
                # TODO: WRITE TO FLASH. for later.
                raise # propagates the current Exception
            else:
                print(f"[ERROR] [MAIN] Main loop error: {e}")
                await session.close()
                reset()

uasyncio.run(main())
