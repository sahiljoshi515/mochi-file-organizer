"""A raw DEFLATE decoder (RFC 1951) for the few small zip entries the rules read ([Content_Types].xml,
docProps/core.xml, meta.xml, mimetype). A verifier may not import zlib, so this is by hand: canonical
Huffman codes are decoded through lookup tables, and what counts as a valid stream follows Mark Adler's
puff.c.

It reads only the start of a stream: at most `limit` bytes of output and at most `blocks` blocks (RULES.md
§3, "Reading limits"), so its cost is bounded whatever the stream holds.

Shared, byte for byte, by src/plugin/ and verifier/. `inflate` never raises: a stream that is not valid
DEFLATE as far as it is read gives None.
"""

from __future__ import annotations

MAX_BITS = 15
LENGTH_BASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)
LENGTH_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)
DIST_BASE = (
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769,
    1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
)  # fmt: skip
DIST_EXTRA = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13)
CODE_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)


class Malformed(ValueError):
    """The stream is not valid DEFLATE."""


class Stream:
    """A byte string read as a little-endian bit stream, refilled a byte at a time."""

    def __init__(self, data: bytes, start: int, end: int) -> None:
        self.data = data
        self.pos = start
        self.end = end
        self.buffer = 0
        self.count = 0

    def fill(self) -> None:
        """Hold at least 32 bits, or every bit left."""
        while self.count < 32 and self.pos < self.end:
            self.buffer |= self.data[self.pos] << self.count
            self.pos += 1
            self.count += 8

    def take(self, need: int) -> int:
        if self.count < need:
            self.fill()
            if self.count < need:
                raise Malformed("the stream ends early")
        value = self.buffer & ((1 << need) - 1)
        self.buffer >>= need
        self.count -= need
        return value

    def to_byte(self) -> None:
        """Drop the bits left in the current byte and give back the whole bytes read ahead."""
        self.pos -= self.count // 8
        self.buffer = 0
        self.count = 0


def counted(lengths: list[int]) -> tuple[list[int], int]:
    """How many codes of each length, and how many codes are left unused (negative: over-subscribed)."""
    counts = [0] * (MAX_BITS + 1)
    for length in lengths:
        counts[length] += 1
    left = 1
    for length in range(1, MAX_BITS + 1):
        left = (left << 1) - counts[length]
        if left < 0:
            return counts, left
    return counts, left


def reversed_bits(code: int, length: int) -> int:
    result = 0
    for _index in range(length):
        result = (result << 1) | (code & 1)
        code >>= 1
    return result


def lookup(lengths: list[int], counts: list[int]) -> tuple[list[int], int]:
    """A table indexed by the stream's next `width` bits (the first bit lowest): for each, the code's
    symbol << 4 | its length, or -1 where no code starts."""
    width = max(lengths) or 1
    table = [-1] * (1 << width)
    next_code = [0] * (MAX_BITS + 1)
    code = 0
    for length in range(1, MAX_BITS + 1):
        next_code[length] = code
        code = (code + counts[length]) << 1
    for found, length in enumerate(lengths):
        if length:
            first = reversed_bits(next_code[length], length)
            next_code[length] += 1
            table[first :: 1 << length] = [found << 4 | length] * (1 << (width - length))
    return table, width


def fixed(lengths: list[int]) -> tuple[list[int], int]:
    """The fixed codes' tables, as RFC 1951 3.2.6 gives them (the distance code is incomplete by design)."""
    return lookup(lengths, counted(lengths)[0])


FIXED_LITERALS = fixed([8] * 144 + [9] * 112 + [7] * 24 + [8] * 8)
FIXED_DISTANCES = fixed([5] * 30)


def code_table(lengths: list[int], single_allowed: bool) -> tuple[list[int], int]:
    counts, left = counted(lengths)
    if left < 0:
        raise Malformed("an over-subscribed code")
    used = len(lengths) - counts[0]
    # An incomplete code is allowed only as a single code of length 1 (RFC 1951 3.2.7, as puff.c reads it).
    if left and used and not (single_allowed and used == counts[1]):
        raise Malformed("an incomplete code")
    return lookup(lengths, counts)


def symbol(stream: Stream, table: list[int], width: int) -> int:
    if stream.count < MAX_BITS:
        stream.fill()
    entry = table[stream.buffer & ((1 << width) - 1)]
    length = entry & 15
    if entry < 0 or length > stream.count:
        raise Malformed("a code that is not in the table, or the stream ends early")
    stream.buffer >>= length
    stream.count -= length
    return entry >> 4


def dynamic_tables(stream: Stream) -> tuple[tuple[list[int], int], tuple[list[int], int]]:
    literals = stream.take(5) + 257
    distances = stream.take(5) + 1
    code_count = stream.take(4) + 4
    if literals > 286 or distances > 30:
        raise Malformed("too many codes")
    code_lengths = [0] * 19
    for index in range(code_count):
        code_lengths[CODE_ORDER[index]] = stream.take(3)
    counts, left = counted(code_lengths)
    if left != 0:
        raise Malformed("an incomplete or over-subscribed code-length code")
    length_table, length_width = lookup(code_lengths, counts)
    lengths: list[int] = []
    while len(lengths) < literals + distances:
        found = symbol(stream, length_table, length_width)
        if found < 16:
            lengths.append(found)
            continue
        if found == 16:
            if not lengths:
                raise Malformed("a repeat with nothing to repeat")
            value, repeat = lengths[-1], 3 + stream.take(2)
        elif found == 17:
            value, repeat = 0, 3 + stream.take(3)
        else:
            value, repeat = 0, 11 + stream.take(7)
        if len(lengths) + repeat > literals + distances:
            raise Malformed("too many lengths")
        lengths.extend([value] * repeat)
    if lengths[256] == 0:
        raise Malformed("no end-of-block code")
    return code_table(lengths[:literals], True), code_table(lengths[literals:], True)


def codes(stream: Stream, out: bytearray, literal: tuple[list[int], int], distance: tuple[list[int], int], limit: int) -> bool:
    """Decode one block's codes into `out`; True when `out` reached `limit` (the reading stops)."""
    literal_table, literal_width = literal
    distance_table, distance_width = distance
    while True:
        found = symbol(stream, literal_table, literal_width)
        if found < 256:
            out.append(found)
            if len(out) >= limit:
                return True
            continue
        if found == 256:
            return False
        found -= 257
        if found >= 29:
            raise Malformed("a bad length symbol")
        length = LENGTH_BASE[found] + stream.take(LENGTH_EXTRA[found])
        found = symbol(stream, distance_table, distance_width)
        if found >= 30:
            raise Malformed("a bad distance symbol")
        back = DIST_BASE[found] + stream.take(DIST_EXTRA[found])
        if back > len(out):
            raise Malformed("a distance before the start")
        start = len(out) - back
        if back >= length:
            out += out[start : start + length]
        else:
            out += (out[start:] * (length // back + 1))[:length]
        if len(out) >= limit:
            del out[limit:]
            return True


def inflate(data: bytes, limit: int, blocks: int = 4, start: int = 0, end: int | None = None) -> bytes | None:
    """The first `limit` bytes the raw DEFLATE stream in data[start:end] decodes to, reading at most
    `blocks` blocks (fewer bytes when the stream or those blocks end first), or None when what is read
    is not valid DEFLATE."""
    stream = Stream(data, start, len(data) if end is None else end)
    out = bytearray()
    try:
        for _block in range(blocks):
            last = stream.take(1)
            kind = stream.take(2)
            if kind == 0:
                stream.to_byte()
                if stream.pos + 4 > stream.end:
                    raise Malformed("a stored block ends early")
                length = data[stream.pos] | data[stream.pos + 1] << 8
                check = data[stream.pos + 2] | data[stream.pos + 3] << 8
                if length != (~check & 0xFFFF):
                    raise Malformed("a stored block's length does not check")
                stream.pos += 4
                if stream.pos + length > stream.end:
                    raise Malformed("a stored block ends early")
                out += data[stream.pos : stream.pos + min(length, limit - len(out))]
                stream.pos += length
                full = len(out) >= limit
            elif kind == 1:
                full = codes(stream, out, FIXED_LITERALS, FIXED_DISTANCES, limit)
            elif kind == 2:
                full = codes(stream, out, *dynamic_tables(stream), limit)
            else:
                raise Malformed("block type 3")
            if full or last:
                break
    except Malformed:
        return None
    return bytes(out)
