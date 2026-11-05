import hashlib
import logging
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .source_catalog import CableSourceError, catalog_request_headers, is_catalog_url


logger = logging.getLogger(__name__)

THUMB_RELATIVE_DIR = Path("cable_mall") / "product_thumbs"
THUMB_SIZE = (128, 96)
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def first_product_image(product) -> str:
    images = product.product_images or []
    if not isinstance(images, list):
        return ""
    return str(images[0] or "").strip() if images else ""


def product_thumb_relative_path(product) -> str:
    image_url = first_product_image(product)
    if not image_url:
        return ""
    source_id = str(product.product_archive_id or product.pk or "product")
    cache_key = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:16]
    return f"{THUMB_RELATIVE_DIR.as_posix()}/{source_id}-{cache_key}.jpg"


def product_thumb_path(product):
    relative_path = product_thumb_relative_path(product)
    if not relative_path:
        return None
    return Path(settings.MEDIA_ROOT) / relative_path


def product_thumb_url(product) -> str:
    thumb_path = product_thumb_path(product)
    if not thumb_path or not thumb_path.exists():
        return ""
    return f"{settings.MEDIA_URL.rstrip('/')}/{product_thumb_relative_path(product)}"


def ensure_product_thumbnail(product, *, force: bool = False) -> bool:
    image_url = first_product_image(product)
    thumb_path = product_thumb_path(product)
    if not image_url or thumb_path is None:
        return False
    if thumb_path.exists() and not force:
        return False

    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "mj-program-cable-mall/1.0"}
    try:
        if is_catalog_url(image_url):
            headers.update(catalog_request_headers())
    except CableSourceError as exc:
        logger.warning("Product archive image credentials are unavailable: %s", exc)
        return False
    request = Request(image_url, headers=headers)

    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        logger.warning("Pillow is unavailable, skip product thumbnail generation: %s", exc)
        return False

    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("source image is too large")

        with Image.open(BytesIO(raw)) as image:
            image.thumbnail(THUMB_SIZE)
            canvas = Image.new("RGB", THUMB_SIZE, "white")
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            x = (THUMB_SIZE[0] - image.width) // 2
            y = (THUMB_SIZE[1] - image.height) // 2
            canvas.paste(image, (x, y))
            canvas.save(thumb_path, format="JPEG", quality=78, optimize=True)
        return True
    except (OSError, UnidentifiedImageError, ValueError, URLError) as exc:
        logger.warning(
            "Failed to generate cable product thumbnail product_id=%s source_id=%s: %s",
            getattr(product, "pk", ""),
            getattr(product, "product_archive_id", ""),
            exc,
        )
        return False


def ensure_product_thumbnails(products, *, force: bool = False) -> dict:
    created = 0
    existing = 0
    skipped = 0
    failed = 0
    for product in products:
        thumb_path = product_thumb_path(product)
        if thumb_path is None:
            skipped += 1
            continue
        if thumb_path.exists() and not force:
            existing += 1
            continue
        if ensure_product_thumbnail(product, force=force):
            created += 1
        else:
            failed += 1
    return {
        "created": created,
        "existing": existing,
        "skipped": skipped,
        "failed": failed,
    }
