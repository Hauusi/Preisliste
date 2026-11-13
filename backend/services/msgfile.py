"""Outlook-E-Mails (.msg) lesen, ohne Outlook: Betreff, Absender, Empfänger, Datum, Text und Anhänge.

Das .msg-Format ist ein OLE-Verbunddokument (wie alte Office-Dateien). Die Felder liegen als MAPI-Eigenschaften in
Streams „__substg1.0_<ID><TYP>“; feste Werte (z. B. Datum) im Stream „__properties_version1.0“. Gelesen wird nur,
was zum Anzeigen gebraucht wird. HTML wird nie als HTML ausgegeben, sondern in reinen Text umgewandelt.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import struct
from html.parser import HTMLParser
from io import BytesIO

import olefile

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def is_msg(data: bytes) -> bool:
    """Echte Outlook-Nachricht? (OLE-Datei mit MAPI-Eigenschaften)"""
    if not data.startswith(OLE_MAGIC):
        return False
    try:
        ole = olefile.OleFileIO(BytesIO(data))
    except Exception:  # noqa: BLE001 – kaputte Datei
        return False
    try:
        return any(e[0].startswith("__substg1.0_") for e in ole.listdir())
    finally:
        ole.close()


def _text(ole, prefix: str, prop: str, codepage: str = "cp1252") -> str:
    """Text-Eigenschaft (Unicode 001F oder 8-Bit 001E)."""
    for typ, enc in (("001F", "utf-16-le"), ("001E", codepage)):
        name = f"{prefix}__substg1.0_{prop}{typ}"
        if ole.exists(name):
            raw = ole.openstream(name).read()
            return raw.decode(enc, errors="replace").rstrip("\x00").strip()
    return ""


def _binary(ole, prefix: str, prop: str) -> bytes | None:
    name = f"{prefix}__substg1.0_{prop}0102"
    return ole.openstream(name).read() if ole.exists(name) else None


def _fixed(ole, prefix: str, header: int) -> dict[int, bytes]:
    """Feste Eigenschaften aus __properties_version1.0: {Eigenschaft-ID: 8 Byte Wert}."""
    name = f"{prefix}__properties_version1.0"
    if not ole.exists(name):
        return {}
    raw = ole.openstream(name).read()[header:]
    out = {}
    for i in range(0, len(raw) - 15, 16):
        tag, _flags = struct.unpack_from("<II", raw, i)
        out[tag >> 16] = raw[i + 8:i + 16]
    return out


def _filetime(value: bytes | None) -> dt.datetime | None:
    if not value:
        return None
    ticks = struct.unpack("<Q", value)[0]
    if not ticks:
        return None
    try:
        return dt.datetime(1601, 1, 1) + dt.timedelta(microseconds=ticks // 10)
    except OverflowError:
        return None


class _HtmlText(HTMLParser):
    """HTML → lesbarer Text (Zeilenumbrüche bei Blöcken, kein Skript/Stil)."""
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "tr", "table", "blockquote"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    p = _HtmlText()
    try:
        p.feed(raw)
        p.close()
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html.unescape(raw))
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _tidy(text: str) -> str:
    """Zeilenenden vereinheitlichen, Leerzeilen-Stapel auf eine Leerzeile kürzen."""
    text = re.sub(r"[ \t\xa0]+\n", "\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def read(data: bytes) -> dict:
    """Inhalt einer .msg-Datei als dict (Betreff, Absender, An, Cc, Datum, Text, Anhänge)."""
    ole = olefile.OleFileIO(BytesIO(data))
    try:
        subject = _text(ole, "", "0037")
        sender = _text(ole, "", "0C1A")
        sender_mail = _text(ole, "", "5D01") or _text(ole, "", "0C1F") or _text(ole, "", "0065")
        fixed = _fixed(ole, "", 32)
        sent = _filetime(fixed.get(0x0039)) or _filetime(fixed.get(0x0E06))
        body = _text(ole, "", "1000")
        if not body:
            raw_html = _binary(ole, "", "1013") or _text(ole, "", "1013").encode("utf-8")
            if raw_html:
                m = re.search(rb'charset=["\']?([\w-]+)', raw_html[:2000], re.I)
                try:
                    body = html_to_text(raw_html.decode(m.group(1).decode() if m else "utf-8", errors="replace"))
                except LookupError:
                    body = html_to_text(raw_html.decode("utf-8", errors="replace"))
        to, cc = [], []
        dirs = {e[0] for e in ole.listdir(streams=True, storages=True)}
        for d in sorted(x for x in dirs if x.startswith("__recip_version1.0_")):
            p = d + "/"
            name, mail = _text(ole, p, "3001"), _text(ole, p, "39FE") or _text(ole, p, "3003")
            kind = _fixed(ole, p, 8).get(0x0C15)
            entry = f"{name} <{mail}>" if name and mail and name != mail else (name or mail)
            (cc if kind and struct.unpack("<I", kind[:4])[0] == 2 else to).append(entry)
        atts = []
        for d in sorted(x for x in dirs if x.startswith("__attach_version1.0_")):
            p = d + "/"
            payload = _binary(ole, p, "3701")
            name = _text(ole, p, "3707") or _text(ole, p, "3704") or _text(ole, p, "3001") or "Anhang"
            if payload is None:  # z. B. eingebettete E-Mail – nicht zum Herunterladen
                atts.append({"name": name, "size": None, "mime": "", "data": None})
                continue
            atts.append({"name": name, "size": len(payload), "mime": _text(ole, p, "370E"), "data": payload})
        return {"subject": subject, "sender": sender, "sender_mail": sender_mail, "to": to, "cc": cc,
                "date": sent, "body": _tidy(body), "attachments": atts}
    finally:
        ole.close()
