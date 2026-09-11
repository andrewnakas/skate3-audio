#!/usr/bin/env python3
"""Extract the RenderWare Audio plug-in metadata from a decrypted Skate 3 image.

Skate 3 links RenderWare Audio, whose plug-ins are self-describing: every plug-in
carries a 4CC tag, a name, factory function pointers, and tables of attribute,
event, parameter and enum descriptors -- each with an identifier, a display name
and prose documentation. The retail build has RTTI disabled, so this metadata is
the primary source of semantic names for the audio band (0x82B00000-0x82B87000).

Descriptor layouts recovered from the image (all big-endian):

  enum value   +0 char* identifier  +4 char* display  +8 char* doc  +12 u32 value
  enum type    +0 char* name        +4 char* doc      +8 u32 count  +12 EnumValue*
  plug-in      +0 char* name        +4 fn*            +8 fn*        ... +N u32 4CC

Usage:  rw_audio_extract.py <image.bin> [--base 0x82000000]
"""
import argparse, json, struct, sys

AUDIO_LO, AUDIO_HI = 0x82B00000, 0x82B87000
TEXT_LO, TEXT_HI = 0x82380000, 0x82FA0000


class Image:
    def __init__(self, path, base):
        self.data = open(path, "rb").read()
        self.base = base

    def __len__(self):
        return len(self.data)

    def contains(self, addr):
        return self.base <= addr < self.base + len(self.data)

    def u32(self, addr):
        return struct.unpack_from(">I", self.data, addr - self.base)[0]

    def cstr(self, addr, maxlen=4096):
        """Return the NUL-terminated ASCII string at addr, or None."""
        if not self.contains(addr):
            return None
        off = addr - self.base
        end = self.data.find(b"\0", off)
        if end < 0 or end == off or end - off > maxlen:
            return None
        try:
            text = self.data[off:end].decode("ascii")
        except UnicodeDecodeError:
            return None
        return text if all(32 <= ord(c) < 127 for c in text) else None


def fourcc(value):
    raw = struct.pack(">I", value)
    return raw.decode("latin1") if all(0x30 <= c < 0x7F for c in raw) else None


def find_plugins(img):
    """A plug-in record: name pointer, two code pointers, then a 4CC ending in '0'."""
    found = []
    for off in range(0, len(img) - 64, 4):
        addr = img.base + off
        name = img.cstr(img.u32(addr), 40)
        if not name or len(name) < 3:
            continue
        fn1, fn2 = img.u32(addr + 4), img.u32(addr + 8)
        if not (TEXT_LO <= fn1 < TEXT_HI and TEXT_LO <= fn2 < TEXT_HI):
            continue
        for k in range(3, 16):
            tag = fourcc(img.u32(addr + 4 * k))
            if tag and tag.endswith("0"):
                found.append({"record": addr, "tag": tag, "name": name,
                              "fn1": fn1, "fn2": fn2})
                break
    return found


def find_enums(img):
    """Enum type descriptors: name, doc, count, and a pointer to `count` values."""
    out = []
    for off in range(0, len(img) - 16, 4):
        addr = img.base + off
        name, doc = img.cstr(img.u32(addr), 64), img.cstr(img.u32(addr + 4), 4096)
        count, values = img.u32(addr + 8), img.u32(addr + 12)
        if not name or not doc or not 1 <= count <= 64 or not img.contains(values):
            continue
        entries = []
        for i in range(count):
            v = values + 16 * i
            ident = img.cstr(img.u32(v), 64)
            if not ident:
                break
            entries.append({"identifier": ident,
                            "display": img.cstr(img.u32(v + 4), 200),
                            "value": img.u32(v + 12)})
        if len(entries) == count:
            out.append({"record": addr, "name": name, "doc": doc, "values": entries})
    return out



def find_plugin_functions(img, plugins):
    """Map every audio-band function reachable from a plug-in record to its users.

    A record carries two function pointers inline at +4/+8, and four pointers at
    +12..+24 into a constants region where a few more functions sit. Functions are
    shared: the filter families route through one implementation, so the result maps
    address -> set of plug-in names rather than the reverse.
    """
    users = {}

    def note(addr, name):
        if AUDIO_LO <= addr < AUDIO_HI:
            users.setdefault(addr, set()).add(name)

    for p in plugins:
        note(p["fn1"], p["name"])
        note(p["fn2"], p["name"])
        for slot in range(3, 7):
            table = img.u32(p["record"] + 4 * slot)
            if not (0x82F00000 <= table < img.base + len(img)):
                continue
            for k in range(-1, 6):
                note(img.u32(table + 4 * k), p["name"])
    return users


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0x82000000)
    ap.add_argument("--json", help="write full results here")
    ap.add_argument("--toml", help="write a rexglue [functions] name table here")
    args = ap.parse_args()

    img = Image(args.image, args.base)
    plugins = find_plugins(img)
    enums = find_enums(img)

    print(f"{len(plugins)} plug-ins, {len(enums)} enum types\n")
    print(f"{'record':>10}  {'4CC':5} {'name':26} {'fn1':>9} {'fn2':>9}")
    for p in plugins:
        print(f"{p['record']:08X}  {p['tag']:5} {p['name']:26.26} "
              f"{p['fn1']:08X}  {p['fn2']:08X}")

    print(f"\n{'enum':30} values")
    for e in enums:
        vals = ", ".join(f"{v['identifier']}={v['value']}" for v in e["values"])
        print(f"  {e['name']:28.28} {vals[:110]}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"plugins": plugins, "enums": enums}, fh, indent=2)
        print(f"\nwrote {args.json}")

    if args.toml:
        # Several plug-ins share a function: the filter families (High/LowPass
        # Butterworth, Fir64, Iir2; BandPass/High/LowShelf Iir2) route through one
        # implementation each. So group by address -- emitting one entry per
        # plug-in would produce duplicate TOML keys and break codegen. The two
        # pointer slots are named f0/f1 rather than guessed at; what they dispatch
        # to has not been established yet.
        users = find_plugin_functions(img, plugins)

        with open(args.toml, "w") as fh:
            fh.write("# Generated by tools/rw_audio_extract.py -- do not edit.\n")
            fh.write("# RenderWare Audio plug-in functions, named from the metadata\n")
            fh.write("# the retail image carries about itself. Merge into\n")
            fh.write("# config/skate3_tu_functions.toml under [functions].\n\n")
            for addr in sorted(users):
                names = sorted(users[addr])
                ident = f"rwaudio_{'_'.join(names)}_{addr:08X}"
                if len(names) > 1:
                    fh.write(f"# shared by {', '.join(names)}\n")
                fh.write(f'"0x{addr:08X}" = {{ name = "{ident}" }}\n')
        print(f"wrote {args.toml} ({len(users)} unique addresses)")


if __name__ == "__main__":
    sys.exit(main())
