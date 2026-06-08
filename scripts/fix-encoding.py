#!/usr/bin/env python3
"""Fix double-encoded UTF-8 (Win-1252 mojibake) in frontend TypeScript/CSS files."""
import os, sys, glob

# Windows-1252 0x80-0x9F mapping
WIN1252 = {
    0x80: 0x20AC, 0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E, 0x85: 0x2026,
    0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02C6, 0x89: 0x2030, 0x8A: 0x0160,
    0x8B: 0x2039, 0x8C: 0x0152, 0x8E: 0x017D, 0x91: 0x2018, 0x92: 0x2019,
    0x93: 0x201C, 0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014,
    0x98: 0x02DC, 0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A, 0x9C: 0x0153,
    0x9E: 0x017E, 0x9F: 0x0178,
}

def btu(b):
    return WIN1252.get(b, b)

def double_enc(orig_bytes):
    try:
        return b''.join(chr(btu(b)).encode('utf-8') for b in orig_bytes)
    except Exception:
        return None

# Build replacement table for all 2-byte and 3-byte UTF-8 sequences that appear garbled
REPLACEMENTS = {}

# 3-byte sequences: cover E0-EF range but focus on E2 (most typographic chars)
for b1 in range(0xE0, 0xF0):
    for b2 in range(0x80, 0xC0):
        for b3 in range(0x80, 0xC0):
            orig = bytes([b1, b2, b3])
            try:
                orig.decode('utf-8')
            except Exception:
                continue
            wrong = double_enc(orig)
            if wrong and wrong != orig:
                REPLACEMENTS[wrong] = orig

# 2-byte sequences: C2-DF range
for b1 in range(0xC2, 0xE0):
    for b2 in range(0x80, 0xC0):
        orig = bytes([b1, b2])
        try:
            orig.decode('utf-8')
        except Exception:
            continue
        wrong = double_enc(orig)
        if wrong and wrong != orig:
            REPLACEMENTS[wrong] = orig

# Sort longest-first to avoid partial matches
SORTED_REPS = sorted(REPLACEMENTS.items(), key=lambda x: -len(x[0]))

# Also build a byte-level inverse for 4-byte emoji decoding
WIN1252_INV = {}
for b in range(0x00, 0x100):
    cp = btu(b)
    try:
        enc = chr(cp).encode('utf-8')
        WIN1252_INV[enc] = b
    except Exception:
        pass
# Sort longest-first
WIN1252_INV_SORTED = sorted(WIN1252_INV.items(), key=lambda x: -len(x[0]))


def decode_one_wrong(data, pos):
    for wrong_bytes, orig_byte in WIN1252_INV_SORTED:
        if data[pos:pos+len(wrong_bytes)] == wrong_bytes:
            return orig_byte, len(wrong_bytes)
    return None, 0


def fix_emoji(content):
    """Decode double-encoded 4-byte emoji (F0 9F ... pattern)."""
    F0_9F_WRONG = bytes.fromhex('c3b0c5b8')
    if F0_9F_WRONG not in content:
        return content, 0
    result = bytearray()
    i = 0
    fixes = 0
    while i < len(content):
        if content[i:i+4] == F0_9F_WRONG:
            orig_bytes = bytearray()
            j = i
            ok = True
            for _ in range(4):
                orig_byte, consumed = decode_one_wrong(content, j)
                if orig_byte is None:
                    ok = False
                    break
                orig_bytes.append(orig_byte)
                j += consumed
            if ok and len(orig_bytes) == 4:
                try:
                    orig_bytes.decode('utf-8')
                    result.extend(orig_bytes)
                    i = j
                    fixes += 1
                    continue
                except Exception:
                    pass
        result.append(content[i])
        i += 1
    return bytes(result), fixes


def fix_file(path):
    with open(path, 'rb') as f:
        content = f.read()

    original = content

    # Apply 2/3-byte replacements
    for wrong, correct in SORTED_REPS:
        content = content.replace(wrong, correct)

    # Apply 4-byte emoji fix
    content, emoji_fixes = fix_emoji(content)

    if content == original:
        return False, 0, 0

    # Verify result is valid UTF-8
    try:
        content.decode('utf-8')
    except UnicodeDecodeError as e:
        print(f"  SKIP {path}: result not valid UTF-8: {e}", file=sys.stderr)
        return False, 0, 0

    with open(path, 'wb') as f:
        f.write(content)

    chars_fixed = sum(1 for a, b in zip(content, original) if a != b)
    return True, chars_fixed, emoji_fixes


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend = os.path.join(root, 'frontend')

    patterns = [
        os.path.join(frontend, 'components', '*.tsx'),
        os.path.join(frontend, 'app', '**', '*.tsx'),
        os.path.join(frontend, 'app', '**', '*.css'),
        os.path.join(frontend, 'lib', '*.ts'),
    ]

    total_fixed = 0
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            changed, chars, emojis = fix_file(path)
            if changed:
                rel = os.path.relpath(path, root)
                print(f"  fixed {rel}: {chars} bytes, {emojis} emoji")
                total_fixed += 1

    print(f"\nTotal files fixed: {total_fixed}")
