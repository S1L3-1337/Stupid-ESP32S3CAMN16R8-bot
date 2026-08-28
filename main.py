import time
import network
import uasyncio
import ujson
from camera import Camera, PixelFormat, FrameSize, GrabMode
import jpeg
import os
import gc
from machine import WDT
import aiohttp
import urequests

print(f"initial free available memory: {gc.mem_free()}")


try:
    print("reading config.json's content...")
    with open("config.json") as f:
        config = ujson.load(f)
except OSError as e:
    print("an error occured during read operation on config.json:", e)
    print("fallback to default value for config.json")
    config = {
        "ssid": "Py",
        "password": "11111111",
        "token": "***",
        "l_offset": "6a91d015a7019529a704ac19"
    }

SSID = config.get("ssid")
PASSWORD = config.get("password")
TOKEN = config.get("token")
URL = f"https://botapi.rubika.ir/v3/{TOKEN}"
LAST_FETCH = time.ticks_ms()
LAST_PUSH = time.ticks_ms()
HEADERS = {'Content-Type': 'application/json'}
latest_offset: str = config.get("l_offset", "")

print("Initializing Camera...")
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
print("Safety Cooldown for 5s...")
time.sleep(5)

enc = jpeg.Encoder(
    width=640,
    height=480,
    pixel_format="RGB565_BE",
    quality=85,
    rotation=0
)

wdt = WDT(timeout=80000)  # watchdog timer 80 seconds timeout

try:
    print("reading authorized.json's content...")
    with open("authorized.json", mode='r') as f:
        AUTH_USERS = ujson.load(f)
except OSError as e:
    print("error occured during read operation on authorized.json")
    print("unrecoverable for now, Panic!")
    raise e

def capture_image():

    print("capturing new image...")
    frame = cam.capture()
    if frame:
        rgb565_bytes = bytes(frame)
        print(f"Captured {len(rgb565_bytes)} bytes of raw RGB565")
        print("Encoding to JPEG and saving to file: image.jpg")
        with open("image.jpg", mode="wb") as f:
            f.write(enc.encode(rgb565_bytes))
        file_size = os.stat("image.jpg")[6]
        print(f"Saved to \"image.jpg\" ({file_size} bytes)")
        print("cleaning the buffer...")
        cam.free_buffer()
        now = time.localtime()
        return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
            now[0], now[1], now[2], now[3], now[4], now[5]
        )
    else:
        print("capture failed...")
        return None

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("connecting", end="")
        wlan.connect(SSID, PASSWORD)
    while not wlan.isconnected():
        time.sleep_ms(500)
        print(".", end="")
    print("Connected! Connection config: ", wlan.ifconfig())

async def update_offset(offset_id: str):
    print("updating config.json with new offset_id...")
    config["l_offset"] = offset_id
    try:
        print("writing the new offset_id...")
        with open("config.json.temp", mode='w') as f:
            ujson.dump(config, f)
        os.rename("config.json.temp", "config.json") # atomicity
    except OSError as e:
        print("an error occured during write operation on config.json")

async def get_updates(offset_id: str, lim: int = 10):
    global latest_offset
    global LAST_FETCH
    if time.ticks_diff(time.ticks_ms(), LAST_FETCH) >= 5000:
        payload = {
            "offset_id": offset_id,
            "limit": lim,
        }
        try:
            print("[INFO] polling new updates...")
            async with aiohttp.ClientSession() as session:
                async with session.request('POST', f"{URL}/getUpdates", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                    data = await response.json()
                    updates_data = data.get("data", data)
                    next_offset = updates_data.get("next_offset_id", offset_id)
                    if next_offset != offset_id:
                        print("new offset_id detected.")
                        print("updating offset_id...")
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
                                print("offset_id didn't, no new [supported] updates yet.")
                                continue
                            await command_routing(msgtype, chat_id, text, sender_id, message_id)
                    else:
                        pass # no new update/message.
            LAST_FETCH = time.ticks_ms()
        except Exception as e:
            print(f"[ERROR] polling failed: {e}")
    else:
        print("[ERROR] ratelimit exhausted. wait for 5s to finish.")

async def command_routing(msgtype: str, chat_id: str, text: str|None, sender_id: str|None, message_id: str|None):
    print("[MESSAGE]: new message received.")
    if msgtype == "StartedBot" and not (text or sender_id) and str(chat_id) not in AUTH_USERS.get("blocked_chats", []):
        print(f"[COMMAND] new /start received in {chat_id}") # lets restrict the bot to already authorized users. and ignore blocked fellas
        print(chat_id, "UNAUTHORIZED ACCESS.\n BLOCKING USER.../!") # ignore it
        block_user(str(chat_id))
    elif msgtype == "NewMessage" and text == "/start" and str(sender_id) in AUTH_USERS.get("user_id", []) and str(chat_id) not in AUTH_USERS.get("blocked_chats", []):
        print(f"[COMMAND] /start received from {sender_id} in {chat_id}")
        print(f"user {sender_id} is already authorized")
        await send_text_message(chat_id, "Your already authorized.\n use /capture to recieve new photos.")
    elif text == "/capture" and str(sender_id) in AUTH_USERS.get("user_id", []) and str(chat_id) not in AUTH_USERS.get("blocked_chats", []):
         await send_images(chat_id, message_id)
    elif msgtype == "NewMessage" and (str(sender_id) not in AUTH_USERS.get("user_id", []) or str(chat_id) in AUTH_USERS.get("blocked_chats", [])):
        print(f"[MESSAGE] message received from an unauthorized user: {sender_id} in {chat_id}") # ignore it.
    else:
        await send_text_message(chat_id, "unknown command!\n use /capture to capture new photos.")


async def send_text_message(chat_id: str, msg: str):
        payload = {
            "chat_id": chat_id,
            "text": msg,
        }
        try:
            print(f"Sending message to {chat_id}...")
            async with aiohttp.ClientSession() as session:
                async with session.request('POST', f"{URL}/sendMessage", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                    result = await response.json()
                    if "data" in result or result.get("status") == "OK":
                        print(f"[OK] message sent to {chat_id}")
                    else:
                        print(f"[FAIL] sending message to {chat_id} failed.")
        except Exception as e:
            print(f"[ERROR] network failure: ")
            print("unrecoverable for now, Panic!")
            raise e

def block_user(chat_id: str):
    print(f"blocking {chat_id}")
    if "blocked_chats" not in AUTH_USERS:
        AUTH_USERS["blocked_chats"] = []
    AUTH_USERS["blocked_chats"].append(chat_id)
    try:
        with open("authorized.json.temp", mode='w') as f:
            ujson.dump(AUTH_USERS, f)
        os.rename("authorized.json.temp", "authorized.json") # atomicity
        print("User blocked and saved successfully.")
    except OSError as e:
        print(f"[ERROR] Failed to write authorized.json: {e}")

async def send_images(chat_id, reply_message_id):
    global LAST_PUSH
    if time.ticks_diff(time.ticks_ms(), LAST_PUSH) >= 5000:
        print(f"sending new capture to {chat_id}...")
        try:
            async with aiohttp.ClientSession() as session:
                upload_url = ""
                async with session.request('POST', f"{URL}/requestSendFile", data=ujson.dumps({"type":"Image"}).encode("utf-8"), headers=HEADERS) as response:
                    result = await response.json()
                    print(f"returned ERRNO=0 Position: \n{result}")
                    if "data" in result or result.get("status") == "OK":
                        data = result.get("data", result)
                        upload_url = data.get("upload_url")
                    else:
                        print(f"[FAIL] POST request to FETCH upload_url failed. ERRORNO=0")
                        await send_text_message(chat_id, "an error occured during capture upload operation.\n Please try again. ERRNO=0")
        except Exception as e:
            print(f"[ERROR] network failure ERRNO=0: ")
            print("operation unrecoverable. returning...")
            return

        if not upload_url:
            print("[FAIL] upload_url is Empty. ERRNO=3")
            await send_text_message(chat_id, "POST request to server failed. please try again.")
            return

        capture_detail = capture_image()
        if not capture_detail:
            await send_text_message(chat_id, "Camera capture failed. Please try again. ERRNO=5")
            return

        try:
            print("uploading jpeg file...")
            file_id = None
            try:
                print("reading image.jpg into bytes...")
                with open("image.jpg", "rb") as file_handle:
                    fdata = handle_encoding(file_handle)
            except OSError as e:
                print("an error occured during binary read operation on image.jpg")
                return

            response = urequests.post(upload_url, data=fdata[0], headers=fdata[1])

            try:
                result = response.json()
            except Exception:
                result = {"raw_error": response.text, "status": response.status_code}

            if "data" in result or result.get("status") == "OK":
                file_id = result.get("data", {}).get("file_id")
                print(f"[OK] Multipart upload successful! file_id: {file_id}")
            else:
                print(f"[FAIL] Both upload methods failed. Server replied: {result}\n ERRNO=1")
                await send_text_message(chat_id, "Upload failed. ERRNO=1")
                return
            response.close()

        except Exception as e:
            print(f"[ERROR] Upload failed: {e}")
            await send_text_message(chat_id, "Network error during upload. ERRNO=1")
            return

        if not file_id:
            print("[FAIL] file_id is Empty. ERRNO=4")
            await send_text_message(chat_id, "POST request to upload file failed. please try again.")
            return

        payload = {
            "chat_id": chat_id,
            "file_id": file_id,
            "text": f"captured at: {capture_detail}",
            "reply_to_message_id": reply_message_id,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request('POST', URL+"/sendFile", data=ujson.dumps(payload).encode("utf-8"), headers=HEADERS) as response:
                    result = await response.json()
                    if "data" in result or result.get("status") == "OK":
                        LAST_PUSH = time.ticks_ms()
                    else:
                        print(f"[FAIL] POST request to send captured image to user failed. ERRORNO=2")
                        await send_text_message(chat_id, "an error occured during capture upload operation.\n Please try again. ERRNO=2")
        except Exception as e:
            print(f"[ERROR] network failure ERRRNO=2: ")
            print("operation unrecoverable. returning...")
            return

        try:
            if "image.jpg" in os.listdir():
                os.remove("image.jpg")
                print("[CLEANUP] Removed image.jpg from flash storage.")
        except OSError as e:
                print(f"[WARN] Failed to remove image.jpg: {e}")

    else:
        print("[ERROR] capture ratelimit exhausted. wait for 5s to finish.")
        await send_text_message(chat_id, "capture ratelimit exhausted. wait 5s before requesting another capture.")

def handle_encoding(file_handler): # --- BEGINNING OF AI-ASSISTED PART ---
    print("encoding POST request...")
    boundary = "MicroPythonUploadBoundary123"

    image_bytes = file_handler.read()

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
    print("starting program...")
    connect_wifi()

    print("Bot is running. Listening for commands...")
    while True:
        try:
            wdt.feed()
            await get_updates(latest_offset, 10)
            gc.collect()
            await uasyncio.sleep(5)
            print(f"free available memory: {gc.mem_free()}")
        except Exception as e:
            print(f"[CRITICAL] Main loop error: {e}")

uasyncio.run(main())
