"""Fixed O7 PACKED10: no deduplication, adaptation, or scientific transforms."""
import struct
import zlib

MAGIC = 0xF107C001
VERSION = 0xF1070001
SEAL = 0xF107C0DE
PACKED10_FLAG = 0x10000
MAX_EVENTS = 942


def uint32(value, name):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(name + " must be uint32")
    return value


def validate_events(events):
    events = list(events)
    if len(events) > MAX_EVENTS:
        raise ValueError("event capacity exceeded")
    previous = -1
    for value in events:
        if type(value) is not int or not (0 <= value <= 470 or 512 <= value <= 982):
            raise ValueError("invalid event index or type")
        if value <= previous:
            raise ValueError("events must be stimulus ascending then noise ascending, without duplicates")
        previous = value
    return events


def payload_word_count(count):
    if type(count) is not int or not 0 <= count <= MAX_EVENTS:
        raise ValueError("invalid event count")
    return (10 * count + 31) // 32


def pack10(events):
    events = validate_events(events)  # Reject before bit packing; never deduplicate.
    words = []
    accumulator = bits = 0
    for event in events:
        accumulator |= event << bits
        bits += 10
        if bits >= 32:
            words.append(accumulator & 0xFFFFFFFF)
            accumulator >>= 32
            bits -= 32
    if bits:
        words.append(accumulator)
    return words


def unpack10(words, count):
    words = list(words)
    if len(words) != payload_word_count(count):
        raise ValueError("payload length does not match count")
    for value in words:
        uint32(value, "payload word")
    used = (10 * count) % 32
    if words and used and words[-1] >> used:
        raise ValueError("nonzero high padding")
    accumulator = bits = index = 0
    events = []
    for _ in range(count):
        while bits < 10:
            accumulator |= words[index] << bits
            index += 1
            bits += 32
        events.append(accumulator & 0x3FF)
        accumulator >>= 10
        bits -= 10
    return validate_events(events)


def request_crc(header, payload):
    values = list(header) + list(payload)
    for value in values:
        uint32(value, "CRC input word")
    return zlib.crc32(struct.pack("<" + str(len(values)) + "I", *values))


def make_packet(generation, frame, events, dn_enable=1):
    uint32(generation, "generation")
    uint32(frame, "frame")
    if type(dn_enable) is not int or dn_enable not in (0, 1):
        raise ValueError("DN enable must be 0 or 1")
    events = validate_events(events)
    payload = pack10(events)
    header = [MAGIC, VERSION, generation, frame, len(events), PACKED10_FLAG | dn_enable, frame]
    return header + [request_crc(header, payload)] + payload + [SEAL]


def decode_packet(words, *, expected_generation=None, expected_frame=None):
    words = list(words)
    for value in words:
        uint32(value, "packet word")
    if len(words) < 9 or words[0] != MAGIC or words[1] != VERSION or words[-1] != SEAL:
        raise ValueError("invalid O7 magic/version/seal")
    count = words[4]
    if len(words) != 9 + payload_word_count(count):
        raise ValueError("packet length mismatch")
    if words[5] not in (PACKED10_FLAG, PACKED10_FLAG | 1) or words[6] != words[3]:
        raise ValueError("encoding flags/request ID mismatch")
    if expected_generation is not None and words[2] != uint32(expected_generation, "expected generation"):
        raise ValueError("generation mismatch")
    if expected_frame is not None and words[3] != uint32(expected_frame, "expected frame"):
        raise ValueError("frame mismatch")
    if request_crc(words[:7], words[8:-1]) != words[7]:
        raise ValueError("CRC mismatch")
    return {"generation": words[2], "frame": words[3], "dn_enable": words[5] & 1,
            "events": unpack10(words[8:-1], count), "crc32": words[7], "packet_words": len(words)}
