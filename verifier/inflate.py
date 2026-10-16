"""A raw DEFLATE decoder (RFC 1951), after Mark Adler's puff.c, for the few small zip entries the rules
read (docProps/core.xml, meta.xml, mimetype). A verifier may not import zlib, so this is by hand.

Shared, byte for byte, by src/plugin/ and verifier/. `inflate` never raises: malformed input, or
output that would pass `limit` bytes, gives None.
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
    """The stream is not valid DEFLATE, or its output would pass the limit."""


class Bits:
    """Reads a byte string as a little-endian bit stream."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.buffer = 0
        self.count = 0

    def take(self, need: int) -> int:
        value = self.buffer
        while self.count < need:
            if self.pos >= len(self.data):
                raise Malformed("the stream ends early")
            value |= self.data[self.pos] << self.count
            self.pos += 1
            self.count += 8
        self.buffer = value >> need
        self.count -= need
        return value & ((1 << need) - 1)

    def align(self) -> None:
        self.buffer = 0
        self.count = 0


class Huffman:
    """A canonical Huffman code: how many codes of each length, and the symbols in code order."""

    def __init__(self, lengths: list[int]) -> None:
        self.counts = [0] * (MAX_BITS + 1)
        for length in lengths:
            self.counts[length] += 1
        self.symbols: list[int] = []
        self.left = 0
        if self.counts[0] == len(lengths):
            return
        left = 1
        for length in range(1, MAX_BITS + 1):
            left = (left << 1) - self.counts[length]
            if left < 0:
                raise Malformed("an over-subscribed code")
        self.left = left
        offsets = [0] * (MAX_BITS + 2)
        for length in range(1, MAX_BITS + 1):
            offsets[length + 1] = offsets[length] + self.counts[length]
        self.symbols = [0] * offsets[MAX_BITS + 1]
        for symbol, length in enumerate(lengths):
            if length:
                self.symbols[offsets[length]] = symbol
                offsets[length] += 1

    def decode(self, bits: Bits) -> int:
        code = first = index = 0
        for length in range(1, MAX_BITS + 1):
            code |= bits.take(1)
            count = self.counts[length]
            if code - count < first:
                return self.symbols[index + (code - first)]
            index += count
            first = (first + count) << 1
            code <<= 1
        raise Malformed("a code that is not in the table")


def fixed_tables() -> tuple[Huffman, Huffman]:
    lengths = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
    return Huffman(lengths), Huffman([5] * 30)


def dynamic_tables(bits: Bits) -> tuple[Huffman, Huffman]:
    literals = bits.take(5) + 257
    distances = bits.take(5) + 1
    code_count = bits.take(4) + 4
    if literals > 286 or distances > 30:
        raise Malformed("too many codes")
    code_lengths = [0] * 19
    for index in range(code_count):
        code_lengths[CODE_ORDER[index]] = bits.take(3)
    lencode = Huffman(code_lengths)
    if lencode.left != 0:
        raise Malformed("an incomplete code-length code")
    lengths: list[int] = []
    while len(lengths) < literals + distances:
        symbol = lencode.decode(bits)
        if symbol < 16:
            lengths.append(symbol)
            continue
        if symbol == 16:
            if not lengths:
                raise Malformed("a repeat with nothing to repeat")
            value, repeat = lengths[-1], 3 + bits.take(2)
        elif symbol == 17:
            value, repeat = 0, 3 + bits.take(3)
        else:
            value, repeat = 0, 11 + bits.take(7)
        if len(lengths) + repeat > literals + distances:
            raise Malformed("too many lengths")
        lengths.extend([value] * repeat)
    if lengths[256] == 0:
        raise Malformed("no end-of-block code")
    literal_code = Huffman(lengths[:literals])
    # An incomplete code is allowed only as a single code of length 1 (RFC 1951 3.2.7, as puff.c reads it).
    if literal_code.left and literals != literal_code.counts[0] + literal_code.counts[1]:
        raise Malformed("an incomplete literal/length code")
    distance_code = Huffman(lengths[literals:])
    if distance_code.left and distances != distance_code.counts[0] + distance_code.counts[1]:
        raise Malformed("an incomplete distance code")
    return literal_code, distance_code


def codes(bits: Bits, out: bytearray, literal_code: Huffman, distance_code: Huffman, limit: int) -> None:
    while True:
        symbol = literal_code.decode(bits)
        if symbol < 256:
            out.append(symbol)
        elif symbol == 256:
            return
        else:
            symbol -= 257
            if symbol >= 29:
                raise Malformed("a bad length symbol")
            length = LENGTH_BASE[symbol] + bits.take(LENGTH_EXTRA[symbol])
            symbol = distance_code.decode(bits)
            if symbol >= 30:
                raise Malformed("a bad distance symbol")
            distance = DIST_BASE[symbol] + bits.take(DIST_EXTRA[symbol])
            if distance > len(out):
                raise Malformed("a distance before the start")
            start = len(out) - distance
            for offset in range(length):
                out.append(out[start + offset])
        if len(out) > limit:
            raise Malformed("the output passes the limit")


def inflate(data: bytes, limit: int) -> bytes | None:
    """The raw DEFLATE stream `data` decoded, or None when it is malformed or decodes to more than `limit` bytes."""
    bits = Bits(data)
    out = bytearray()
    try:
        while True:
            last = bits.take(1)
            kind = bits.take(2)
            if kind == 0:
                bits.align()
                if bits.pos + 4 > len(data):
                    raise Malformed("a stored block ends early")
                length = data[bits.pos] | data[bits.pos + 1] << 8
                check = data[bits.pos + 2] | data[bits.pos + 3] << 8
                if length != (~check & 0xFFFF):
                    raise Malformed("a stored block's length does not check")
                bits.pos += 4
                if bits.pos + length > len(data):
                    raise Malformed("a stored block ends early")
                out += data[bits.pos : bits.pos + length]
                bits.pos += length
                if len(out) > limit:
                    raise Malformed("the output passes the limit")
            elif kind == 1:
                codes(bits, out, *fixed_tables(), limit)
            elif kind == 2:
                codes(bits, out, *dynamic_tables(bits), limit)
            else:
                raise Malformed("block type 3")
            if last:
                return bytes(out)
    except (Malformed, IndexError):
        return None
