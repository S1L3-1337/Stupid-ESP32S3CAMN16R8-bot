import ugit
from machine import reset
import gc

try:
    gc.collect()
    gc.collect()
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
    print("[ERROR] [OTA] Restoring previous backup...")
    try:
        if ugit.restore():
            print("[INFO] [OTA] Backup restored successfully. Rebooting...")
            reset()
        else:
            raise Exception
    except Exception as rollback_error:
        print(f"[ERROR] [OTA] Rollback failed: {rollback_error}")
