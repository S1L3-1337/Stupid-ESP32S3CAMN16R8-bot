import ugit
from machine import reset
import gc
import errno

backup_created = False
network_codes = [errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET, errno.ETIMEDOUT]
class BootIntoMainError(Exception)

def rollback_mechanism():
    if backup_created:
        print("[ERROR] [OTA] Restoring previous backup...")
        try:
            if ugit.restore():
                print("[INFO] [OTA] Backup restored successfully. Rebooting...")
            else:
                raise Exception
        except Exception as rollback_error:
            print(f"[ERROR] [OTA] Rollback failed: {rollback_error}")
    else:
        print("[ERROR] [OTA] there is no backup to restore. hard-resetting...")
    reset()

def concrete_check():
    try:
        for i in range(5):
            return ugit.check_for_updates()
    except Exception as e:
        if i < 4:
            continue
        else:
            print("checking for updates failed. booting into main.py")
            raise BootIntoMainError

def concrete_update():
    try:
        print("[INFO] [OTA] Checking for updates...")
        uflag = concrete_check()

        if (uflag["new"] or uflag["changed"] or uflag["deleted"]):
            print("[INFO] [OTA] New updates found. Downloading...")
            ugit.backup()
            backup_created = True
            ugit.pull_all(isconnected=True, branch="main")
            print("[INFO] [OTA] Update complete. Rebooting...")
            reset()
        else:
            print("[INFO] [OTA] System is up to date.")
        print("[INFO] [OTA] booting into main.py")

    except Exception as e:
        print(f"[ERROR] [OTA] Update operation failed: {e}")
        if isinstance(e, OSError) and e.args:
            err_code = e.errno if hasattr(e, 'errno') else e.args[0]
            if err_code in network_codes:
                try:
                    print(f"[ERROR] [OTA] update operation failed due to netowork error: {err_code}")
                    print("[INFO] [OTA] retrying the update operation...")
                    for repeat in range(5):
                        gc.collect()
                        gc.collect()
                        ugit.pull_all(isconnected=True, branch="main")
                        print("[INFO] [OTA] Update complete. Rebooting...")
                        reset()
                except Exception as e:
                    if isinstance(e, OSError):
                        err_code = e.errno if hasattr(e, 'errno') else e.args[0]
                        if err_code in network_codes and repeat < 4:
                            continue
                        else:
                            print("[ERROR] [INFO] retrying failed... booting into main.py")
                    else:
                        print("[ERROR] [OTA] retry-update operations failed due to non-network error")
                        rollback_mechanism()
        elif isinstance(e, BootIntoMainError):
            pass
        else:
            rollback_mechanism()

def ota():
    gc.collect()
    gc.collect()
    wlan = ugit.wificonnect()
    if wlan.isconnected():
        concrete_update()
    else:
        for i in range(5):
            ugit.wifidisconnect()
            if wlan := ugit.wificonnect():
                if wlan.isconnected():
                    break
        if not wlan.isconnected():
            print("[ERROR] [OTA] connecting to wifi failed. booting into main.py")
        else:
            concrete_update()
ota()
