import time
import sys
import uasyncio
from machine import RTC
import ujson

try:
    rtc_data = RTC().memory().decode('utf-8')
    rtc_json = ujson.loads(rtc_data)
    if "boot_log" not in rtc_json:
        rtc_json["boot_log"] = []
except Exception:
    rtc_json = {"config": {}, "auth": {}, "l_offset": "", "boot_log": []}

boot_phase = False
no_ws = True
original_print = print
active_connections = set()

def custom_log_print(*args, **kwargs):
    global no_ws
    now = time.gmtime()
    p_timestamp = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(now[0], now[1], now[2], now[3], now[4], now[5])
    log_text = " ".join(str(arg) for arg in args)
    full_message = f"{p_timestamp} | {log_text}"

    original_print(full_message, **kwargs)

    if not boot_phase:
        if not active_connections:
            no_ws = True
        else:
            no_ws = False
            for wsocket in active_connections:
                try:
                    uasyncio.create_task(wsocket.send(full_message))
                except:
                    original_print("[WARNING] [WEBSOCKET] an error occured during sending operation.")

    if boot_phase or no_ws:
        try:
            rtc_json["boot_log"].append(full_message) # save the boot logs for future's websocket in main.py
            RTC().memory(ujson.dumps(rtc_json).encode("utf-8"))
        except ValueError as e:
            print("[ERROR] [LOGGER] buffer overflow...")
            print("[ERROR] [LOGGER] removing old logs...")
            rtc_json["boot_log"] = [full_message]
            RTC().memory(ujson.dumps(rtc_json).encode("utf-8"))
