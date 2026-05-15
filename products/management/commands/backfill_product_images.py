from __future__ import annotations

from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from products.models import Product


class Command(BaseCommand):
    help = "Download and attach images for products."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only set images for products with empty image (default behavior).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing product images.",
        )

    def handle(self, *args, **options):
        only_missing = options["only_missing"] or not options["overwrite"]
        qs = Product.objects.all().order_by("id")
        if only_missing:
            qs = qs.filter(image="")

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No products matched the criteria."))
            return

        updated = 0
        failed = 0
        for product in qs:
            query = f"{product.name} fresh food product"
            image_url = self._build_image_url(query, product.id)
            try:
                content, ext = self._download_image(image_url)
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"[{product.id}] Failed download for '{product.name}': {exc}"))
                continue

            filename = f"{slugify(product.name) or f'product-{product.id}'}-{product.id}.{ext}"
            product.image.save(filename, ContentFile(content), save=True)
            updated += 1
            self.stdout.write(self.style.SUCCESS(f"[{product.id}] Image applied -> {filename}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Done. Updated={updated}, Failed={failed}, Total={total}"))

    def _build_image_url(self, query: str, product_id: int) -> str:
        seed = quote_plus(f"{product_id}-{query}")
        return f"https://picsum.photos/seed/{seed}/900/700"

    def _download_image(self, url: str) -> tuple[bytes, str]:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read()
        if not data:
            raise RuntimeError("empty image response")

        if "png" in content_type:
            ext = "png"
        elif "webp" in content_type:
            ext = "webp"
        else:
            ext = "jpg"
        return data, ext
