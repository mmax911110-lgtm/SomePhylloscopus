"""Bounded thumbnails for display only; never used for recognition inputs."""
from collections import OrderedDict
from math import ceil, floor
from pathlib import Path
from threading import RLock

from PIL import Image, ImageOps

_MAX_ITEMS = 64
_MAX_RGB_BYTES = 16 * 1024 * 1024
_cache = OrderedDict()
_cache_bytes = 0
_lock = RLock()


def clear_cache():
    global _cache_bytes
    with _lock:
        _cache.clear()
        _cache_bytes = 0


def cache_info():
    with _lock:
        return {"items": len(_cache), "rgb_bytes": _cache_bytes,
                "max_items": _MAX_ITEMS, "max_rgb_bytes": _MAX_RGB_BYTES}


def _contain_size(original, bounds):
    """Keep Pillow thumbnail's aspect rounding, before JPEG draft changes size."""
    ow, oh = original
    w, h = bounds
    if w >= ow and h >= oh:
        return original
    aspect = ow / oh
    if w / h >= aspect:
        value = h * aspect
        w = max(1, min((floor(value), ceil(value)), key=lambda n: abs(aspect - n / h)))
    else:
        value = w / aspect
        h = max(1, min((floor(value), ceil(value)), key=lambda n: 0 if n == 0 else abs(aspect - w / n)))
    return w, h


def _oriented_box(box, size, orientation):
    """JPEG draft may pad an odd edge; rotate its valid fractional rectangle too."""
    w, h = size
    transforms = {
        2: lambda x, y: (w-x, y), 3: lambda x, y: (w-x, h-y),
        4: lambda x, y: (x, h-y), 5: lambda x, y: (y, x),
        6: lambda x, y: (h-y, x), 7: lambda x, y: (h-y, w-x),
        8: lambda x, y: (y, w-x),
    }
    transform = transforms.get(orientation, lambda x, y: (x, y))
    points = [transform(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def load_thumbnail(path, size, cover=False):
    """Return an independent RGB image, EXIF-correct, with the original UI crop.

    ``cover`` gives exactly ``size`` with a centred crop; contain fits within
    the bounds without enlargement. Source bytes and metadata are never saved.
    The shared LRU stores only resized RGB pixels, not Tk objects/full originals.
    """
    global _cache_bytes
    bounds = tuple(floor(value) for value in size)
    if len(bounds) != 2 or min(bounds) < 1:
        raise ValueError("Thumbnail size must contain two positive dimensions")
    file = Path(path).resolve()
    stat = file.stat()
    key = (str(file), stat.st_mtime_ns, stat.st_size, bounds, bool(cover))
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached.copy()
    with Image.open(file) as source:
        orientation = source.getexif().get(274, 1)
        original = source.size[::-1] if orientation in (5, 6, 7, 8) else source.size
        box = (0, 0, *source.size)
        if source.format == "JPEG":
            target = bounds[::-1] if orientation in (5, 6, 7, 8) else bounds
            # Preserve at least two decoder pixels per requested pixel. Calling
            # exif_transpose/convert first would already force full-size decode.
            draft = source.draft("RGB", tuple(value * 2 for value in target))
            if draft is not None:
                box = draft[1]
        box = _oriented_box(box, source.size, orientation)
        image = ImageOps.exif_transpose(source) if orientation in range(2, 9) else source
        if image.mode != "RGB":
            image = image.convert("RGB")
        if cover:
            ratio = max(bounds[0] / original[0], bounds[1] / original[1])
            scaled_size = tuple(max(1, round(value * ratio)) for value in original)
            scaled = image.resize(scaled_size, Image.Resampling.LANCZOS, box=box)
            x, y = ((scaled_size[i] - bounds[i]) // 2 for i in (0, 1))
            image = scaled.crop((x, y, x + bounds[0], y + bounds[1]))
        else:
            image = image.resize(_contain_size(original, bounds), Image.Resampling.LANCZOS,
                                 box=box, reducing_gap=2.0)
    image.info.clear()
    cost = image.width * image.height * 3
    if cost <= _MAX_RGB_BYTES:
        with _lock:
            # Remove stale variants of the same replaced source, then evict LRU.
            for old_key in tuple(_cache):
                if old_key[0] == key[0] and old_key[1:3] != key[1:3]:
                    old = _cache.pop(old_key)
                    _cache_bytes -= old.width * old.height * 3
            previous = _cache.pop(key, None)
            if previous is not None:
                _cache_bytes -= previous.width * previous.height * 3
            while _cache and (len(_cache) >= _MAX_ITEMS or _cache_bytes + cost > _MAX_RGB_BYTES):
                _, old = _cache.popitem(last=False)
                _cache_bytes -= old.width * old.height * 3
            _cache[key] = image
            _cache_bytes += cost
        return image.copy()
    return image
