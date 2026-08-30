import ugit
from machine import reset

def run_ota():
    try:
        ugit.wificonnect()

        if ugit.check_for_updates(isconnected=True):
            print("[INFO] [OTA] New updates found. Downloading...")
            ugit.safe_pull_all(isconnected=True)
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
run_ota()
