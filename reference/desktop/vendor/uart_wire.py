"""O8 byte protocol. Standard library only; contains no device operations."""
from dataclasses import dataclass
import struct
import zlib

DELIM, ESC = 0x7E, 0x7D
MAX_PAYLOAD = 2124
MAX_RAW = 2148
MAX_WIRE = 4298
HEADER = struct.Struct('<4BIIIHH')
HELLO, CLAIM, RESET, FRAME, VIEW, ACK, RELEASE = range(1, 8)


def uint(value, bits):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError('unsigned integer required')
    return value


@dataclass(frozen=True)
class Message:
    opcode: int
    view: int = 0
    session: int = 0
    generation: int = 0
    frame: int = 0
    payload: bytes = b''


def raw_encode(message):
    for field, bits in ((message.opcode, 8), (message.view, 8), (message.session, 32),
                        (message.generation, 32), (message.frame, 32)):
        uint(field, bits)
    if message.view not in (0, 1) or type(message.payload) is not bytes or len(message.payload) > MAX_PAYLOAD:
        raise ValueError('invalid view or payload')
    body = HEADER.pack(0xF8, 1, message.opcode, message.view, message.session,
                       message.generation, message.frame, len(message.payload), 0) + message.payload
    return body + struct.pack('<I', zlib.crc32(body))


def encode(message):
    escaped = bytearray([DELIM])
    for value in raw_encode(message):
        if value in (DELIM, ESC):
            escaped.extend((ESC, value ^ 0x20))
        else:
            escaped.append(value)
    escaped.append(DELIM)
    return bytes(escaped)


def decode_raw(raw):
    if not 24 <= len(raw) <= MAX_RAW:
        raise ValueError('raw length outside bound')
    magic, version, opcode, view, session, generation, frame, length, reserved = HEADER.unpack_from(raw)
    if magic != 0xF8 or version != 1 or view not in (0, 1) or reserved or length > MAX_PAYLOAD or len(raw) != 24 + length:
        raise ValueError('header or declared length invalid')
    if zlib.crc32(raw[:-4]) != struct.unpack_from('<I', raw, len(raw)-4)[0]:
        raise ValueError('outer CRC mismatch')
    return Message(opcode, view, session, generation, frame, raw[20:-4])


class Parser:
    """Bounded storage, strict escapes, delimiter resync; errors never yield messages."""
    def __init__(self):
        self.buffer = bytearray()
        self.started = self.escaped = self.invalid = False
        self.errors = 0

    def feed(self, data):
        messages = []
        for value in data:
            if value == DELIM:
                closed = bool(self.started and (self.buffer or self.escaped or self.invalid))
                if closed:
                    try:
                        if self.escaped or self.invalid:
                            raise ValueError('escape/overflow')
                        messages.append(decode_raw(bytes(self.buffer)))
                    except ValueError:
                        self.errors += 1
                self.buffer.clear()
                self.started, self.escaped, self.invalid = not closed, False, False
                continue
            if not self.started or self.invalid:
                continue
            if self.escaped:
                if value not in (DELIM ^ 0x20, ESC ^ 0x20):
                    self.invalid = True
                    continue
                self.buffer.append(value ^ 0x20)
                self.escaped = False
            elif value == ESC:
                self.escaped = True
            else:
                self.buffer.append(value)
            if len(self.buffer) > MAX_RAW:
                self.buffer.clear()
                self.invalid = True
        return messages

    def abandon_partial(self):
        """Deadline/break cleanup: discard partial only; no scientific reset."""
        self.buffer.clear()
        self.started = self.escaped = self.invalid = False


def words_payload(words):
    values = [uint(v, 32) for v in words]
    return struct.pack('<' + str(len(values)) + 'I', *values)


def payload_words(payload):
    if len(payload) % 4:
        raise ValueError('word payload not aligned')
    return list(struct.unpack('<' + str(len(payload)//4) + 'I', payload))
