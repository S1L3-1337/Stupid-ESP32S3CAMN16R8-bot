import time
import network
import uasyncio
import ujson
from camera import Camera, PixelFormat, FrameSize, GrabMode
import jpeg
import os
import gc
from machine import WDT, idle
import aiohttp
import urequests
from machine import RTC, reset, lightsleep, reset_cause
import esp32


original_print = print
def custom_log_print(*args, **kwargs):
    now = time.gmtime()

    original_print("{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
                now[0], now[1], now[2], now[3], now[4], now[5]
            ), *args, **kwargs)
print = custom_log_print

print(f"[INFO] [INITIAL] initial free available memory: {gc.mem_free()}")
print(f"[INFO] [INITIAL] latest reset caused by: {reset_cause()}")

print("[INFO] [INITIAL] reading from RTC memory...")
rtc_json = {"config": {}, "auth": {}}
if rtc_content := RTC().memory():
    try:
        print("[INFO] [INITIAL] RTC memory valid. Loading config from RTC...")
        loaded_data = ujson.loads(rtc_content)
        rtc_json["config"] = loaded_data.get("config", {})
        rtc_json["auth"] = loaded_data.get("auth", {})
    except ValueError:
        print("[WARN] [INITIAL] RTC memory corrupted. Falling back to files.")
else:
    print("[WARN] [INITIAL] RTC memory invalid. Loading config from file...")
if not rtc_json["config"]:
    try:
        print("[INFO] [INITIAL] reading config.json's content...")
        with open("config.json") as f:
            rtc_json["config"] = ujson.load(f)
    except OSError as e:
        print("[WARN] [INITIAL] config.json read error:", e)
        rtc_json["config"] = {
            "ssid": "Py",
            "password": "11111111",
            "token": "***",
            "l_offset": "6a91f6931e1b488427378f6e"
        }
if not rtc_json["auth"]:
    try:
        print("[INFO] [INITIAL] reading authorized.json's content...")
        with open("authorized.json", mode='r') as f:
            rtc_json["auth"] = ujson.load(f)
    except OSError as e:
        print("[ERROR] [INITIAL] authorized.json missing or corrupted. Panic!")
        raise e

config = rtc_json["config"]
AUTH_USERS = rtc_json["auth"]
SSID = config.get("ssid")
PASSWORD = config.get("password")
TOKEN = config.get("token")
URL = f"https://botapi.rubika.ir/v3/{TOKEN}"
LAST_FETCH = time.ticks_ms()
LAST_PUSH = time.ticks_ms()
idle_count = 1
HEADERS = {'Content-Type': 'application/json'}
latest_offset: str = config.get("l_offset", "")
_BOOT_TICK = time.ticks_ms()
wlan = network.WLAN(network.STA_IF)

print("[INFO] [INITIAL] Initializing Camera...")
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
print("[INFO] [INITIAL] Safety Cooldown for 5s...")
time.sleep(5)

enc = jpeg.Encoder(
    width=640,
    height=480,
    pixel_format="RGB565_BE",
    quality=85,
    rotation=0
)

wdt = WDT(timeout=80000)

def get_uptime(unit: str = 'D'):
    print("[INFO] [UPTIME] calculating uptime...")
    uptime_ms = time.ticks_diff(time.ticks_ms(), _BOOT_TICK)
    if unit == 'D':
        return uptime_ms / 86_400_000
    elif unit == 'H':
        return uptime_ms / 3_600_000
    else:
        print("[ERROR] [UPTIME] unknown unit.")
        print("[ERROR] [UPTIME] unrecoverable for now... panic!")
        raise ValueError

def capture_image():
    print("[INFO] [CAM] capturing new image...")
    frame = cam.capture()
    if frame:
        rgb565_bytes = bytes(frame)
        print(f"[INFO] [CAM] Captured {len(rgb565_bytes)} bytes of raw RGB565")
        print("[INFO] [CAM] Encoding image from RGB565 to jpeg format.")
        jpeg = enc.encode(rgb565_bytes)
        print(f"[INFO] [CAM] file encoded Successfully! image size: {len(jpeg)} bytes")
        print("[INFO] [CAM] cleaning the buffer...")
        cam.free_buffer()
        now = time.gmtime()
        return jpeg, "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            now[0], now[1], now[2], now[3], now[4], now[5]
        )
    else:
        print("[ERROR] [CAM] capture failed...")
        print("[ERROR] [CAM] unrecoverable error for now. returning...")
        return None

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
        print(".", end="")
    print("[INFO] [WIFI] Connected! Connection config: ", wlan.ifconfig())

async def update_offset(offset_id: str):
    global rtc_json
    if get_uptime('H') > 12:
        print("[INFO] [OFFSET] 12h uptime limit reached.")
        print("[INFO] [OFFSET] updating config.json with new offset_id...")
        config["l_offset"] = offset_id
        try:
            print("[INFO] [OFFSET] writing the new offset_id...")
            with open("config.json.temp", mode='w') as f:
                ujson.dump(config, f)
            os.rename("config.json.temp", "config.json")
            os.sync()
        except OSError as e:
            print("[WARN] [OFFSET] an error occured during write operation on config.json")
    else:
        print("[INFO] [OFFSET] device uptime is less than 12 hours.")
        try:
            print("[INFO] [OFFSET] updating RTC memory with new offset_id...")
            rtc_json['config']['l_offset'] = offset_id
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
            async with aiohttp.ClientSession() as session:
                async with session.request('POST', f"{URL}/getUpdates", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                    data = await response.json()
                    updates_data = data.get("data", data)
                    next_offset = updates_data.get("next_offset_id", offset_id)
                    if next_offset != offset_id:
                        idle_count = 0
                        print("[INFO] [UPDATES] new offset_id detected.")
                        print("[INFO] [UPDATES] updating offset_id...")
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
                                print("[INFO] [UPDATES] offset_id didn't, no new [supported] updates yet.")
                                continue
                            await command_routing(msgtype, chat_id, text, sender_id, message_id)
                    else:
                        print("[INFO] [UPDATES] next_offset_id is identical to l_offset. passing...")
                        idle_count += 1
                        if idle_count > 100:
                            print("[INFO] [UPDATES] idle_count reached 100. entering lightsleep for 5 minutes...")
                            print("[INFO] [UPDATES] feeding CPU WATCHDOG timer...")
                            wdt.feed()
                            lightsleep(300000)
                            print("[INFO] [UPDATES] lightsleep finished.")
                            print("[INFO] [UPDATES] reconnecting to WiFi again...")
                            wlan.disconnect()
                            connect_wifi()
                            idle_count = 0

            LAST_FETCH = time.ticks_ms()
        except Exception as e:
            print(f"[ERROR] [UPDATES] polling failed: {e}")
    else:
        print("[ERROR] [UPDATES] ratelimit exhausted. wait for 5s to finish.")

async def command_routing(msgtype: str, chat_id: str, text: str|None, sender_id: str|None, message_id: str|None):
    print("[INFO] [COMMAND]: new message received.")
    if msgtype == "StartedBot" and not (text or sender_id) and str(chat_id) not in AUTH_USERS.get("blocked_chats", []):
        print(f"[INFO] [COMMAND] new /start received in {chat_id}")
        print(f"[INFO] [COMMAND] UNAUTHORIZED ACCESS IN {chat_id}. BLOCKING USER.../!")
        block_user(str(chat_id))
    elif msgtype == "NewMessage" and text == "/start" and str(sender_id) in AUTH_USERS.get("user_id", []) and str(chat_id) not in AUTH_USERS.get("blocked_chats", []):
        print(f"[INFO] [COMMAND] /start received from {sender_id} in {chat_id}")
        print(f"[INFO] [COMMAND] user {sender_id} is already authorized")
        await send_text_message(chat_id, "Your already authorized.\n use /capture to recieve new photos.\n use /info to get MCU's stats and info.")
    elif msgtype == "NewMessage" and text == "/capture" and str(sender_id) in AUTH_USERS.get("user_id", []) and str(chat_id) not in AUTH_USERS.get("blocked_chats", []):
        print(f"[COMMAND] /capture received from {sender_id} in {chat_id}")
        await send_images(chat_id, message_id)
    elif msgtype == "NewMessage" and text == "/info" and str(sender_id) in AUTH_USERS.get("user_id", []) and str(chat_id) not in AUTH_USERS.get("blocked_chats", []):
        print(f"[INFO] [COMMAND] /info received from {sender_id} in {chat_id}")
        await send_text_message(chat_id, await get_info_str(chat_id))
    elif msgtype == "NewMessage" and (str(sender_id) not in AUTH_USERS.get("user_id", []) or str(chat_id) in AUTH_USERS.get("blocked_chats", [])):
        print(f"[INFO] [MESSAGE] message received from an unauthorized user: {sender_id} in {chat_id}")
    else:
        await send_text_message(chat_id, "unknown command!\n use /capture to capture new photos\n use /info to get MCU's stats and info.")

async def send_text_message(chat_id: str, msg: str):
        payload = {
            "chat_id": chat_id,
            "text": msg,
        }
        try:
            print(f"[INFO] [MESSAGE] Sending message to {chat_id}...")
            async with aiohttp.ClientSession() as session:
                async with session.request('POST', f"{URL}/sendMessage", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                    result = await response.json()
                    if "data" in result or result.get("status") == "OK":
                        print(f"[INFO] [MESSAGE] message sent to {chat_id}")
                    else:
                        print(f"[WARN] [MESSAGE] sending message to {chat_id} failed.")
        except Exception as e:
            print(f"[ERROR] [MESSAGE] network failure")
            print("[ERROR] [MESSAGE] unrecoverable for now, Panic!")
            raise e

async def get_info_str(chat_id: str):
    print("[INFO] [GET_INFO] getting MCU's info...")
    now = time.gmtime()
    vfs = os.statvfs("/")
    free_kb = (vfs[0] * vfs[3]) // 1024
    ssid = wlan.config('ssid')
    channel = wlan.config('channel')
    gmt_time = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(now[0], now[1], now[2], now[3], now[4], now[5])
    return f"--- --- ---\ntime(GMT):\n{gmt_time}\n--- DEVICE INFO ---\nFree ram: {gc.mem_free()} bytes\nAllocated ram {gc.mem_alloc()} bytes\nFree flash: {free_kb} KB\nTemperature: {esp32.mcu_temperature()} °C\n--- --- ---\nWi-Fi active: {wlan.active()}\nConnected: {wlan.isconnected()}\nIP: {wlan.ifconfig()[0]}\nSSID: {ssid}\nWiFi Channel: {channel}\nLink Status: {wlan.status()}\n--- --- ---"

def block_user(chat_id: str):
    global rtc_json
    print(f"[INFO] [BLOCK] blocking {chat_id}...")
    if "blocked_chats" not in AUTH_USERS:
        AUTH_USERS["blocked_chats"] = []
    AUTH_USERS["blocked_chats"].append(chat_id)
    if get_uptime('H') > 12:
        print("[INFO] [BLOCK] 12h uptime limit reached.")
        print("[INFO] [BLOCK] adding new blocked user to authorized.json...")
        try:
            with open("authorized.json.temp", mode='w') as f:
                ujson.dump(AUTH_USERS, f)
            os.rename("authorized.json.temp", "authorized.json")
            os.sync()
            print("[INFO] [BLOCK] User blocked and saved successfully.")
        except OSError as e:
            print(f"[ERROR] [BLOCK] Failed to write authorized.json: {e}")
            print("[ERROR] [BLOCK] unrecoverable for now... panic!")
            raise e
    else:
        print("[INFO] [BLOCK] device uptime is less than 12 hours.")
        try:
            print("[INFO] [BLOCK] adding new blocked user to RTC memory...")
            rtc_json['auth'] = AUTH_USERS
            RTC().memory(ujson.dumps(rtc_json).encode('utf-8'))
        except Exception as e:
            print(f"[ERROR] [BLOCK] Failed to write new data to RTC memory.: {e}")
            print("[ERROR] [BLOCK] unrecoverable for now... panic!")
            raise e

async def send_images(chat_id, reply_message_id):
    global LAST_PUSH
    if time.ticks_diff(time.ticks_ms(), LAST_PUSH) >= 5000:
        print(f"[INFO] [IMAGE] sending new capture to {chat_id}...")
        try:
            async with aiohttp.ClientSession() as session:
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
            print("[ERROR] [IMAGE] operation unrecoverable. returning...")
            return

        if not upload_url:
            print("[WARN] [IMAGE] upload_url is Empty. ERRNO=3")
            await send_text_message(chat_id, "POST request to server failed. please try again.")
            return

        capture_data = capture_image()
        if not capture_data:
            await send_text_message(chat_id, "Camera capture failed. Please try again. ERRNO=5")
            print("[INFO] [IMAGE] operation unrecoverable. returning...")
            return

        try:
            print("[INFO] [IMAGE] uploading jpeg file...")
            file_id = None
            print("[INFO] [IMAGE] encoding image...")
            fdata = handle_encoding(capture_data[0])
            response = urequests.post(upload_url, data=fdata[0], headers=fdata[1])
            try:
                result = response.json()
            except Exception:
                result = {"raw_error": response.text, "status": response.status_code}

            if "data" in result or result.get("status") == "OK":
                file_id = result.get("data", {}).get("file_id")
                print(f"[INFO] [IMAGE] Multipart upload successful! file_id: {file_id}")
            else:
                print(f"[WARN] [IMAGE] Both upload methods failed. Server replied: {result}\n ERRNO=1")
                print("[WARN] [IMAGE] operation unrecoverable. returning...")
                await send_text_message(chat_id, "Upload failed. ERRNO=1")
                return
            response.close()

        except Exception as e:
            print(f"[ERROR] [IMAGE] Upload failed: {e}")
            print(f"[ERROR] [IMAGE] operation unrecoverable. returning...")
            await send_text_message(chat_id, "Network error during upload. ERRNO=1")
            return

        if not file_id:
            print("[WARN] [IMAGE] file_id is Empty. ERRNO=4")
            print("[WARN] [IMAGE] operation unrecoverable. returning...")
            await send_text_message(chat_id, "POST request to upload file failed. please try again.")
            return

        payload = {
            "chat_id": chat_id,
            "file_id": file_id,
            "text": f"captured at: {capture_data[1]}",
            "reply_to_message_id": reply_message_id,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request('POST', URL+"/sendFile", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                    result = await response.json()
                    if "data" in result or result.get("status") == "OK":
                        LAST_PUSH = time.ticks_ms()
                    else:
                        print(f"[WARN] [IMAGE] POST request to send captured image to user failed. ERRORNO=2")
                        await send_text_message(chat_id, "an error occured during capture upload operation.\n Please try again. ERRNO=2")
        except Exception as e:
            print(f"[ERROR] [IMAGE] network failure ERRRNO=2: ")
            print("[ERROR] [IMAGE] operation unrecoverable. returning...")
            return

        del capture_data
        print("[INFO] [IMAGE] Removed image.jpg from ram.")

    else:
        print("[ERROR] [IMAGE] capture ratelimit exhausted. wait for 5s to finish.")
        await send_text_message(chat_id, "capture ratelimit exhausted. wait 5s before requesting another capture.")

def handle_encoding(image_bytes): # --- BEGINNING OF AI-ASSISTED PART ---
    print("[INFO] [ENCODE] encoding POST request...")
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

async def main():
    global latest_offset
    print("[INFO] [MAIN] starting program...")
    connect_wifi()

    print("[INFO] [MAIN] Bot is running. Listening for commands...")
    while True:
        try:
            print("[INFO] [MAIN] feeding CPU WATCHDOG timer...")
            wdt.feed()
            await get_updates(latest_offset, 10)
            print("[INFO] [MAIN] garbage collecting...")
            gc.collect()
            gc.collect()
            await uasyncio.sleep(5)
            print(f"[INFO] [MAIN] free available memory: {gc.mem_free()}")
            if get_uptime() > 6:
                print("[INFO] [MAIN] 6 days limit reached. hardresetting...")
                reset()
        except Exception as e:
            print(f"[ERROR] [MAIN] Main loop error: {e}")
            print("[ERROR] unrecoverable error... hardresetting...")
            reset()

uasyncio.run(main())
