"""Kleine PDFs für Tests: Textzeilen an festen Positionen (Helvetica) und optional ein Bild mit Transparenz."""

import zlib


def _esc(text: str) -> bytes:
    return text.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_pdf(pages: list[list[tuple[float, float, float, str]]], image_on_page: int | None = None,
             title: str | None = None) -> bytes:
    """pages: je Seite Liste (x, y, Schriftgröße, Text) in pt (A4 = 595 × 842). Bild: 200 × 140 px, Mitte rot,
    Rand transparent (wie ein freigestelltes Produktfoto)."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    img = smask = None
    if image_on_page is not None:
        w, h = 200, 140
        rgb, alpha = bytearray(), bytearray()
        for y in range(h):
            for x in range(w):
                inside = 30 < x < w - 30 and 25 < y < h - 25
                rgb += bytes((220, 40, 30) if inside else (255, 255, 255))
                alpha.append(255 if inside else 0)
        sm = zlib.compress(bytes(alpha))
        smask = add(b"<< /Type /XObject /Subtype /Image /Width 200 /Height 140 /ColorSpace /DeviceGray "
                    b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % len(sm) + sm + b"\nendstream")
        data = zlib.compress(bytes(rgb))
        img = add(b"<< /Type /XObject /Subtype /Image /Width 200 /Height 140 /ColorSpace /DeviceRGB "
                  b"/BitsPerComponent 8 /SMask %d 0 R /Filter /FlateDecode /Length %d >>\nstream\n" % (smask, len(data))
                  + data + b"\nendstream")
    page_ids = []
    pages_id = len(objs) + 2 * len(pages) + 1
    for i, lines in enumerate(pages):
        stream = b"".join(b"BT /F1 %.1f Tf %.1f %.1f Td (%s) Tj ET\n" % (size, x, y, _esc(t)) for x, y, size, t in lines)
        res = b"/Font << /F1 %d 0 R >>" % font
        if img and i == image_on_page:
            stream += b"q 200 0 0 140 330 560 cm /Im1 Do Q\n"
            res += b" /XObject << /Im1 %d 0 R >>" % img
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Resources << %s >> "
                            b"/Contents %d 0 R >>" % (pages_id, res, content)))
    assert add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % p for p in page_ids),
                                                            len(page_ids))) == pages_id
    info = add(b"<< /Title (%s) >>" % _esc(title)) if title else None
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R%s >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, catalog, (b" /Info %d 0 R" % info) if info else b"", xref)
    return bytes(out)
