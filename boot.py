import ugit
from machine import reset
import gc
import errno

backup_created = False
network_codes = [errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET, errno.ETIMEDOUT]

def rollback_mechanism():
    if backup_created:
        print("[ERROR] [OTA] Restoring previous backup...")
        try:
            if ugit.restore():
                print("[INFO] [OTA] Backup restored successfully. Rebooting...")
                reset()
            else:
                raise Exception
        except Exception as rollback_error:
            print(f"[ERROR] [OTA] Rollback failed: {rollback_error}")
            print("[ERROR] [OTA] booting into main.py...")
            return None
    else:
        print("[ERROR] [OTA] there is no backup to restore. booting into main.py...")
        return None

def concrete_check():
    for i in range(10):
        try:
            return ugit.check_for_updates()
        except Exception as e:
            if isinstance(e, OSError):
                print(e)
                if i < 4:
                    continue
                else:
                    print("[ERROR] [OTA] checking for updates failed. probably due to network related issue.\nbooting into main.py")
                    return None
            else: # not network related.
                print("[ERROR] [OTA] checking for updates failed due to non-network related issue.\nbooting into main.py")
                return None

def concrete_update():
    global backup_created
    try:
        print("[INFO] [OTA] Checking for updates...")
        uflag = concrete_check()
        if uflag is not None:
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
        else:
            pass

    except Exception as e0:
        print(f"[ERROR] [OTA] Update operation failed: {e0}")
        if isinstance(e0, OSError) and e0.args:
            err_code = e0.errno if hasattr(e0, 'errno') else e0.args[0]
            if err_code in network_codes:
                print(f"[ERROR] [OTA] update operation failed due to netowork error: {err_code}")
                print("[INFO] [OTA] retrying the update operation...")
                for repeat in range(10):
                    try:
                        gc.collect()
                        gc.collect()
                        ugit.pull_all(isconnected=True, branch="main")
                        print("[INFO] [OTA] Update complete. Rebooting...")
                        reset()
                    except Exception as e1:
                        if isinstance(e1, OSError):
                            err_code = e1.errno if hasattr(e1, 'errno') else e1.args[0]
                            if (err_code in network_codes) and repeat < 4:
                                continue
                            elif err_code not in network_codes:
                                print("[ERROR] [OTA] retry-update operations failed due to non-network OSError. [POS=-1]")
                                rollback_mechanism()
                                break
                            else:
                                print("[ERROR] [INFO] retrying failed... booting into main.py")
                                break
                        else:
                            print("[ERROR] [OTA] retry-update operations failed due to non-network error. [POS=0]")
                            rollback_mechanism()
                            break
            else:
                print("[ERROR] [OTA] retry-update operations failed due to non-network OSError [POS=1]")
                rollback_mechanism()
        else:
            print("[ERROR] [OTA] retry-update operations failed due to non-network error. [POS=2]")
            rollback_mechanism()

def ota():
    try:
        gc.collect()
        gc.collect()
        wlan = ugit.wificonnect() # it will raise OSError after 30 tries so lets catch it.
        if wlan.isconnected():
            concrete_update()
        else:
            for i in range(5):
                ugit.wifidisconnect()
                wlan = ugit.wificonnect() # removed walrus to maintain consistency. instead we will capture OSError
                if wlan.isconnected():
                    break
            if not wlan.isconnected():
                print("[ERROR] [OTA] connecting to wifi failed. booting into main.py")
            else:
                concrete_update()
    except OSError:
        print("[ERROR] [OTA] connecting to wifi failed. booting into main.py...")
ota()
