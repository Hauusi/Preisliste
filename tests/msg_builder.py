"""Kleine Outlook-.msg-Dateien für Tests bauen (OLE-Verbunddatei, nur normale Sektoren).

Kein vollständiger Writer: Streams unter 4096 Byte liegen im Mini-Stream (64-Byte-Sektoren), größere in normalen
512-Byte-Sektoren; die Geschwister im Verzeichnis sind als rechte Kette verknüpft. Genügt für olefile/msgfile.
"""

import struct

END, FREE, FATSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF


def _prop_text(pid: str, value: str) -> tuple[str, bytes]:
    return f"__substg1.0_{pid}001F", value.encode("utf-16-le")


def _fixed_props(header: int, items: list[tuple[int, int, bytes]]) -> bytes:
    out = b"\x00" * header
    for pid, ptype, val in items:
        out += struct.pack("<II", (pid << 16) | ptype, 6) + val.ljust(8, b"\x00")[:8]
    return out


def build_msg(subject="Angebot Spartan", sender="Max Muster", mail="max@example.com", to=("Anna <anna@example.com>",),
              body="Hallo,\nanbei das Angebot.\nGruß Max", filetime=133000000000000000,
              attachments=(("Angebot.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf"),)) -> bytes:
    # Baum: [(Name, Daten oder None für Speicher, Kinder)]
    top = [_prop_text("0037", subject), _prop_text("0C1A", sender), _prop_text("5D01", mail), _prop_text("1000", body),
           ("__properties_version1.0", _fixed_props(32, [(0x0039, 0x0040, struct.pack("<Q", filetime))]))]
    tree = [(n, d, None) for n, d in top]
    for i, r in enumerate(to):
        name, addr = (r.split(" <")[0], r.split("<")[1].rstrip(">")) if "<" in r else (r, r)
        kids = [_prop_text("3001", name), _prop_text("39FE", addr),
                ("__properties_version1.0", _fixed_props(8, [(0x0C15, 0x0003, struct.pack("<I", 1))]))]
        tree.append((f"__recip_version1.0_#{i:08X}", None, [(n, d, None) for n, d in kids]))
    for i, (fname, data, mime) in enumerate(attachments):
        kids = [_prop_text("3707", fname), ("__substg1.0_37010102", data), _prop_text("370E", mime)]
        tree.append((f"__attach_version1.0_#{i:08X}", None, [(n, d, None) for n, d in kids]))

    entries, streams = [], []  # Verzeichnis: dict je Eintrag

    def add(name, data, kids):
        idx = len(entries)
        e = {"name": name, "type": 1 if data is None else 2, "left": NOSTREAM, "right": NOSTREAM, "child": NOSTREAM,
             "data": data}
        entries.append(e)
        if kids:
            ids = [add(*k) for k in kids]
            e["child"] = ids[0]
            for a, b in zip(ids, ids[1:]):
                entries[a]["right"] = b
        return idx

    root = {"name": "Root Entry", "type": 5, "left": NOSTREAM, "right": NOSTREAM, "child": NOSTREAM, "data": None}
    entries.append(root)
    ids = [add(*k) for k in tree]
    root["child"] = ids[0]
    for a, b in zip(ids, ids[1:]):
        entries[a]["right"] = b

    # Sektoren: zuerst Daten der Streams, dann Verzeichnis, dann FAT
    sectors, fat = [], []

    def put(data):
        start = len(sectors)
        n = max(1, (len(data) + 511) // 512)
        for k in range(n):
            sectors.append(data[k * 512:(k + 1) * 512].ljust(512, b"\x00"))
            fat.append(start + k + 1 if k < n - 1 else END)
        return start

    mini, minifat = b"", []
    for e in entries:
        if e["type"] != 2 or not e["data"]:
            e["start"], e["size"] = END, 0
        elif len(e["data"]) < 4096:  # Mini-Stream
            start, n = len(minifat), (len(e["data"]) + 63) // 64
            mini += e["data"].ljust(n * 64, b"\x00")
            minifat += [start + k + 1 if k < n - 1 else END for k in range(n)]
            e["start"], e["size"] = start, len(e["data"])
        else:
            e["start"], e["size"] = put(e["data"]), len(e["data"])
    if mini:
        root["start"], root["size"] = put(mini), len(mini)
        mfd = b"".join(struct.pack("<I", x) for x in minifat + [FREE] * (-len(minifat) % 128))
        minifat_start, n_minifat = put(mfd), len(mfd) // 512
    else:
        minifat_start, n_minifat = END, 0
    dirdata = b""
    for e in entries:
        nm = e["name"].encode("utf-16-le") + b"\x00\x00"
        dirdata += (nm.ljust(64, b"\x00") + struct.pack("<HBB", len(nm), e["type"], 1)
                    + struct.pack("<III", e["left"], e["right"], e["child"]) + b"\x00" * 16 + b"\x00" * 4
                    + b"\x00" * 16 + struct.pack("<IQ", e["start"], e["size"]))
    dir_start = put(dirdata.ljust(((len(dirdata) + 511) // 512) * 512, b"\x00"))
    n_fat = 1
    while (len(sectors) + n_fat) > n_fat * 128:
        n_fat += 1
    fat_start = len(sectors)
    fat += [FATSECT] * n_fat
    fat += [FREE] * (n_fat * 128 - len(fat))
    fatdata = b"".join(struct.pack("<I", x) for x in fat)
    for k in range(n_fat):
        sectors.append(fatdata[k * 512:(k + 1) * 512])
    difat = [fat_start + k for k in range(n_fat)] + [FREE] * (109 - n_fat)
    header = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)
              + b"\x00" * 6 + struct.pack("<IIIIIIIII", 0, n_fat, dir_start, 0, 4096, minifat_start, n_minifat, END, 0)
              + b"".join(struct.pack("<I", x) for x in difat))
    return header + b"".join(sectors)
