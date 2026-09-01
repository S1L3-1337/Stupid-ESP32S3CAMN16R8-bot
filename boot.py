import ugit
from machine import reset
import gc
import errno

try:
    gc.collect()
    gc.collect()
    network_codes = [errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET, errno.ETIMEDOUT]
    ugit.wificonnect()
    uflag = ugit.check_for_updates(isconnected=True, branch="main")
    if (uflag["new"] or uflag["changed"] or uflag["deleted"]):
        print("[INFO] [OTA] New updates found. Downloading...")
        ugit.backup()
        ugit.pull_all(isconnected=True, branch="main")
        print("[INFO] [OTA] Update complete. Rebooting...")
        reset()
    else:
        print("[INFO] [OTA] System is up to date.")

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
                    print("[ERROR] [OTA] Restoring previous backup...")
                    try:
                        if ugit.restore():
                            print("[INFO] [OTA] Backup restored successfully. Rebooting...")
                            reset()
                        else:
                            raise Exception
                    except Exception as rollback_error:
                        print(f"[ERROR] [OTA] Rollback failed: {rollback_error}")
    else:
        print("[ERROR] [OTA] Restoring previous backup...")
        try:
            if ugit.restore():
                print("[INFO] [OTA] Backup restored successfully. Rebooting...")
                reset()
            else:
                raise Exception
        except Exception as rollback_error:
            print(f"[ERROR] [OTA] Rollback failed: {rollback_error}")
