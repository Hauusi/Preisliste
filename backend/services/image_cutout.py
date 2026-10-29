"""Produktbilder freistellen: einfarbigen Hintergrund (z. B. weißes Studiofoto) entfernen, als PNG mit Transparenz.

Ohne KI und ohne Netzwerk: Hintergrund ist die Farbe am Bildrand; entfernt wird nur, was zusammenhängend vom Rand aus
diese Farbe hat. Helle Flächen im Produkt, die nicht an den Rand stoßen, bleiben also erhalten. Hat der Rand keine
einheitliche Farbe (Foto mit echtem Hintergrund) oder ist das Bild schon transparent, bleibt es unverändert.
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageDraw, ImageOps

MAX_PIXELS = 40_000_000  # Schutz gegen „Dekompressionsbomben“
MAX_SIDE = 2400  # größere Produktbilder werden verkleinert (Druck A4 braucht nicht mehr)
WORK_SIDE = 500  # Auflösung für die Suche nach dem zusammenhängenden Hintergrund
TOLERANCE = 18  # max. Abweichung je Farbkanal, die noch als Hintergrund gilt (JPEG-Rauschen)
SOFT = 40  # weicher Übergang an den Kanten (Kantenglättung)
UNIFORM_BORDER = 0.8  # Anteil der Randpixel in Hintergrundfarbe, ab dem freigestellt wird
PADDING = 4  # Rand in Pixeln nach dem Zuschneiden


class NotAnImage(ValueError):
    pass


def open_image(data: bytes) -> Image.Image:
    """Bild öffnen und vollständig laden (prüft den Inhalt), Drehung aus EXIF übernehmen, erstes Einzelbild."""
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        im = Image.open(io.BytesIO(data))
        im.seek(0)
        im.load()
        return ImageOps.exif_transpose(im)
    except (OSError, ValueError, Image.DecompressionBombError, SyntaxError) as e:
        raise NotAnImage(str(e)) from e


def _channel_max(diff: Image.Image) -> Image.Image:
    r, g, b = diff.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b)


def _border_color(rgb: Image.Image) -> tuple[int, int, int] | None:
    """Häufigste Randfarbe (Median), nur wenn der Rand überwiegend diese Farbe hat."""
    w, h = rgb.size
    px = rgb.load()
    border = ([px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)]
              + [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)])
    color = tuple(sorted(p[i] for p in border)[len(border) // 2] for i in range(3))
    close = sum(1 for p in border if max(abs(p[i] - color[i]) for i in range(3)) <= TOLERANCE)
    return color if close >= UNIFORM_BORDER * len(border) else None


def _background_region(distance: Image.Image) -> Image.Image | None:
    """Maske (255 = Hintergrund) der vom Rand aus zusammenhängenden Fläche in Hintergrundfarbe, verkleinert berechnet."""
    small = distance.copy()
    small.thumbnail((WORK_SIDE, WORK_SIDE), Image.Resampling.BILINEAR)
    marks = small.point(lambda v: 0 if v <= TOLERANCE else 255)
    w, h = marks.size
    px = marks.load()
    edge = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + \
           [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    for xy in edge:
        if px[xy] == 0:
            ImageDraw.floodfill(marks, xy, 100)
    region = marks.point(lambda v: 255 if v == 100 else 0)
    share = sum(region.histogram()[255:]) / (w * h)
    if share < 0.02 or share > 0.97:
        return None  # kaum Hintergrund oder fast alles: lieber nichts verändern
    # hochrechnen, leicht ausgedehnt, damit die Kante vollständig im weichen Übergang liegt
    return region.resize(distance.size, Image.Resampling.BILINEAR).point(lambda v: 255 if v else 0)


def cut_out(im: Image.Image) -> Image.Image:
    """RGBA-Bild mit transparentem Hintergrund (oder unverändert, wenn kein einfarbiger Hintergrund erkennbar)."""
    im = im.convert("RGBA")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    if im.getchannel("A").getextrema()[0] < 250:
        return im  # schon freigestellt
    rgb = im.convert("RGB")
    color = _border_color(rgb)
    if color is None:
        return im
    distance = _channel_max(ImageChops.difference(rgb, Image.new("RGB", rgb.size, color)))
    region = _background_region(distance)
    if region is None:
        return im
    ramp = distance.point(lambda v: 0 if v <= TOLERANCE else min(255, (v - TOLERANCE) * 255 // SOFT))
    im.putalpha(ImageChops.lighter(ramp, ImageChops.invert(region)))
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        l, t, r, b = box
        im = im.crop((max(0, l - PADDING), max(0, t - PADDING), min(im.width, r + PADDING), min(im.height, b + PADDING)))
    return im


def product_png(data: bytes) -> bytes:
    """Hochgeladenes Produktbild -> PNG, Hintergrund wenn möglich transparent."""
    out = io.BytesIO()
    cut_out(open_image(data)).save(out, "PNG", optimize=True)
    return out.getvalue()
