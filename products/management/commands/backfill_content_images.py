from __future__ import annotations

import hashlib
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from products.models import ContentPost


class Command(BaseCommand):
    help = "Download and attach cover images for content posts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only set images for posts with empty cover_image (default behavior).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing cover images.",
        )

    def handle(self, *args, **options):
        only_missing = options["only_missing"] or not options["overwrite"]
        qs = ContentPost.objects.all().order_by("id")
        if only_missing:
            qs = qs.filter(cover_image="")

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No posts matched the criteria."))
            return

        updated = 0
        failed = 0

        for post in qs:
            query = f"{post.content_type} {post.title} farm food"
            image_url = self._build_image_url(query, post.id)

            try:
                content, ext = self._download_image(image_url)
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"[{post.id}] Failed download: {exc}"))
                continue

            filename = f"content_{post.id}_{self._slug_token(post.title)}.{ext}"
            post.cover_image.save(filename, ContentFile(content), save=True)
            updated += 1
            self.stdout.write(self.style.SUCCESS(f"[{post.id}] Image applied -> {filename}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Done. Updated={updated}, Failed={failed}, Total={total}"))

    def _build_image_url(self, query: str, post_id: int) -> str:
        # Stable random image by seed so reruns are deterministic enough per post.
        seed = quote_plus(f"{post_id}-{query}")
        return f"https://picsum.photos/seed/{seed}/1200/800"

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

    def _slug_token(self, text: str) -> str:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        return digest
