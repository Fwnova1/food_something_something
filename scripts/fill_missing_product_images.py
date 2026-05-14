import os
import re
import sqlite3
import time
import urllib.request


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "db.sqlite3")
MEDIA_DIR = os.path.join(BASE_DIR, "media", "products")


KEYWORD_MAP = {
    "organic carrots": "carrots,vegetable,farm",
    "free range eggs": "eggs,farm,food",
    "sourdough loaf": "sourdough,bread,bakery",
    "strawberry jam": "strawberry,jam,food",
    "organic milk": "milk,dairy,bottle",
    "spinach": "spinach,leafy,vegetable",
    "walnut bread": "walnut,bread,bakery",
    "apples": "apples,fruit,market",
    "cheddar cheese": "cheddar,cheese,dairy",
    "tomato sauce": "tomato,sauce,food",
}


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def download_image(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read()


def main() -> int:
    os.makedirs(MEDIA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT id, name, image FROM products_product ORDER BY id"
    ).fetchall()
    missing = [r for r in rows if not (r[2] or "").strip()]

    print(f"MISSING_BEFORE {len(missing)}")
    if not missing:
        print("No missing images.")
        conn.close()
        return 0

    updated = 0
    failed = []

    for pid, name, _ in missing:
        key = (name or "").strip().lower()
        tags = KEYWORD_MAP.get(key, re.sub(r"[^a-z0-9]+", ",", key).strip(","))
        filename = f"{slugify(key)}.jpg"
        rel_path = f"products/{filename}"
        abs_path = os.path.join(MEDIA_DIR, filename)
        source_url = f"https://loremflickr.com/1200/900/{tags}"

        try:
            data = download_image(source_url)
            if len(data) < 2000:
                raise RuntimeError(f"download too small: {len(data)} bytes")
            with open(abs_path, "wb") as f:
                f.write(data)
            cur.execute(
                "UPDATE products_product SET image = ? WHERE id = ?",
                (rel_path, pid),
            )
            conn.commit()
            updated += 1
            print(f"UPDATED {pid} {name} -> {rel_path} ({len(data)} bytes)")
            time.sleep(0.4)
        except Exception as exc:
            failed.append((pid, name, str(exc)))
            print(f"FAILED {pid} {name}: {exc}")

    missing_after = cur.execute(
        "SELECT COUNT(*) FROM products_product WHERE image IS NULL OR TRIM(image) = ''"
    ).fetchone()[0]

    print(f"UPDATED_COUNT {updated}")
    print(f"FAILED_COUNT {len(failed)}")
    print(f"MISSING_AFTER {missing_after}")
    for pid, name, reason in failed:
        print(f"FAILED_DETAIL {pid} {name}: {reason}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
