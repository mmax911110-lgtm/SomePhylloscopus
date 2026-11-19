"""Willow sprays and a small, restless, mouse-shy leaf warbler for the title band.

* The bird is drawn from smooth bezier shapes (supersampled), with real field
  marks: pale supercilium, dark eye-stripe, two pale wing-bars, short legs.
  Frames: perch / tail-flick / crouch / bounding-flight flaps / glide / landing.
* Branches: one perch twig under the title plus a few hanging willow strands in
  the visible title band — no ornaments on every card.
* The Windows sprite is a click-through layered CHILD window: it cannot become
  a desktop pet, take keyboard focus, or cover another application. No GPU/model
  or timer thread is used.
"""
from functools import lru_cache
import math
import os
import random
import time

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

# =====================================================================  the bird
SS = 4                      # supersampling
UW, UH = 200, 180           # unit box of every frame (bird faces left)
OY = 24                     # global downward shift so raised wings fit
ANCHOR = (98, 113 + OY)     # feet / perch contact point in unit coords


def _cubic(p0, p1, p2, p3, n=18):
    out = []
    for i in range(n + 1):
        t = i / n
        a = (1 - t) ** 3
        b = 3 * (1 - t) ** 2 * t
        c = 3 * (1 - t) * t * t
        d = t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def _path(start, segments):
    pts = [start]
    cur = start
    for c1, c2, end in segments:
        pts.extend(_cubic(cur, c1, c2, end)[1:])
        cur = end
    return pts


def _xf(points, dx=0, dy=0, angle=0, origin=(0, 0), sx=1, sy=1):
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    ox, oy = origin
    out = []
    for x, y in points:
        x, y = (x - ox) * sx, (y - oy) * sy
        out.append((ox + x * ca - y * sa + dx, oy + x * sa + y * ca + dy))
    return out


def _S(points):
    return [(x * SS, (y + OY) * SS) for x, y in points]


def _mask(points):
    m = Image.new("L", (UW * SS, UH * SS), 0)
    ImageDraw.Draw(m).polygon(_S(points), fill=255)
    return m


def _fill(canvas, mask, color):
    layer = Image.new("RGBA", canvas.size, color if len(color) == 4 else color + (255,))
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    canvas.alpha_composite(layer)


def _vgradient(size, stops):
    """stops: [(y_unit, (r,g,b)), ...] -> RGBA image."""
    w, h = size
    col = Image.new("RGBA", (1, h))
    for y in range(h):
        yu = y / SS - OY
        for (y0, c0), (y1, c1) in zip(stops, stops[1:]):
            if yu <= y0:
                col.putpixel((0, y), c0 + (255,)); break
            if y0 <= yu <= y1:
                u = (yu - y0) / max(1e-6, y1 - y0)
                col.putpixel((0, y), tuple(int(c0[i] + (c1[i] - c0[i]) * u) for i in range(3)) + (255,)); break
        else:
            col.putpixel((0, y), stops[-1][1] + (255,))
    return col.resize((w, h))


def _stroke(draw, points, color, width):
    draw.line(_S(points), fill=color, width=max(1, int(width * SS)), joint="curve")


OLIVE = (122, 140, 66)
OLIVE_DK = (88, 104, 48)
WING = (92, 106, 52)
WING_DK = (64, 76, 38)
PALE = (238, 238, 206)
BROW = (236, 232, 168)
BAR = (226, 228, 176)
INK = (34, 36, 24)


def _body(dy=0, crouch=0.0):
    """Head + body silhouette (one smooth outline)."""
    c = crouch
    segs = [
        ((44, 38 + dy), (58, 30 + dy), (73, 31 + dy)),                 # forehead -> crown
        ((88, 32 + dy), (98, 41 + dy), (110, 50 + dy)),                # nape
        ((124, 58 + dy), (138, 68 + dy + c * 2), (147, 78 + dy + c * 2)),  # back -> rump
        ((149, 85 + dy + c), (144, 91 + dy + c), (134, 93 + dy + c)),  # undertail
        ((116, 101 + dy + c), (94, 104 + dy + c), (78, 99 + dy + c)),  # belly
        ((60, 95 + dy), (47, 83 + dy), (44, 70 + dy)),                 # breast
        ((42, 64 + dy), (40, 58 + dy), (40, 55 + dy)),                 # throat
    ]
    return _path((40, 52 + dy), segs)


def _tail(dy=0, lift=0.0, spread=0.0):
    root = (138, 78 + dy)
    pts = [(134, 72 + dy), (192, 96 + dy - spread), (197, 101 + dy), (191, 106 + dy + spread), (130, 90 + dy)]
    return _xf(pts, angle=-lift, origin=root)


def _folded_wing(dy=0):
    return _path((78, 52 + dy), [
        ((96, 46 + dy), (120, 54 + dy), (140, 70 + dy)),
        ((152, 78 + dy), (162, 85 + dy), (170, 90 + dy)),
        ((152, 90 + dy), (124, 86 + dy), (100, 80 + dy)),
        ((86, 76 + dy), (76, 66 + dy), (78, 52 + dy)),
    ])


def _open_wing(shoulder, angle, length=78, fold=1.0, near=True):
    """Spread wing in local coords (+x towards the wing tip), rotated about the shoulder."""
    L = length * fold
    pts = _path((0, 0), [((L * .28, -9), (L * .72, -8), (L, -1))])          # leading edge to tip
    # trailing edge: five gently scalloped flight feathers, tip -> body
    xs = [L, L * .86, L * .72, L * .58, L * .44, L * .3]
    ys = [-1, 9, 15, 19, 21, 22]
    for i in range(5):
        a, b = (xs[i], ys[i]), (xs[i + 1], ys[i + 1])
        mid = ((a[0] + b[0]) / 2 + 2, (a[1] + b[1]) / 2 + 4.5)
        pts += _cubic(a, mid, mid, b, 6)[1:]
    pts += _cubic((xs[-1], ys[-1]), (L * .16, 22), (4, 18), (0, 12), 8)[1:]
    out = _xf(pts, angle=angle, origin=(0, 0))
    return [(x + shoulder[0], y + shoulder[1]) for x, y in out]


def _head_details(d, dy=0, blink=False):
    # supercilium (the eyebrow everyone stares at)
    _stroke(d, _path((45, 45 + dy), [((54, 39 + dy), (70, 38 + dy), (86, 43 + dy))]), BROW + (255,), 3.4)
    # eye-stripe
    _stroke(d, _path((41, 53 + dy), [((50, 50 + dy), (60, 50 + dy), (80, 53 + dy))]), (66, 74, 38, 235), 2.6)
    # eye
    if blink:
        _stroke(d, [(54, 51 + dy), (58, 52 + dy), (62, 50 + dy)], INK + (255,), 1.6)
    else:
        d.ellipse(_S([(54.2, 46.2 + dy), (62.4, 54.4 + dy)]), fill=INK + (255,))
        d.ellipse(_S([(55.6, 47.4 + dy), (58.0, 49.8 + dy)]), fill=(250, 252, 236, 255))
        d.arc(_S([(53.4, 45.6 + dy), (63.2, 55.4 + dy)]), 30, 150, fill=PALE + (220,), width=SS)
    # bill
    d.polygon(_S([(41.5, 50 + dy), (23, 54.5 + dy), (41.5, 55.5 + dy)]), fill=(58, 50, 36, 255))
    d.polygon(_S([(41.5, 54.6 + dy), (25, 55.2 + dy), (41.5, 57.6 + dy)]), fill=(196, 160, 108, 255))


def _legs(d, dy=0, crouch=0.0):
    leg = (146, 116, 90, 255)
    foot = ANCHOR[1] - OY
    for x0, x1 in ((92, 90), (103, 104)):
        top = 98 + dy - crouch * 2
        _stroke(d, [(x0, top), (x0 - 1 + crouch, (top + foot) / 2), (x1, foot - .5)], leg, 1.9)
        _stroke(d, [(x1 - 6, foot + .4), (x1 + 5, foot + .4)], leg, 1.6)
        _stroke(d, [(x1 + 1, foot - .6), (x1 + 4, foot + 1.2)], leg, 1.3)


@lru_cache(maxsize=512)
def frame(kind="perch", phase=0, width=72, facing_right=False, tilt=0):
    """kind: perch | flick | crouch | glide | flap (phase 0..7) | brake. Cheap after the base render."""
    out = _base_frame(kind, phase, width)
    if tilt:
        scale = width / UW
        out = out.rotate(tilt, resample=Image.BICUBIC, center=(ANCHOR[0] * scale, ANCHOR[1] * scale))
    if facing_right:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    return out


FRAME_KINDS = [("perch", 0), ("flick", 0), ("crouch", 0), ("glide", 0), ("brake", 0)] + [("flap", i) for i in range(8)] + [("blink", 0)]


def prewarm(width):
    """Render every base pose once (safe to call from a worker thread: pure Pillow)."""
    for kind, phase in FRAME_KINDS:
        _base_frame(kind, phase, width)


@lru_cache(maxsize=64)
def _base_frame(kind="perch", phase=0, width=72):
    img = Image.new("RGBA", (UW * SS, UH * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    crouch = {"crouch": 1.0, "brake": .4}.get(kind, 0.0)
    dy = 8 if kind == "crouch" else 0
    flying = kind in ("flap", "glide", "brake")
    if flying:
        dy = 10
    # far wing (behind the body) when flying
    angles = (-78, -60, -30, 6, 38, 52, 28, -40)
    if kind == "flap":
        ang = angles[phase % 8]
        fold = .62 + .38 * abs(math.cos(math.radians(ang)))
    elif kind == "brake":
        ang, fold = -62, .95
    shoulder = (86, 56 + dy)
    if kind in ("flap", "brake"):
        far = _open_wing((shoulder[0] + 8, shoulder[1] - 3), ang - 16, 74, fold * .85)
        _fill(img, _mask(far), WING_DK + (255,))
    # tail
    tail = _tail(dy, lift={"flick": 14, "brake": -8}.get(kind, 0) + (4 if flying else 0),
                 spread=4 if kind == "brake" else 0)
    tmask = _mask(tail)
    _fill(img, tmask, (84, 92, 50))
    _stroke(d, [(140, 82 + dy), (194, 101 + dy)], (70, 78, 40, 160), .8)
    # body with soft vertical shading
    body = _body(dy, crouch)
    bmask = _mask(body)
    grad = _vgradient(img.size, [(30 + dy, (128, 146, 70)), (62 + dy, (150, 164, 92)),
                                 (78 + dy, (214, 218, 168)), (100 + dy, PALE)])
    grad.putalpha(bmask)
    img.alpha_composite(grad)
    # back/mantle darker wash on top
    mantle = _mask(_path((70, 30 + dy), [((96, 30 + dy), (128, 52 + dy), (150, 78 + dy)),
                                          ((120, 68 + dy), (96, 58 + dy), (70, 50 + dy))]))
    m = ImageChops.multiply(mantle, bmask).filter(ImageFilter.GaussianBlur(3 * SS))
    _fill(img, m.point(lambda v: int(v * .55)), OLIVE_DK)
    # cheek/throat paler
    cheek = _mask(_path((44, 58 + dy), [((52, 56 + dy), (70, 58 + dy), (78, 66 + dy)),
                                         ((70, 80 + dy), (52, 80 + dy), (44, 70 + dy))]))
    _fill(img, ImageChops.multiply(cheek, bmask).filter(ImageFilter.GaussianBlur(2 * SS)).point(lambda v: int(v * .7)),
          (232, 232, 196))
    _head_details(d, dy, blink=kind == "blink")
    # wing
    if kind in ("flap", "brake"):
        near = _open_wing(shoulder, ang, 84, fold)
        nmask = _mask(near)
        wg = _vgradient(img.size, [(0, (110, 126, 60)), (170, (80, 94, 44))])
        wg.putalpha(nmask)
        img.alpha_composite(wg)
        # wing-bars across the coverts + feather separations
        L = 84 * fold
        for k in (.2, .33):
            a = _xf(_path((L * k, -6), [((L * k + 1, 2), (L * k + 3, 8), (L * k + 6, 14))]), angle=ang)
            _stroke(d, [(x + shoulder[0], y + shoulder[1]) for x, y in a], BAR + (200,), 2.2)
        for k in (.5, .62, .74, .86):
            a = _xf([(L * k + 2, 2), (L * (k - .04), 18)], angle=ang)
            _stroke(d, [(x + shoulder[0], y + shoulder[1]) for x, y in a], WING_DK + (170,), .8)
    else:
        wing = _folded_wing(dy + crouch * 2)
        wmask = _mask(wing)
        wg = _vgradient(img.size, [(50 + dy, (104, 120, 56)), (90 + dy, (78, 90, 42))])
        wg.putalpha(wmask)
        img.alpha_composite(wg)
        bars = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(bars)
        for x0, w0 in ((93, 2.4), (106, 2.0)):
            band = _path((x0 + 2, 55 + dy), [((x0 + 1, 62 + dy), (x0 - 1, 70 + dy), (x0 - 5, 78 + dy))])
            _stroke(bd, band, (240, 238, 196, 210), w0)
        bars.putalpha(ImageChops.multiply(bars.getchannel("A").filter(ImageFilter.GaussianBlur(.6 * SS)), wmask))
        img.alpha_composite(bars)
        for i in range(4):   # tertial / primary edges
            _stroke(d, [(118 + i * 9, 64 + dy + i * 3), (150 + i * 5, 84 + dy + i * 1.2)], (196, 200, 150, 140), .9)
    if not flying:
        _legs(d, dy, crouch)
    # thin dark rim so the bird reads on any background
    alpha = img.getchannel("A")
    rim = alpha.filter(ImageFilter.GaussianBlur(1.1 * SS)).point(lambda v: 255 if v > 24 else 0)
    rim = ImageChops.subtract(rim, alpha)
    edge = Image.new("RGBA", img.size, (30, 34, 18, 0))
    edge.putalpha(rim.point(lambda v: int(v * .55)))
    out = Image.alpha_composite(edge, img)
    scale = width / UW
    return out.resize((round(UW * scale), round(UH * scale)), Image.LANCZOS)


# =====================================================================  willow sprays
# Hand-tuned, deterministic botanical drawing: a tapered bezier twig that the
# bird perches on, plus a few hanging willow strands (柳枝 for 柳莺). Only drawn
# where the background is actually visible (title band), never around every card.

LEAF_GREENS = ((92, 120, 48), (112, 140, 60), (132, 156, 74), (150, 170, 86), (100, 128, 54))


def _bez_point(p, t):
    a, b, c, d = p
    u = 1 - t
    return (u**3 * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t**3 * d[0],
            u**3 * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t**3 * d[1])


def _bez_tangent(p, t):
    a, b, c, d = p
    u = 1 - t
    return (3 * u * u * (b[0] - a[0]) + 6 * u * t * (c[0] - b[0]) + 3 * t * t * (d[0] - c[0]),
            3 * u * u * (b[1] - a[1]) + 6 * u * t * (c[1] - b[1]) + 3 * t * t * (d[1] - c[1]))


def _tapered(draw, ctrl, w0, w1, colors, k, steps=40):
    """Filled tapered stem along a cubic bezier, with a soft highlight ridge."""
    left, right, centre = [], [], []
    for i in range(steps + 1):
        t = i / steps
        x, y = _bez_point(ctrl, t)
        dx, dy = _bez_tangent(ctrl, t)
        n = math.hypot(dx, dy) or 1
        nx, ny = -dy / n, dx / n
        w = (w0 + (w1 - w0) * t ** .8) / 2
        left.append(((x + nx * w) * k, (y + ny * w) * k))
        right.append(((x - nx * w) * k, (y - ny * w) * k))
        centre.append(((x - nx * w * .35) * k, (y - ny * w * .35) * k, w))
    dark, mid, light = colors
    draw.polygon(left + right[::-1], fill=dark)
    inner_l = [((a[0] * .55 + b[0] * .45), (a[1] * .55 + b[1] * .45)) for a, b in zip(left, right)]
    draw.line([(c[0], c[1]) for c in centre], fill=mid, width=max(1, int(w0 * .45 * k)), joint="curve")
    draw.line(inner_l[: int(steps * .85)], fill=light, width=max(1, int(w0 * .16 * k)), joint="curve")
    r = w0 / 2 * k
    sx, sy = left[0][0] * .5 + right[0][0] * .5, left[0][1] * .5 + right[0][1] * .5
    draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=dark)


@lru_cache(maxsize=96)
def _leaf(length, ratio, tone, curl, k=3):
    """One lanceolate willow leaf, pointing +x from its stalk at the origin."""
    L, W = length * k, max(2, length * ratio * k)
    pad = int(W + 6)
    im = Image.new("RGBA", (int(L + 2 * pad), int(2 * W + 2 * pad)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    oy = im.height / 2
    up, down = [], []
    n = 24
    for i in range(n + 1):
        t = i / n
        x = pad + t * L
        bend = curl * W * 1.6 * t * t
        half = W * math.sin(math.pi * min(1, t * 1.08)) ** .75 * (1 - .25 * t)
        up.append((x, oy - half + bend))
        down.append((x, oy + half * .82 + bend))
    base = LEAF_GREENS[tone % len(LEAF_GREENS)]
    shade = tuple(max(0, int(c * .78)) for c in base)
    d.polygon(up + down[::-1], fill=base + (255,))
    # lower half slightly darker -> reads as a folded, living leaf rather than a sticker
    d.polygon([(x, (y1 + y2) / 2) for (x, y1), (_, y2) in zip(up, down)] + down[::-1], fill=shade + (255,))
    d.line([(x, (y1 + y2) / 2 - W * .05) for (x, y1), (_, y2) in zip(up, down)][:n - 2],
           fill=tuple(min(255, int(c * 1.32)) for c in base) + (200,), width=max(1, k))
    d.line([(pad - 5 * k, oy), (pad + 2, oy)], fill=(84, 70, 44, 255), width=max(1, k))
    return im, (pad - 5 * k, oy)


def _place_leaf(layer, k, at, angle, length, ratio, tone, curl):
    leaf, (ax, ay) = _leaf(int(length), ratio, tone, curl, k)
    rot = leaf.rotate(-angle, resample=Image.BICUBIC, expand=True)
    # expand=True moves the stalk point; recompute where it went
    w0, h0 = leaf.size
    cx, cy = w0 / 2, h0 / 2
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    vx, vy = ax - cx, ay - cy
    rx, ry = vx * ca - vy * sa, vx * sa + vy * ca
    px = at[0] * k - (rot.width / 2 + rx)
    py = at[1] * k - (rot.height / 2 + ry)
    layer.alpha_composite(rot, (int(px), int(py))) if px >= 0 and py >= 0 else layer.paste(rot, (int(px), int(py)), rot)


def branch_geometry(W, H, hero, scale=1, title_right=None, photo_left=None):
    """Return (perch twig control points, willow strand list, perch anchors) in window px."""
    s = scale
    title_right = title_right if title_right is not None else 330 * s
    photo_left = photo_left if photo_left is not None else W * .6
    y = hero - 14 * s
    reach = min(W * .42, max(title_right + 40 * s, 330 * s))
    twig = ((-14 * s, y + 10 * s), (reach * .32, y - 30 * s), (reach * .62, y + 8 * s), (reach, y - 18 * s))
    strands = []
    gap_l, gap_r = title_right + 26 * s, photo_left - 18 * s
    if gap_r - gap_l > 60 * s:
        n = 3 if gap_r - gap_l > 190 * s else 2
        for i in range(n):
            x = gap_l + (gap_r - gap_l) * (i + .5) / n + (-9, 7, -4)[i] * s
            L = hero * (.62, .44, .54)[i]
            strands.append(((x, -6 * s), (x + 9 * s, L * .35), (x - 6 * s, L * .72), (x + 5 * s, L)))
    perches = []
    for t in (.3, .5, .7, .9):
        px, py = _bez_point(twig, t)
        w = (8.5 * s + (1.4 * s - 8.5 * s) * t ** .8) / 2
        perches.append((px, py - w + 1))
    return twig, strands, perches


@lru_cache(maxsize=6)
def _branch_layer(W, H, hero, scale, title_right, photo_left):
    k = 2
    layer = Image.new("RGBA", (W * k, (hero + int(40 * scale)) * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    s = scale
    twig, strands, _ = branch_geometry(W, H, hero, scale, title_right, photo_left)
    bark = ((52, 41, 28, 255), (86, 70, 48, 255), (150, 128, 92, 150))
    leaves = []
    # side twigs of the perch branch
    sides = []
    for t, ang, ln in ((.2, -24, 34), (.45, 32, 46), (.62, -20, 40), (.84, -52, 52), (.97, -6, 30)):
        bx, by = _bez_point(twig, t)
        a = math.radians(ang)
        ex, ey = bx + math.cos(a) * ln * s, by + math.sin(a) * ln * s
        mx, my = (bx + ex) / 2, (by + ey) / 2
        ctrl = ((bx, by), (mx - 6 * s, my - 4 * s), (mx + 4 * s, my - 2 * s), (ex, ey))
        sides.append(ctrl)
    for ctrl in strands:
        _tapered(d, ctrl, 2.2 * s, .9 * s, bark, k, 30)
    for ctrl in sides:
        _tapered(d, ctrl, 2.4 * s, .8 * s, bark, k, 18)
    _tapered(d, twig, 8.5 * s, 1.4 * s, bark, k, 50)
    # leaves: alternate sides, drooping with gravity, smaller toward the tips
    import random as _r
    rnd = _r.Random(int(W * 7 + hero))
    def sprinkle(ctrl, start, step, length, droop, hang=False):
        t, side = start, 1
        while t <= 1.0:
            x, y = _bez_point(ctrl, t)
            dx, dy = _bez_tangent(ctrl, t)
            base = math.degrees(math.atan2(dy, dx))
            if hang:
                ang = 90 + side * rnd.uniform(14, 38)
            else:
                ang = base + side * rnd.uniform(38, 62)
                ang = ang + (90 - ang) * droop          # gravity pulls leaves downward
            ln = length * rnd.uniform(.75, 1.15) * (1 - .25 * t) * s
            ratio = rnd.uniform(.1, .13) if hang else rnd.uniform(.14, .18)
            leaves.append(((x, y), ang, ln, ratio, rnd.randrange(5), rnd.uniform(-.3, .3)))
            side = -side
            t += step * rnd.uniform(.75, 1.25)
    sprinkle(twig, .3, .085, 34, .3)
    for ctrl in sides:
        sprinkle(ctrl, .3, .2, 32, .35)
        # a small fan of leaves at each twig tip: foliage grows in clusters, not evenly
        ex, ey = ctrl[3]
        dx, dy = _bez_tangent(ctrl, 1)
        base = math.degrees(math.atan2(dy, dx))
        for spread in (-34, -12, 10, 30):
            leaves.append(((ex, ey), base + spread + rnd.uniform(-6, 6), rnd.uniform(30, 42) * s,
                           rnd.uniform(.15, .19), rnd.randrange(5), rnd.uniform(-.2, .2)))
    for ctrl in strands:
        sprinkle(ctrl, .08, .055, 34, 0, hang=True)
    rnd.shuffle(leaves)
    for at, ang, ln, ratio, tone, curl in leaves:
        _place_leaf(layer, k, at, ang, ln, ratio, tone, curl)
    small = layer.resize((W, layer.height // k), Image.LANCZOS)
    # leaves that hang onto the toolbar fade out instead of being sliced by its edge
    fade = Image.new("L", small.size, 255)
    fd = ImageDraw.Draw(fade)
    top = int(hero - 6 * s)
    for y in range(top, small.height):
        fd.line([(0, y), (W, y)], fill=max(0, int(255 * (1 - (y - top) / max(1, 14 * s)))))
    small.putalpha(ImageChops.multiply(small.getchannel("A"), fade))
    # soft contact shadow so the spray sits *on* the photo instead of floating
    shadow = Image.new("RGBA", small.size, (10, 14, 4, 0))
    shadow.putalpha(small.getchannel("A").filter(ImageFilter.GaussianBlur(3 * s)).point(lambda v: int(v * .5)))
    out = Image.new("RGBA", small.size, (0, 0, 0, 0))
    out.alpha_composite(shadow, (int(2 * s), int(4 * s)))
    out.alpha_composite(small)
    return out


# =====================================================================  corner sprigs
# A few slim twigs that lie ACROSS a card corner (on Windows they are click-through
# layered child windows above the widgets, like the bird). Only on corners whose
# content is empty, and never on every card.

SPRIG_SPOTS = (("preview", "tr", 1.0), ("birds", "tr", .72), ("footer", "r", .9))


def _sprig_shape(kind, s):
    """(width, height, hx, hy, stem bezier) of a corner sprig in its own pixel space."""
    if kind == "r":                                       # horizontal spray along the footer's top-right
        W, Hh = int(230 * s), int(70 * s)
        return W, Hh, W - int(16 * s), int(26 * s), \
            ((W + 6 * s, 30 * s), (W - 70 * s, 18 * s), (W - 150 * s, 34 * s), (16 * s, 26 * s))
    W, Hh = int(170 * s), int(140 * s)                    # arching over a top-right corner
    return W, Hh, W - int(16 * s), int(40 * s), \
        ((W + 4 * s, 108 * s), (W - 10 * s, 44 * s), (W - 70 * s, 24 * s), (14 * s, 46 * s))


SPRIG_PERCH_T = {"tr": (.55, .72, .88), "r": (.3, .55, .8)}


def sprig_perches(rects, W, scale):
    """Window points on top of the corner sprigs where the bird may land."""
    points = []
    for name, kind, size in SPRIG_SPOTS:
        box = rects.get(name)
        if not box or box[2] - box[0] < 220 * scale:
            continue
        s = round(scale * size, 3)
        _, _, hx, hy, ctrl = _sprig_shape(kind, s)
        ox, oy = box[2] - hx, box[1] - hy
        for t in SPRIG_PERCH_T[kind]:
            x, y = _bez_point(ctrl, t)
            w = (4.4 * s + (1.1 * s - 4.4 * s) * t) / 2
            if 0 <= ox + x <= W:
                points.append((ox + x, oy + y - w + 1))
    return points


@lru_cache(maxsize=12)
def sprig_image(kind, scale):
    """Return (RGBA image, (hx, hy)) where (hx, hy) is the pixel that sits on the card corner."""
    import random as _r
    s, k = scale, 2
    W, Hh, hx, hy, ctrl = _sprig_shape(kind, s)
    layer = Image.new("RGBA", (W * k, Hh * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    bark = ((58, 46, 30, 255), (94, 78, 54, 255), (162, 140, 104, 150))
    _tapered(d, ctrl, 4.4 * s, 1.1 * s, bark, k, 40)
    # one side twig
    bx, by = _bez_point(ctrl, .45)
    side = ((bx, by), (bx - 14 * s, by + 4 * s), (bx - 26 * s, by + 14 * s), (bx - 34 * s, by + 26 * s))
    _tapered(d, side, 2.2 * s, .8 * s, bark, k, 16)
    rnd = _r.Random(hash(kind) & 0xffff)
    leaves = []
    t, flip = .18, 1
    while t < .97:
        x, y = _bez_point(ctrl, t)
        dx, dy = _bez_tangent(ctrl, t)
        base = math.degrees(math.atan2(dy, dx))
        ang = base + flip * rnd.uniform(36, 58)
        ang = ang + (90 - ang) * .35 if flip > 0 else ang          # lower leaves droop a bit
        leaves.append(((x, y), ang, rnd.uniform(26, 34) * s * (1 - .3 * t), rnd.uniform(.16, .2),
                       rnd.randrange(5), rnd.uniform(-.3, .3)))
        flip = -flip
        t += rnd.uniform(.12, .17)
    ex, ey = side[3]
    for spread in (-20, 8, 30):
        leaves.append(((ex, ey), 120 + spread, rnd.uniform(18, 24) * s, .18, rnd.randrange(5), .1))
    tip = ctrl[3]
    for spread in (-14, 16):
        leaves.append((tip, 180 + spread, rnd.uniform(16, 20) * s, .19, rnd.randrange(5), 0))
    for at, ang, ln, ratio, tone, curl in leaves:
        _place_leaf(layer, k, at, ang, ln, ratio, tone, curl)
    for t in (.3, .62):
        x, y = _bez_point(ctrl, t)
        r = 2.1 * s * k
        d.ellipse((x * k - r, y * k - r, x * k + r, y * k + r), fill=(182, 146, 74, 235))
    small = layer.resize((W, Hh), Image.LANCZOS)
    shadow = Image.new("RGBA", small.size, (12, 16, 6, 0))
    shadow.putalpha(small.getchannel("A").filter(ImageFilter.GaussianBlur(2.2 * s)).point(lambda v: int(v * .45)))
    out = Image.new("RGBA", small.size, (0, 0, 0, 0))
    out.alpha_composite(shadow, (int(1 * s), int(3 * s)))
    out.alpha_composite(small)
    return out, (hx, hy)


def sprig_placements(rects, W, scale):
    """[(image, x, y)] window positions for the corner sprigs (clipped to the window)."""
    out = []
    for name, kind, size in SPRIG_SPOTS:
        box = rects.get(name)
        if not box or box[2] - box[0] < 220 * scale:
            continue
        image, (hx, hy) = sprig_image(kind, round(scale * size, 3))
        x, y = box[2] - hx, box[1] - hy
        if x + image.width > W:
            image = image.crop((0, 0, max(1, int(W - x)), image.height))
        out.append((image, int(x), int(y)))
    return out


class SprigOverlay:
    """Click-through layered child windows that hold the corner sprigs (Windows only)."""

    def __init__(self, root):
        self.root, self.windows, self.key = root, [], None

    def place(self, rects, scale):
        W = self.root.winfo_width()
        key = (W, self.root.winfo_height(), tuple(sorted((k, tuple(v)) for k, v in rects.items()
                                                       if not k.startswith("_"))))
        if key == self.key:
            return
        self.key = key
        items = sprig_placements(rects, W, scale)
        while len(self.windows) > len(items):
            self.windows.pop().close()
        for i, (image, x, y) in enumerate(items):
            if i < len(self.windows) and (self.windows[i].width, self.windows[i].height) != image.size:
                self.windows[i].close()
                self.windows[i] = _LayeredBird(self.root, image.size)
            elif i >= len(self.windows):
                self.windows.append(_LayeredBird(self.root, image.size))
            self.windows[i].show(image, x, y)

    def hide(self):
        if self.key is None:
            return
        for window in self.windows:
            window.hide()
        self.key = None

    def close(self):
        for window in self.windows:
            window.close()
        self.windows = []


def paint_branches(image, rects, scale=1, title_right=None, photo_left=None):
    """A perch twig + willow strands in the title band (corner sprigs live in SprigOverlay)."""
    hero = rects.get("_hero") if isinstance(rects, dict) else None
    if not hero:
        return
    W, H = image.size
    layer = _branch_layer(W, H, int(hero), round(scale, 3), None if title_right is None else int(title_right),
                          None if photo_left is None else int(photo_left))
    image.alpha_composite(layer, (0, 0))


def bird_sprite(width=64, phase=-1, right=False):
    """Backwards-compatible helper: phase < 0 → perched, else a flap frame."""
    return frame("perch" if phase < 0 else "flap", max(0, phase), width, right)


class _LayeredBird:
    """Windows child sprite, per-pixel alpha and mouse passthrough."""
    def __init__(self, root, size):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w, self.width, self.height = c, w, *size
        self._last_image = None
        self.user = c.WinDLL("user32", use_last_error=True)
        self.gdi = c.WinDLL("gdi32", use_last_error=True)
        self.user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
            c.c_int, c.c_int, c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
        self.user.CreateWindowExW.restype = w.HWND
        self.user.DestroyWindow.argtypes = [w.HWND]
        self.user.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
        self.user.ShowWindow.argtypes = [w.HWND, c.c_int]
        self.gdi.CreateCompatibleDC.argtypes = [w.HDC]
        self.gdi.CreateCompatibleDC.restype = w.HDC
        self.gdi.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
        self.gdi.SelectObject.restype = w.HGDIOBJ
        self.gdi.DeleteDC.argtypes = [w.HDC]
        self.gdi.DeleteObject.argtypes = [w.HGDIOBJ]
        class Header(c.Structure):
            _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                ("planes", w.WORD), ("bits", w.WORD), ("compression", w.DWORD),
                ("bytes", w.DWORD), ("x", w.LONG), ("y", w.LONG), ("used", w.DWORD), ("important", w.DWORD)]
        class Blend(c.Structure):
            _fields_ = [("operation", c.c_ubyte), ("flags", c.c_ubyte),
                        ("alpha", c.c_ubyte), ("format", c.c_ubyte)]
        self.blend = Blend(0, 0, 255, 1)
        self.origin, self.size = w.POINT(0, 0), w.SIZE(*size)
        self.user.UpdateLayeredWindow.argtypes = [w.HWND, w.HDC, c.POINTER(w.POINT),
            c.POINTER(w.SIZE), w.HDC, c.POINTER(w.POINT), w.DWORD, c.POINTER(Blend), w.DWORD]
        self.user.UpdateLayeredWindow.restype = w.BOOL
        self.gdi.CreateDIBSection.argtypes = [w.HDC, c.POINTER(Header), w.UINT,
                                            c.POINTER(c.c_void_p), w.HANDLE, w.DWORD]
        self.gdi.CreateDIBSection.restype = w.HBITMAP
        self.dc = self.gdi.CreateCompatibleDC(None)
        header = Header(c.sizeof(Header), size[0], -size[1], 1, 32, 0, size[0] * size[1] * 4, 0, 0, 0, 0)
        self.bits = c.c_void_p()
        self.bitmap = self.gdi.CreateDIBSection(self.dc, c.byref(header), 0, c.byref(self.bits), None, 0)
        if not self.bitmap:
            self.gdi.DeleteDC(self.dc)
            raise c.WinError(c.get_last_error())
        self.old_bitmap = self.gdi.SelectObject(self.dc, self.bitmap)
        # WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE; WS_CHILD.
        self.hwnd = self.user.CreateWindowExW(0x08080020, "Static", "", 0x40000000,
            0, 0, *size, root.winfo_id(), None, None, None)
        if not self.hwnd:
            self.close()
            raise c.WinError(c.get_last_error())

    def show(self, image, x, y):
        # Frame/branch images are immutable. Windows retains the uploaded bitmap
        # while the child moves, including when it is hidden and shown again.
        if image is not self._last_image:
            data = image.convert("RGBa").tobytes("raw", "BGRa")
            self.c.memmove(self.bits, data, len(data))
            if not self.user.UpdateLayeredWindow(self.hwnd, None, None, self.c.byref(self.size), self.dc,
                    self.c.byref(self.origin), 0, self.c.byref(self.blend), 2):
                raise self.c.WinError(self.c.get_last_error())
            self._last_image = image
        self.user.SetWindowPos(self.hwnd, None, int(x), int(y), self.width, self.height, 0x50)

    def hide(self):
        self.user.ShowWindow(self.hwnd, 0)

    def close(self):
        if getattr(self, "hwnd", None):
            self.user.DestroyWindow(self.hwnd)
            self.hwnd = None
        if getattr(self, "dc", None):
            self.gdi.SelectObject(self.dc, self.old_bitmap)
            self.gdi.DeleteObject(self.bitmap)
            self.gdi.DeleteDC(self.dc)
            self.dc = None



class BirdScene:
    """A restless leaf warbler: hops, flicks its tail, turns, flits between perches.

    Motion uses eased cubic paths plus the bounding flight of small passerines
    (short flap bursts, then wings tucked) instead of a constant-speed glide.
    """

    TICK_FLY, TICK_REST = 20, 70
    _pointer_sample = None
    _alert = False
    _noticed_pointer = False

    def __init__(self, app):
        self.app, self.root, self.canvas = app, app.window, app.bg
        self.width = max(64, app._px(100))
        self.k = self.width / UW
        self.height = round(UH * self.k)
        self.sprigs = SprigOverlay(self.root) if os.name == "nt" else None
        self.native = _LayeredBird(self.root, (self.width, self.height)) if os.name == "nt" else None
        self.item = None if self.native else self.canvas.create_image(0, 0, anchor="nw", tags="mascot")
        self.photo = None
        self.right = False
        home = self.perches()
        self.position = home[1] if len(home) > 1 else (app._px(183), app._px(5))
        self.destination = self.position
        self.path = None
        self.until = time.monotonic() + random.uniform(3, 6)
        self.state = "perched"
        self.pose_until = 0.
        self.pose = "perch"
        self.next_fidget = time.monotonic() + random.uniform(.6, 1.6)
        self.hop = None
        self.after_id = None
        self.closed = False
        self.dialog_anchors = None
        self._dialog_attention_motion = None
        self.suspended = False
        self.hop_count = 0
        self.flee_count = self.flight_count = 0
        self._last_frame = None
        import threading
        threading.Thread(target=prewarm, args=(self.width,), name="warbler-frames", daemon=True).start()
        self.after_id = self.root.after(80, self.tick)

    # ---------------------------------------------------------------- geometry
    def _anchor_to_topleft(self, x, y):
        ax = (UW - ANCHOR[0]) * self.k if self.right else ANCHOR[0] * self.k
        return (x - ax, y - ANCHOR[1] * self.k)

    def perches(self):
        if getattr(self, 'dialog_anchors', None):
            return [self._anchor_to_topleft(x, y) for x, y in self.dialog_anchors]
        rects = getattr(self.app, "rects", None) or {}
        W = max(1, self.root.winfo_width())
        hero = rects.get("_hero")
        points = []
        if hero:
            args = getattr(self.app, "branch_args", {}) or {}
            _, _, anchors = branch_geometry(W, max(1, self.root.winfo_height()), hero, self.app.s,
                                            args.get("title_right"), args.get("photo_left"))
            points += anchors
            if self.sprigs is not None or getattr(self, "force_sprig_perches", False):
                points += sprig_perches(rects, W, self.app.s)     # fly anywhere: twigs on the cards
            tb = rects.get("toolbar")
            photo_left = args.get("photo_left") or W * .6
            if tb:
                x = W * .45
                if x < photo_left - self.app._px(50):
                    points.append((x, tb[1] + self.app._px(2)))
        if not points:
            points = [(self.app._px(220), self.app._px(60))]
        result = []
        for x, y in points:
            tx, ty = self._anchor_to_topleft(x, y)
            result.append((max(2, min(tx, W - self.width - 2)), max(0, ty)))
        return result

    # ---------------------------------------------------------------- behaviour
    def dialog_attention(self, duration=1.2):
        """Request three visible hops on the dialog, using the existing bird tick.

        A bird already in flight finishes that flight first. Repeated clicks do
        not create another timer or restart an unfinished hopping sequence.
        """
        if self.closed or self.suspended or not self.dialog_anchors:
            return False
        if self._dialog_attention_motion is not None:
            return True
        duration = max(.6, min(2., float(duration)))
        self._dialog_attention_motion = {"duration": duration, "started": None,
                                         "anchor": None, "hop_index": -1}
        self.hop = None
        perches = self.perches()
        if not self.path and perches and min(math.dist(p, self.position) for p in perches) > self.app._px(45):
            self.take_off(now=time.monotonic())
        return True

    def cancel_dialog_attention(self):
        """End a dialog cue without disturbing unrelated ordinary bird motion."""
        if getattr(self, "_dialog_attention_motion", None) is not None:
            self._dialog_attention_motion = None
            self.hop = None
            self.pose, self.pose_until = "perch", 0.

    def _step_dialog_attention(self, now):
        motion = getattr(self, "_dialog_attention_motion", None)
        if motion is None:
            return False
        if not self.dialog_anchors or self.suspended:
            self.cancel_dialog_attention()
            return False
        if self.path:
            return False
        perches = self.perches()
        if not perches:
            self.cancel_dialog_attention()
            return False
        if motion["started"] is None:
            motion["started"] = now
            motion["anchor"] = min(range(len(perches)), key=lambda i: math.dist(perches[i], self.position))
        elapsed = now - motion["started"]
        if elapsed >= motion["duration"]:
            self.cancel_dialog_attention()
            self.until = max(self.until, now + 1.)
            self.next_fidget = now + .65
            return False
        # Anchors may sway with the branches. Track the same perch, not a new
        # nearest one each frame, so the feet follow the twig between hops.
        x, y = perches[min(motion["anchor"], len(perches) - 1)]
        self.position = (max(0, min(x, self.root.winfo_width() - self.width)),
                         max(0, min(y, self.root.winfo_height() - self.height)))
        self.destination = self.position
        self.state = "perched"
        period = motion["duration"] / 3.
        index = min(2, int(elapsed / period))
        if index != motion["hop_index"]:
            motion["hop_index"] = index
            began = motion["started"] + index * period
            self.hop = (began, period * .78, self.app._px(15))
            self.pose, self.pose_until = "crouch", began + .055
            self.hop_count += 1
        if self.hop and now >= self.hop[0] + self.hop[1]:
            self.hop = None
        return True

    def _watch_pointer(self, now, pointer):
        """Briefly look ahead in the cursor's direction, with separate enter/leave radii."""
        if pointer is None:
            self._alert, self._pointer_sample = False, None
            self._noticed_pointer = False
            return None
        x, y = pointer
        vx = vy = 0.
        if self._pointer_sample:
            then, px, py, old_vx, old_vy = self._pointer_sample
            dt = now - then
            if 0 < dt < .2:
                blend = -math.expm1(-dt / .09)
                vx = old_vx + blend * ((x-px)/dt - old_vx)
                vy = old_vy + blend * ((y-py)/dt - old_vy)
        self._pointer_sample = now, x, y, vx, vy
        centre = (self.position[0] + self.width / 2, self.position[1] + self.height * .6)
        distance = math.dist(centre, pointer)
        if distance > self.app._px(160):
            self._noticed_pointer = False
        self._alert = distance < self.app._px(115 if self._alert else 72)
        if not self._alert:
            if (not self.path and not self.hop and not self.dialog_anchors and
                    distance < self.app._px(138) and not self._noticed_pointer):
                self.right = x > centre[0]
                self.pose, self.pose_until = "look", now + .32
                self.next_fidget = now + random.uniform(.65, 1.3)
                self._noticed_pointer = True
            return None
        lead = min(.16, self.app._px(74) / max(1., math.hypot(vx, vy)))
        return x + vx * lead, y + vy * lead

    def take_off(self, pointer=None, now=None, velocity=None):
        now = time.monotonic() if now is None else now
        candidates = [p for p in self.perches() if math.dist(p, self.position) > self.app._px(60)]
        if not candidates:
            return
        if pointer is not None:
            if velocity is None and self._pointer_sample:
                # An approaching cursor must not push the bird towards the cursor
                # just because the longest available branch is on that side.
                px, py = self._pointer_sample[1:3]
                ax = self.position[0] + self.width / 2 - px
                ay = self.position[1] + self.height * .6 - py
                if math.hypot(ax, ay) > self.app._px(10):
                    outward = [p for p in candidates
                               if (p[0]-self.position[0])*ax + (p[1]-self.position[1])*ay >= 0]
                    candidates = outward or candidates
            def escape_score(p):
                away = math.dist((p[0] + self.width / 2, p[1] + self.height * .6), pointer)
                dx, dy = p[0] - self.position[0], p[1] - self.position[1]
                heading = 0.
                if velocity:
                    heading = (dx*velocity[0] + dy*velocity[1]) / max(1., math.hypot(dx,dy)*math.hypot(*velocity))
                return away + self.app._px(185)*heading + random.uniform(0, self.app._px(110))
            if velocity:
                alternatives = [p for p in candidates if math.dist(p, self.destination) > self.app._px(80)]
                candidates = alternatives or candidates
            target = max(candidates, key=escape_score)
            if velocity is None:
                self.flee_count += 1
        else:
            target = random.choice(candidates)
        start = self.position
        distance = math.dist(start, target)
        speed = random.uniform(450, 545) if pointer is not None else random.uniform(345, 420)
        duration = max(.52, min(2.6, distance / self.app._px(speed)))
        lift = min(self.app._px(110), distance * .3) + self.app._px(14)
        # long flights over the panels: gently arched, never above the window
        c1 = (start[0] + (target[0] - start[0]) * .25, max(2, start[1] + (target[1]-start[1])*.18-lift))
        if velocity is not None:
            # The cubic's initial derivative equals the incoming velocity.
            # Shorten the handle along that tangent only if it hits the window edge.
            room = (max(0, self.root.winfo_width()-self.width), max(0, self.root.winfo_height()-self.height))
            handle = duration / 3
            for pos, speed_on_axis, limit in zip(start, velocity, room):
                if speed_on_axis > 0:
                    handle = min(handle, (limit-pos)/speed_on_axis)
                elif speed_on_axis < 0:
                    handle = min(handle, -pos/speed_on_axis)
            c1 = tuple(pos + max(0., handle)*v for pos, v in zip(start, velocity))
        c2 = (start[0] + (target[0] - start[0]) * .75, max(2, target[1] - lift * random.uniform(.55, .9)))
        delay = 0. if pointer is not None else .09
        self.path = (now + delay, duration, start, c1, c2, target)
        self.destination = target
        if velocity is None:
            self.right = target[0] > start[0]
            self._wing_start = now + delay
            self._beat_hz = random.uniform(5.3, 6.4)
        self._bank_at = random.uniform(.54, .67)
        self.state = "takeoff" if delay else "flying"
        self.hop = None
        self.flight_count += 1

    def _sample_flight(self, now):
        began, duration, *points = self.path
        u = min(1., max(0., (now-began)/duration))
        # Depart with momentum, slow down only on the final approach.
        t = u + u*u*(1-u)
        rate = (1 + 2*u - 3*u*u) / duration
        x, y = _bez_point(points, t)
        dx, dy = _bez_tangent(points, t)
        return u, (x, y), (dx * rate, dy * rate)

    def _fidget(self, now):
        if self.dialog_anchors:
            self.hop = (now, .34, self.app._px(random.uniform(9, 15)))
            self.pose, self.pose_until = 'crouch', now + .07
            self.right = not self.right if random.random() < .3 else self.right
            self.hop_count += 1
            self.next_fidget = now + random.uniform(.65, 1.35)
            return
        roll = random.random()
        if roll < .3:
            self.pose, self.pose_until = "flick", now + .16
        elif roll < .55:
            self.right = not self.right
            self.pose, self.pose_until = "crouch", now + .08
        elif roll < .78:
            self.hop = (now, .26, self.app._px(random.uniform(5, 9)))
            self.pose, self.pose_until = "crouch", now + .06
        elif roll < .90:
            self.pose, self.pose_until = "blink", now + .11
        else:
            self.pose, self.pose_until = "crouch", now + .18      # a quick peck / look down
        self.next_fidget = now + random.uniform(.45, 1.7)

    def step(self, now, pointer=None):
        if self._step_dialog_attention(now):
            return
        threat = self._watch_pointer(now, pointer)
        if threat is not None and not self.path:
            self.take_off(threat, now)
        if self.path:
            if now < self.path[0]:
                self.state = "takeoff"
                return
            self.state = "flying"
            progress, self.position, self._velocity = self._sample_flight(now)
            if abs(self._velocity[0]) > self.app._px(35):
                self.right = self._velocity[0] > 0
            if (threat is not None and self._bank_at <= progress < .97 and
                    not self.dialog_anchors):
                self.take_off(threat, now, self._velocity)
            elif progress >= 1:
                self.position = self.path[-1]
                self.path = None
                self.state = "perched"
                self.pose, self.pose_until = "crouch", now + .14
                self.until = now + random.uniform(3.5, 8.)
                self.next_fidget = now + random.uniform(.5, 1.2)
        else:
            self.state = "perched"
            if self.hop:
                began, duration, height = self.hop
                if now >= began + duration:
                    self.hop = None
            if now > self.until and not getattr(self.app, "busy", False):
                self.take_off(now=now)
            elif now > self.next_fidget and now > self.pose_until:
                self._fidget(now)
        x, y = self.position
        self.position = (max(0, min(x, self.root.winfo_width() - self.width)),
                         max(0, min(y, self.root.winfo_height() - self.height)))

    def _current_frame(self, now):
        if self.state == "takeoff":
            return ("crouch", 0, 0)
        if self.state == "flying" and self.path:
            began, duration = self.path[:2]
            raw = min(1., max(0., (now - began) / duration))
            if raw > .86:
                return ("brake", 0, 0)
            wing = (now - self._wing_start) * self._beat_hz
            vx, vy = self._velocity
            climb = math.degrees(math.atan2(-vy, abs(vx) + 1e-3))
            tilt = -max(-16, min(16, climb * .55))
            tilt = int(round(tilt / 4) * 4)
            if wing % 3.6 < 3:
                return ("flap", int(wing * 8) % 8, tilt)
            return ("glide", 0, tilt)
        if now < self.pose_until:
            if self.pose == "look":
                return ("perch", 0, -6)
            return (self.pose, 0, 0)
        return ("perch", 0, 0)

    def tick(self):
        started = time.monotonic()
        self.after_id = None
        if self.closed or self.app.closing:
            return
        try:
            if self.root.winfo_viewable() and not self.suspended:
                if self.sprigs is not None and getattr(self.app, "rects", None):
                    if self.dialog_anchors:
                        self.sprigs.hide()
                    else:
                        self.sprigs.place(self.app.rects, self.app.s)
                pointer = (self.root.winfo_pointerx() - self.root.winfo_rootx(),
                           self.root.winfo_pointery() - self.root.winfo_rooty())
                now = time.monotonic()
                self.step(now, pointer)
                kind, phase, tilt = self._current_frame(now)
                x, y = self.position
                if self.hop:
                    began, duration, height = self.hop
                    u = min(1., (now - began) / duration)
                    y -= math.sin(math.pi * u) * height
                key = (kind, phase, tilt, self.right, int(x), int(y))
                if key != self._last_frame:
                    self._last_frame = key
                    image = frame(kind, phase, self.width, self.right, tilt)
                    if self.native:
                        self.native.show(image, x, y)
                    else:
                        from PIL import ImageTk
                        self.photo = ImageTk.PhotoImage(image, master=self.root)
                        self.canvas.itemconfigure(self.item, image=self.photo)
                        self.canvas.coords(self.item, x, y)
                        self.canvas.tag_raise(self.item)
            elif self.native:
                self.native.hide()
                self._last_frame = None
                if self.sprigs is not None:
                    self.sprigs.hide()
        except Exception as exc:
            self.app.logger.warning("小鸟动画暂停：%s", exc)
            self.close()
            return
        busy = self.state in ("flying", "takeoff") or self.hop is not None
        interval = 350 if self.suspended else (self.TICK_FLY if busy else self.TICK_REST)
        self.after_id = self.root.after(max(1, round(interval - (time.monotonic()-started)*1000)), self.tick)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel_dialog_attention()
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None
        if self.sprigs is not None:
            self.sprigs.close()
        if self.native:
            self.native.close()
        elif self.item:
            self.canvas.delete(self.item)
