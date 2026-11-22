"""Image helpers for the meme UI: real warbler photos + stickers/stamps.

Backgrounds, the mascot avatar and the "猜猜这是哪种" quiz all use real photos
from ``assets/photos`` (Wikimedia Commons, see ``credits.json``). Put your own
photos into ``assets/backgrounds/`` and they will be mixed in too.
"""
from functools import lru_cache
import json
from pathlib import Path
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ASSETS = Path(__file__).resolve().parents[1] / "assets"
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# ---------------------------------------------------------------- palette
PAPER = (246, 243, 226)
CARD = (255, 253, 244)
INK = (47, 54, 30)
INK_SOFT = (104, 112, 82)
OLIVE = (122, 138, 52)
YELLOW = (246, 211, 72)
STAMP_RED = (214, 64, 52)

FONT_CANDIDATES = (
    "C:/Windows/Fonts/STHUPO.TTF",          # 华文琥珀 (only with Office)
    "C:/Windows/Fonts/msyhbd.ttc",          # 微软雅黑 Bold
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
BODY_FONT_CANDIDATES = FONT_CANDIDATES[1:]
TITLE_FONT = ASSETS / "fonts/MaShanZheng-subset.ttf"   # 马善政毛笔楷书, SIL OFL (subset)
SERIF_ITALIC_CANDIDATES = (
    "C:/Windows/Fonts/georgiai.ttf", "C:/Windows/Fonts/timesi.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
)


@lru_cache(maxsize=16)
def serif_italic(size):
    for path in SERIF_ITALIC_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, int(size))
            except OSError:
                continue
    return font(size)


@lru_cache(maxsize=8)
def title_font(size):
    if TITLE_FONT.is_file():
        try:
            return ImageFont.truetype(str(TITLE_FONT), int(size))
        except OSError:
            pass
    return font(size, display=True)


@lru_cache(maxsize=64)
def font(size, display=False):
    for path in (FONT_CANDIDATES if display else BODY_FONT_CANDIDATES):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, int(size))
            except OSError:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------- photos
def load_photos(extra_dirs=()):
    """Return [{path, species_cn, author, license, source, focus}] for all photos."""
    photos = []
    credits_path = ASSETS / "photos/credits.json"
    if credits_path.is_file():
        try:
            for item in json.loads(credits_path.read_text(encoding="utf-8")):
                path = ASSETS / "photos" / item["file"]
                if path.is_file():
                    photos.append({**item, "path": path, "focus": tuple(item.get("focus") or (.5, .5))})
        except (OSError, ValueError, KeyError):
            pass
    for folder in (ASSETS / "backgrounds", *extra_dirs):
        folder = Path(folder)
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() in PHOTO_SUFFIXES and all(p["path"] != path for p in photos):
                    photos.append({"file": path.name, "path": path, "species_cn": None, "author": None,
                                   "license": None, "focus": (.5, .5), "user": True})
    return photos


def photo_stamp(path):
    path = Path(path)
    stat = path.stat()
    return path, stat.st_mtime_ns, stat.st_size


def open_photo(path):
    return _open_photo(*photo_stamp(path))


@lru_cache(maxsize=16)
def _open_photo(path, mtime_ns, size):
    with Image.open(path) as src:
        image = ImageOps.exif_transpose(src).convert("RGB")
    image.thumbnail((1920, 1920))
    return image


def focus_crop(image, width, height, focus=(.5, .5), zoom=1.0):
    """Cover-fit ``image`` into width x height keeping ``focus`` (0..1) in view."""
    ratio = max(width / image.width, height / image.height) * zoom
    w, h = max(width, int(image.width * ratio)), max(height, int(image.height * ratio))
    scaled = image.resize((w, h), Image.LANCZOS)
    fx, fy = focus
    x1 = min(max(0, int(fx * w - width / 2)), w - width)
    y1 = min(max(0, int(fy * h - height / 2)), h - height)
    return scaled.crop((x1, y1, x1 + width, y1 + height))


def photo_wallpaper(photo, width, height):
    """Real photo, cover-fit around the bird, slightly softened so cards pop."""
    image = focus_crop(open_photo(photo["path"]), width, height, photo.get("focus", (.5, .5)))
    image = image.filter(ImageFilter.GaussianBlur(1.2)).convert("RGBA")
    image.alpha_composite(Image.new("RGBA", (width, height), PAPER + (46,)))
    # darken the top band a touch so the title sticker reads well
    band = Image.linear_gradient("L").resize((width, max(1, int(height * .22))))
    band = ImageOps.invert(band).point(lambda v: int(v * .35))
    shade = Image.new("RGBA", band.size, (20, 26, 8, 0))
    shade.putalpha(band)
    image.alpha_composite(shade)
    return image


def hero_wallpaper(photo, width, height, hero_h, sharp_x, sharp_w):
    """Blurred full-window photo + a crisp, feather-edged strip showing the bird.

    Returns (RGBA image, (bird_x, bird_y)) where the bird point is in window coords.
    """
    image = open_photo(photo["path"])
    fx, fy = photo.get("focus", (.5, .5))
    # 1) atmosphere: small blurred cover crop scaled up, darkened with a leafy tint
    small = focus_crop(image, max(8, width // 6), max(8, height // 6), (fx, fy), zoom=1.25)
    base = small.filter(ImageFilter.GaussianBlur(3)).resize((width, height), Image.BICUBIC)
    base = Image.blend(base, Image.new("RGB", (width, height), (26, 34, 12)), .45)
    # 2) the real bird, sharp, right side of the hero band
    ramp = max(1, int(sharp_w * .32))
    if photo.get("fit") == "contain":
        scaled = ImageOps.contain(image, (max(1, sharp_w-ramp//2), max(1, hero_h-8)), Image.LANCZOS)
        sw, sh = scaled.size
        left, top = ramp//2 + (sharp_w-ramp//2-sw)//2, (hero_h-sh)//2
        strip = base.crop((sharp_x, 0, sharp_x+sharp_w, hero_h))
        # Feather the contained photo itself, including its top/right edges,
        # so portrait record crops do not form a hard rectangle on the wallpaper.
        ex, ey = max(2, min(24, sw//10)), max(2, min(12, sh//10))
        def smooth(t):
            t = max(0., min(1., t))
            return round(255 * t*t * (3-2*t))
        mx = Image.new("L", (sw, 1))
        mx.putdata([smooth(min(x/ex, (sw-1-x)/ex)) for x in range(sw)])
        my = Image.new("L", (1, sh))
        my.putdata([smooth(min(y/ey, (sh-1-y)/ey)) for y in range(sh)])
        edge_mask = ImageChops.multiply(mx.resize((sw, sh)), my.resize((sw, sh)))
        strip.paste(scaled, (left, top), edge_mask)
        x1, y1 = -left, -top
    else:
        ratio = max(sharp_w / image.width, hero_h / image.height)
        sw, sh = max(sharp_w, int(image.width * ratio)), max(hero_h, int(image.height * ratio))
        scaled = image.resize((sw, sh), Image.LANCZOS)
        x1 = min(max(0, int(fx * sw - sharp_w / 2)), sw - sharp_w)
        y1 = min(max(0, int(fy * sh - hero_h / 2)), sh - hero_h)
        strip = scaled.crop((x1, y1, x1 + sharp_w, y1 + hero_h))
    row = [int(255 * (3 * t * t - 2 * t * t * t)) for t in (min(1, i / ramp) for i in range(sharp_w))]
    mask = Image.new("L", (sharp_w, 1))
    mask.putdata(row)
    mask = mask.resize((sharp_w, hero_h))
    fade = max(1, hero_h // 12)
    bottom = Image.linear_gradient("L").resize((sharp_w, fade))
    bottom = ImageOps.invert(bottom)
    mask.paste(ImageChops.multiply(mask.crop((0, hero_h - fade, sharp_w, hero_h)), bottom), (0, hero_h - fade))
    base.paste(strip, (sharp_x, 0), mask)
    # 3) a soft dark wash behind the title area so white text always reads
    wash_w = max(1, sharp_x + ramp)
    wash = Image.linear_gradient("L").rotate(-90, expand=True).resize((wash_w, hero_h))
    wash = wash.point(lambda v: int(v * .55))
    layer = Image.new("RGBA", (wash_w, hero_h), (14, 18, 6, 0))
    layer.putalpha(wash)
    out = base.convert("RGBA")
    out.alpha_composite(layer, (0, 0))
    bird = (sharp_x + fx * sw - x1, fy * sh - y1)
    return out, bird


# ---------------------------------------------------------------- field-guide plates
@lru_cache(maxsize=1)
def load_reference_images():
    """Verified local reference media; kept separate from the home-page carousel."""
    folder = (ASSETS / "reference_images").resolve()
    try:
        document = json.loads((folder / "index.json").read_text(encoding="utf-8"))
        images = []
        for item in document.get("images", []):
            path = (folder / item["file"]).resolve()
            if path.is_relative_to(folder) and path.is_file():
                images.append({**item, "path": path, "bird_path": path,
                               "name_cn": item["common_name"], "reference_media": True})
        return tuple(images)
    except (OSError, ValueError, KeyError):
        return ()


def find_reference_image(scientific_name=None, common_name=None):
    images = load_reference_images()
    if scientific_name:
        name = str(scientific_name).strip().casefold()
        return next((item for item in images if item["scientific_name"].casefold() == name), None)
    return next((item for item in images if item["common_name"] == common_name), None)


def reference_credit(item):
    kind = "参考图版" if item.get("kind") == "illustration" else "参考照片"
    return " · ".join(str(value) for value in (kind, item.get("author"), item.get("license")) if value)


@lru_cache(maxsize=1)
def load_plates():
    """Plates cut from 《两岸三地50种柳莺类辨识》 (assets/plates/index.json)."""
    path = ASSETS / "plates/index.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    plates = []
    for item in doc.get("plates", []):
        file = ASSETS / "plates" / item["file"]
        bird = ASSETS / "plates" / item.get("bird_file", item["file"])
        if file.is_file():
            plates.append({**item, "path": file, "bird_path": bird if bird.is_file() else file})
    return tuple(plates)


def find_plate(scientific_name=None, common_name=None):
    """Match by species epithet first (survives genus changes like Seicercus -> Phylloscopus)."""
    plates = load_plates()
    if scientific_name:
        epithet = str(scientific_name).split()[-1].lower()
        for plate in plates:
            if epithet == plate["epithet"] or epithet in plate.get("aliases", ()):
                return plate
    if common_name:
        name = str(common_name).replace("咋", "喳").replace("（", "(").split("(")[0].strip()
        for plate in plates:
            if plate["name_cn"] == name:
                return plate
    return find_reference_image(scientific_name, common_name)


@lru_cache(maxsize=64)
def open_plate(path):
    with Image.open(path) as src:
        return src.convert("RGB")


def avatar(photo, size, ring=YELLOW, zoom=1.9):
    """Round sticker avatar of a real bird photo."""
    k = 3
    inner = size * k
    face = focus_crop(open_photo(photo["path"]), inner, inner, photo.get("focus", (.5, .5)), zoom=zoom)
    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner - 1, inner - 1), fill=255)
    out = Image.new("RGBA", (inner + 8 * k, inner + 8 * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    d.ellipse((0, 0, out.width - 1, out.height - 1), fill=(255, 255, 255, 255))
    d.ellipse((2 * k, 2 * k, out.width - 1 - 2 * k, out.height - 1 - 2 * k), fill=ring + (255,))
    out.paste(face, (4 * k, 4 * k), mask)
    return out.resize((size + 8, size + 8), Image.LANCZOS)


def polaroid(photo, width, height, zoom=1.0, tilt=0):
    """Photo print with a white frame and a soft shadow (RGBA)."""
    border = max(4, width // 28)
    pic = focus_crop(open_photo(photo["path"]), width - 2 * border, height - 2 * border,
                     photo.get("focus", (.5, .5)), zoom=zoom)
    card = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    card.paste(pic, (border, border))
    pad = 12
    out = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    ImageDraw.Draw(sh).rectangle((pad + 2, pad + 4, pad + width + 2, pad + height + 4), fill=90)
    shadow = Image.new("RGBA", out.size, (40, 50, 20, 0))
    shadow.putalpha(sh.filter(ImageFilter.GaussianBlur(5)))
    out.alpha_composite(shadow)
    out.alpha_composite(card, (pad, pad))
    if tilt:
        out = out.rotate(tilt, resample=Image.BICUBIC, expand=True)
    return out


# ---------------------------------------------------------------- shapes
def _rounded_card_image(w, h, radius, fill, outline=None, outline_width=2):
    """Generate the original antialiased card pixels, without a background."""
    card = Image.new("RGBA", ((w + 4) * 2, (h + 4) * 2), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    if outline:
        cd.rounded_rectangle((2, 2, (w + 1) * 2, (h + 1) * 2), radius * 2, fill=outline + (255,))
        ow = outline_width * 2
        cd.rounded_rectangle((2 + ow, 2 + ow, (w + 1) * 2 - ow, (h + 1) * 2 - ow), max(1, radius * 2 - ow), fill=fill + (255,))
    else:
        cd.rounded_rectangle((2, 2, (w + 1) * 2, (h + 1) * 2), radius * 2, fill=fill + (255,))
    return card.resize((w + 4, h + 4), Image.LANCZOS)


def rounded_card(base, box, radius, fill=CARD, outline=None, outline_width=2):
    x1, y1, x2, y2 = [int(v) for v in box]
    card = _rounded_card_image(x2 - x1, y2 - y1, radius, fill, outline, outline_width)
    base.alpha_composite(card, (x1 - 1, y1 - 1))


@lru_cache(maxsize=2)
def _card_layers(size, cards, radius, fill):
    """Two recent geometries only; returned layers are private and read-only.

    Keep shadow and cards separate: merging translucent layers in advance would
    change integer alpha-compositing roundoff against some wallpapers.
    """
    sh = Image.new("L", size, 0)
    sd = ImageDraw.Draw(sh)
    for x1, y1, x2, y2 in cards:
        sd.rounded_rectangle((x1 + 2, y1 + 6, x2 + 2, y2 + 6), radius, fill=110)
    layer = Image.new("RGBA", size, (25, 32, 10, 0))
    layer.putalpha(sh.filter(ImageFilter.GaussianBlur(7)))
    overlays = []
    for box in cards:
        x1, y1, x2, y2 = [int(v) for v in box]
        overlays.append((_rounded_card_image(x2 - x1, y2 - y1, radius, fill), (x1 - 1, y1 - 1)))
    return layer, tuple(overlays)


def compose(wall, cards, radius, fill=CARD):
    """Wallpaper + cached rounded cards, preserving the original blend order."""
    base = wall.copy()
    shadow, overlays = _card_layers(wall.size, tuple(tuple(box) for box in cards), radius, tuple(fill))
    base.alpha_composite(shadow)
    for card, position in overlays:
        base.alpha_composite(card, position)
    return base


def sticker_text(base, xy, text, size, fill=YELLOW, stroke=INK, stroke_width=None, display=True, shadow=True):
    f = font(size, display)
    stroke_width = stroke_width if stroke_width is not None else max(2, size // 10)
    x, y = xy
    if shadow:
        sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((x + 3, y + 5), text, font=f, fill=(20, 26, 8, 140),
                                stroke_width=stroke_width + 3, stroke_fill=(20, 26, 8, 140))
        base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(3)))
    d = ImageDraw.Draw(base)
    d.text((x, y), text, font=f, fill=fill, stroke_width=stroke_width + 3, stroke_fill=(255, 255, 255))
    d.text((x, y), text, font=f, fill=fill, stroke_width=stroke_width, stroke_fill=stroke)
    return d.textbbox((x, y), text, font=f, stroke_width=stroke_width + 3)


def green_title(text, size, typeface=None):
    """Brush-lettered title with a leaf-green gradient, dark outline and soft shadow."""
    f = typeface or title_font(size)
    stroke = max(2, size // 20)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    bb = probe.textbbox((0, 0), text, font=f, stroke_width=stroke)
    pad = size // 4
    W, H = bb[2] - bb[0] + pad * 2, bb[3] - bb[1] + pad * 2
    org = (pad - bb[0], pad - bb[1])
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text(org, text, font=f, fill=255)
    outline = Image.new("L", (W, H), 0)
    ImageDraw.Draw(outline).text(org, text, font=f, fill=255, stroke_width=stroke, stroke_fill=255)
    stops = ((0, (222, 242, 160)), (.48, (140, 194, 70)), (1, (46, 104, 26)))
    column = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / max(1, H - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0)
                column.putpixel((0, y), tuple(int(c0[i] + (c1[i] - c0[i]) * u) for i in range(3)))
                break
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (6, 12, 2, 0))
    shadow.putalpha(outline.filter(ImageFilter.GaussianBlur(size / 16)).point(lambda v: int(v * .75)))
    out.alpha_composite(shadow, (2, max(2, size // 18)))
    edge = Image.new("RGBA", (W, H), (16, 38, 8, 255))
    edge.putalpha(outline)
    out.alpha_composite(edge)
    fill = column.resize((W, H)).convert("RGBA")
    fill.putalpha(mask)
    out.alpha_composite(fill)
    shift = max(1, size // 40)
    lifted = mask.transform(mask.size, Image.AFFINE, (1, 0, 0, 0, 1, -shift))
    glint = Image.new("RGBA", (W, H), (248, 255, 222, 0))
    glint.putalpha(ImageChops.subtract(mask, lifted).point(lambda v: int(v * .55)))
    out.alpha_composite(glint)
    return out.crop(out.getbbox())


@lru_cache(maxsize=8)
def brand_title(size, without_bird=False):
    """Transparent botanical wordmark, fitted for the existing title band."""
    path = ASSETS / "branding/willow-title-wenkai.png"
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
        bounds = image.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError("Empty title artwork")
        if without_bird:
            # The code-drawn bird now moves independently. Keep the original
            # lettering, whitespace and scale, rather than generating a new logo.
            image.paste((0, 0, 0, 0), (0, 0, image.width, 116))
        image = image.crop(bounds)
        image.thumbnail((max(1, round(size * 4.8)), max(1, round(size * 1.5))), Image.LANCZOS)
        return image
    except (OSError, ValueError):
        return green_title("某种柳莺", size)


def call_tag(call, caption=None, size=14, playing=False):
    """Dark glassy tag: a bird-call transcription (and optionally a second, smaller line).

    The tail points right, towards the bird.
    """
    f_call = serif_italic(int(size * 1.3))
    f_cap = font(int(size * 1.0))
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    cb = probe.textbbox((0, 0), call, font=f_call)
    pb = probe.textbbox((0, 0), caption, font=f_cap) if caption else (0, 0, 0, 0)
    padx, pady, gap = size, int(size * .6), int(size * .35) if caption else 0
    note_w = int(size * 1.65)
    w = max(note_w + cb[2] - cb[0], pb[2] - pb[0]) + padx * 2
    h = (cb[3] - cb[1]) + (pb[3] - pb[1]) + gap + pady * 2
    tail = int(size * .8)
    k = 2
    img = Image.new("RGBA", ((w + tail + 2) * k, (h + 2) * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * .6)
    d.rounded_rectangle((k, k, w * k, h * k), r * k, fill=(16, 24, 8, 200), outline=(236, 244, 214, 110), width=k)
    my = min(h * k // 2, (pady + (cb[3] - cb[1]) // 2) * k + k)
    d.polygon([(w * k - k, my - tail * k // 2), ((w + tail) * k, my), (w * k - k, my + tail * k // 2)], fill=(16, 24, 8, 200))
    img = img.resize((w + tail + 2, h + 2), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    y = pady + 1
    # Draw a speaker instead of a font glyph: no missing-character square on Windows.
    icon = Image.new("RGBA", (54, 54), (0, 0, 0, 0))
    sd = ImageDraw.Draw(icon)
    colour = (214, 236, 150)
    sd.polygon([(3, 18), (10, 18), (21, 8), (21, 46), (10, 36), (3, 36)], fill=colour)
    if playing:
        sd.rectangle((29, 17, 40, 37), fill=colour)
    else:
        sd.arc((11, 10, 38, 44), -60, 60, fill=colour, width=3)
        sd.arc((9, 2, 50, 52), -55, 55, fill=colour, width=3)
    icon = icon.crop((0, 0, 54, 54)).resize((int(size * 1.3), int(size * 1.3)), Image.LANCZOS)
    img.alpha_composite(icon, (padx, max(1, y + (cb[3] - cb[1] - icon.height) // 2)))
    d = ImageDraw.Draw(img)
    d.text((padx + note_w - cb[0], y - cb[1]), call, font=f_call, fill=(255, 255, 255))
    if caption:
        d.text((padx - pb[0], y + cb[3] - cb[1] + gap - pb[1]), caption, font=f_cap, fill=(214, 236, 150))
    return img


def speech_bubble(base, box, text, size, tail="left"):
    x1, y1, x2, y2 = box
    rounded_card(base, box, (y2 - y1) // 2, fill=(255, 255, 255), outline=INK, outline_width=2)
    d = ImageDraw.Draw(base)
    my = (y1 + y2) // 2
    if tail == "left":
        d.polygon([(x1 + 3, my - 7), (x1 - 12, my + 10), (x1 + 8, my + 4)], fill=(255, 255, 255), outline=INK)
        d.line([(x1 + 4, my - 5), (x1 + 8, my + 3)], fill=(255, 255, 255), width=3)
    elif tail == "right":
        d.polygon([(x2 - 3, my - 7), (x2 + 12, my + 10), (x2 - 8, my + 4)], fill=(255, 255, 255), outline=INK)
        d.line([(x2 - 4, my - 5), (x2 - 8, my + 3)], fill=(255, 255, 255), width=3)
    f = font(size)
    bb = d.textbbox((0, 0), text, font=f)
    d.text(((x1 + x2 - (bb[2] - bb[0])) // 2, my - (bb[3] + bb[1]) // 2), text, font=f, fill=INK)


@lru_cache(maxsize=32)
def stamp(text, sub=None, color=STAMP_RED, size=34, angle=-12):
    """A rubber-stamp style verdict seal with transparent background."""
    f = font(size, display=True)
    fs = font(max(10, size // 3))
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bb = tmp.textbbox((0, 0), text, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    sw = sh_ = 0
    if sub:
        sb = tmp.textbbox((0, 0), sub, font=fs)
        sw, sh_ = sb[2] - sb[0], sb[3] - sb[1]
    pad = size // 2
    w = max(tw, sw) + pad * 2
    h = th + (sh_ + size // 4 if sub else 0) + pad * 2
    img = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # translucent white backing so the seal reads on busy photos
    d.rounded_rectangle((10, 10, 10 + w, 10 + h), size // 4, fill=(255, 255, 255, 120))
    c = tuple(color) + (235,)
    d.rounded_rectangle((10, 10, 10 + w, 10 + h), size // 4, outline=c, width=max(3, size // 9))
    d.rounded_rectangle((10 + size // 7, 10 + size // 7, 10 + w - size // 7, 10 + h - size // 7), size // 6,
                        outline=c, width=max(1, size // 22))
    d.text((10 + (w - tw) // 2 - bb[0], 10 + pad - bb[1]), text, font=f, fill=c)
    if sub:
        d.text((10 + (w - sw) // 2 - sb[0], 10 + pad + th + size // 4 - sb[1]), sub, font=fs, fill=c)
    rnd = random.Random(sum(map(ord, text)))
    speck = Image.new("L", img.size, 255)
    sd = ImageDraw.Draw(speck)
    for _ in range(int(img.width * img.height / 180)):
        x, y = rnd.uniform(0, img.width), rnd.uniform(0, img.height)
        r = rnd.uniform(.4, 1.5)
        sd.ellipse((x - r, y - r, x + r, y + r), fill=rnd.randint(0, 140))
    img.putalpha(ImageChops.multiply(img.getchannel("A"), speck))
    return img.rotate(angle, resample=Image.BICUBIC, expand=True)


def button_image(width, height, fill, border, radius=None, shadow=False, border_w=1):
    """Rounded pill used as a ttk image element (9-slice)."""
    radius = radius or height // 2
    k = 3
    img = Image.new("RGBA", (width * k, (height + 3) * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shadow:
        d.rounded_rectangle((0, 3 * k, width * k - 1, (height + 3) * k - 1), radius * k, fill=border + (255,))
    d.rounded_rectangle((0, 0, width * k - 1, height * k - 1), radius * k, fill=border + (255,))
    b = border_w * k
    d.rounded_rectangle((b, b, width * k - 1 - b, height * k - 1 - b), radius * k - b, fill=fill + (255,))
    return img.resize((width, height + 3), Image.LANCZOS)
