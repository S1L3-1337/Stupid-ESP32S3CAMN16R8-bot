import ugit
from machine import reset
import random

try:
    ugit.wificonnect()
    dyn_branch = f"main?cb={random.randint(100_000, 999_999)}"
    uflag = ugit.check_for_updates(isconnected=True, branch=dyn_branch)
    if (uflag["new"] or uflag["changed"] or uflag["deleted"]):
        print("[INFO] [OTA] New updates found. Downloading...")
        ugit.backup()
        ugit.pull_all(isconnected=True, branch=dyn_branch)
        print("[INFO] [OTA] Update complete. Rebooting...")
        reset()
    else:
        print("[INFO] [OTA] System is up to date.")

except Exception as e:
    print(f"[ERROR] [OTA] Update operation failed: {e}")
    print("[ERROR] [OTA] Restoring previous backup...")
    try:
        ugit.restore()
        print("[INFO] [OTA] Backup restored successfully. Rebooting...")
        reset()
    except Exception as rollback_error:
        print(f"[ERROR] [OTA] Rollback failed: {rollback_error}")
