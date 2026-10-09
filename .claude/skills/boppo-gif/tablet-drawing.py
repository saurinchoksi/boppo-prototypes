"""The tablet drawing every GIF generator shares: an illustrated Boppo, seen from the front at an
angle, from a small 3D model with one camera, so the perspective is consistent. Not run on its
own: each generator exec()s it, then draws with frame(), add_light() and all_lights()."""
from PIL import Image, ImageDraw
import math, pathlib
import numpy as np

W, H = 720, 330
FPS = 10                                          # a GIF keeps 100 ms a frame exact; at 15 it played ~10% fast (60 ms a frame)
BG = (247, 244, 238)
DECK = (241, 237, 228)
DECK_LIP = (222, 217, 205)
BAND = (170, 46, 142)
BAND_DARK = (132, 32, 110)
BTN = (238, 240, 238)
BTN_SIDE = (204, 208, 206)
BTN_PRESSED = (222, 224, 222)
GREEN = (70, 225, 110)
BLUE = (110, 120, 255)
INK = (35, 35, 35)

# --- the model, in millimetres, origin at the centre of the top surface ---------------
LEN, DEP, THICK, CORNER = 260, 128, 22, 28      # body
BTN_R, BTN_H = 20, 16                            # buttons
COLS, ROWS = 5, 2
PITCH_X, PITCH_Y = 50, 54
def btn_center(col, row):
    return ((col - 2) * PITCH_X, (row - 0.5) * PITCH_Y)

# --- camera: in front of the tablet, above it, looking down at it ----------------------
TILT = math.radians(50)
DIST = 760
FOCAL = 1560
CENTER = (W / 2, 150)

def project(x, y, z):
    yc = y * math.cos(TILT) + z * math.sin(TILT)
    zc = -y * math.sin(TILT) + z * math.cos(TILT)
    s = FOCAL / (DIST - yc)
    return (CENTER[0] + x * s, CENTER[1] - zc * s)

def rounded_rect_ring(len_, dep, r, z, n=14):
    pts = []
    cx, cy = len_ / 2 - r, dep / 2 - r
    for (sx, sy, a0) in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append(project(sx * cx + r * math.cos(a), sy * cy + r * math.sin(a), z))
    return pts

def circle_ring(cx, cy, r, z, n=40):
    return [project(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n)]

def hull(points):
    pts = sorted(set(points))
    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and (h[-1][0]-h[-2][0])*(p[1]-h[-2][1]) - (h[-1][1]-h[-2][1])*(p[0]-h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h[:-1]
    return half(pts) + half(pts[::-1])

def mix(a, b, s):
    return tuple(int(a[i] * (1 - s) + b[i] * s) for i in range(3))

# --- the front band, measured off a photo as fractions of the length -------------------
GRILLE = (0.10, 0.31)
POWER, VOLUME, HOME, JACK, USB = 0.37, (0.41, 0.48), (0.53, 0.60), 0.75, 0.83
BAND_MID = -THICK / 2
BTN_RAISED = (186, 62, 158)

def fx(frac):
    return -LEN / 2 + frac * LEN

def face_pts(pts_xz):
    return [project(x, DEP / 2 + 0.5, z) for x, z in pts_xz]

def face_circle(cx, cz, r, n=24):
    return face_pts([(cx + r * math.cos(2 * math.pi * i / n), cz + r * math.sin(2 * math.pi * i / n)) for i in range(n)])

def face_pill(x0, x1, cz, h, n=10):
    r = h / 2
    pts = []
    for i in range(n + 1):
        a = math.pi / 2 + math.pi * i / n
        pts.append((x0 + r + r * math.cos(a), cz + r * math.sin(a)))
    for i in range(n + 1):
        a = -math.pi / 2 + math.pi * i / n
        pts.append((x1 - r + r * math.cos(a), cz + r * math.sin(a)))
    return face_pts(pts)

def draw_band_details(d):
    x0, x1 = fx(GRILLE[0]), fx(GRILLE[1])
    cols = int((x1 - x0) / 4.6)
    for j in range(4):
        for i in range(cols):
            x = x0 + i * 4.6 + (2.3 if j % 2 else 0)
            z = BAND_MID + 5.5 - j * 3.7
            px, py = project(x, DEP / 2 + 0.5, z)
            d.ellipse((px - 1.6, py - 1.6, px + 1.6, py + 1.6), fill=BAND_DARK)
    d.polygon(face_circle(fx(POWER), BAND_MID, 4.2), fill=BTN_RAISED, outline=BAND_DARK)
    d.polygon(face_circle(fx(POWER), BAND_MID, 1.8), fill=BTN_RAISED, outline=BAND_DARK)
    d.polygon(face_pill(fx(VOLUME[0]), fx(VOLUME[1]), BAND_MID, 7.5), fill=BTN_RAISED, outline=BAND_DARK)
    d.polygon(face_pill(fx(HOME[0]), fx(HOME[1]), BAND_MID, 7.5), fill=BTN_RAISED, outline=BAND_DARK)
    d.polygon(face_circle(fx(JACK), BAND_MID, 2.6), fill=(40, 20, 36))
    d.polygon(face_pill(fx(USB) - 4.5, fx(USB) + 4.5, BAND_MID, 3.6), fill=(40, 20, 36))

def draw_scene(d, lights, presses):
    d.polygon(rounded_rect_ring(LEN + 14, DEP + 14, CORNER + 6, -THICK - 4), fill=(226, 221, 211))
    d.polygon(rounded_rect_ring(LEN, DEP, CORNER, -THICK), fill=BAND_DARK)
    d.polygon(hull(rounded_rect_ring(LEN, DEP, CORNER, -THICK + 4) + rounded_rect_ring(LEN, DEP, CORNER, -2)), fill=BAND)
    d.polygon(rounded_rect_ring(LEN, DEP, CORNER, -2), fill=DECK_LIP)
    d.polygon(rounded_rect_ring(LEN, DEP, CORNER, 0), fill=DECK)
    draw_band_details(d)
    for row in range(ROWS):
        for col in range(COLS):
            cx, cy = btn_center(col, row)
            lit = lights.get((row, col), {})
            press = presses.get((row, col), 0)
            h = BTN_H * (1 - 0.6 * press)
            base_top = BTN_PRESSED if press else BTN
            base, cap = circle_ring(cx, cy, BTN_R, 0), circle_ring(cx, cy, BTN_R, h)
            tint = sum(st for _, st in lit.values()) / 4 if lit else 0
            side = BTN_SIDE
            if lit:
                side = mix(BTN_SIDE, blend_color(lit), min(1.0, tint * 0.9) * 0.6)
            d.polygon(hull(base + cap), fill=side)
            d.polygon(cap, fill=base_top, outline=mix(side, INK, 0.12))
            if lit:
                shade_cap(d._image, cap, lit, base_top)

def blend_color(lit):
    tot = sum(st for _, st in lit.values()) or 1
    return tuple(int(sum(c[i] * st for c, st in lit.values()) / tot) for i in range(3))

def shade_cap(im, cap, lit, base):
    """Light the cap per pixel. Each button has four lights, top, left, right, bottom,
    under a milky cap, so each light is brightest on its own side and fades across."""
    xs = [p[0] for p in cap]; ys = [p[1] for p in cap]
    x0, x1, y0, y1 = int(min(xs)), int(max(xs)) + 1, int(min(ys)), int(max(ys)) + 1
    w, hh = x1 - x0, y1 - y0
    if w <= 0 or hh <= 0: return
    mask = Image.new("L", (w, hh), 0)
    ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in cap], fill=255)
    m = np.array(mask) > 0
    u = (np.arange(w)[None, :] - w / 2) / (w / 2)          # -1 left .. 1 right
    v = (np.arange(hh)[:, None] - hh / 2) / (hh / 2)        # -1 top (far) .. 1 bottom (near)
    out = np.zeros((hh, w, 3)) + np.array(base, dtype=float)
    fall = {"left": np.clip(0.75 - u, 0, 1.5) / 1.5, "right": np.clip(0.75 + u, 0, 1.5) / 1.5,
            "top": np.clip(0.75 - v, 0, 1.5) / 1.5, "bottom": np.clip(0.75 + v, 0, 1.5) / 1.5}
    for side, (color, st) in lit.items():
        wgt = np.clip(fall[side] * st * 1.15, 0, 1)[..., None] * 0.9
        out = out * (1 - wgt) + np.array(color, dtype=float) * wgt
    patch = np.array(im.crop((x0, y0, x1, y1))).astype(float)
    patch[m] = out[m]
    im.paste(Image.fromarray(patch.astype(np.uint8)), (x0, y0))

def frame(lights=None, presses=None):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im); d._image = im
    draw_scene(d, lights or {}, presses or {})
    return im

# --- building blocks ---------------------------------------------------------------------
LIGHT_DIRS = ("top", "left", "right", "bottom")

def add_light(lights, key, side, color, st):
    if st <= 0.02: return
    lit = lights.setdefault(key, {})
    if side in lit and lit[side][1] >= st: return
    lit[side] = (color, st)

def all_lights(lights, key, color, st):
    for side in LIGHT_DIRS: add_light(lights, key, side, color, st)
