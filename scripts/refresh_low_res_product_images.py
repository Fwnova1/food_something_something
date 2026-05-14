import os
import re
import sqlite3
import time
import urllib.request


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "db.sqlite3")
MIN_BYTES = 60_000


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, name, image FROM products_product WHERE image IS NOT NULL AND TRIM(image) <> '' ORDER BY id"
    ).fetchall()

    low_res = []
    for pid, name, image in rows:
        image_path = os.path.join(BASE_DIR, "media", image.replace("/", os.sep))
        if os.path.exists(image_path):
            size = os.path.getsize(image_path)
            if size < MIN_BYTES:
                low_res.append((pid, name, image_path, size))

    print(f"LOW_RES_COUNT {len(low_res)}")
    updated = 0
    failed = []

    for pid, name, image_path, old_size in low_res:
        tags = re.sub(r"[^a-z0-9]+", ",", (name or "").lower()).strip(",") or "food,produce"
        url = f"https://loremflickr.com/1600/1200/{tags}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = resp.read()
            if len(data) < MIN_BYTES:
                raise RuntimeError(f"download still low: {len(data)} bytes")
            with open(image_path, "wb") as f:
                f.write(data)
            updated += 1
            print(f"UPDATED {pid} {name}: {old_size} -> {len(data)}")
            time.sleep(0.35)
        except Exception as exc:
            failed.append((pid, name, str(exc)))
            print(f"FAILED {pid} {name}: {exc}")

    print(f"UPDATED_COUNT {updated}")
    print(f"FAILED_COUNT {len(failed)}")
    for pid, name, reason in failed:
        print(f"FAILED_DETAIL {pid} {name}: {reason}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
