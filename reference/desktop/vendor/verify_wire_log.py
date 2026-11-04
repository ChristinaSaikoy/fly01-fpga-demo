"""Independent raw UART evidence parser, no production codec import, no devices."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib


def _parse_separate_frames(stream):
    messages = []
    spans = []
    opened = False
    current = bytearray()
    for value in stream:
        if value == 0x7E:
            if opened and current:
                spans.append(bytes(current))
                current.clear()
                opened = False
            else:
                opened = True
        elif opened:
            current.append(value)
    for span in spans:
        raw = bytearray()
        escaped = False
        invalid = False
        for byte in span:
            if escaped:
                if byte not in (0x5E, 0x5D):
                    invalid = True
                    break
                raw.append(byte ^ 0x20)
                escaped = False
            elif byte == 0x7D:
                escaped = True
            else:
                raw.append(byte)
            if len(raw) > 2148:
                invalid = True
                break
        if invalid or escaped or len(raw) < 24:
            messages.append(dict(valid=False, reason='escape/length/overflow'))
            continue
        magic, version, opcode, view = raw[:4]
        session, generation, frame, length, reserved = struct.unpack_from('<IIIHH', raw, 4)
        crc = struct.unpack_from('<I', raw, len(raw)-4)[0]
        if (magic, version) != (0xF8, 1) or view not in (0, 1) or reserved or length > 2124 or length+24 != len(raw) or crc != zlib.crc32(raw[:-4]):
            messages.append(dict(valid=False, reason='header/CRC'))
            continue
        messages.append(dict(valid=True, opcode=opcode, view=view, session=session,
                             generation=generation, frame=frame, payload=bytes(raw[20:-4])))
    return messages


def parse(stream):
    """Recover after an invalid/truncated span, never accept it as a result.

    A delimiter after INVALID bytes may also start the next complete frame.
    Valid-frame termination still requires a separate following start delimiter.
    Every recovered frame goes through the unchanged strict CRC/header/size gates.
    This models raw-stream resynchronization; no RESPONSE_VALIDATED data is used.
    """
    messages = []
    opened = False
    current = bytearray()
    for value in stream:
        if value == 0x7E:
            if opened and current:
                checked = _parse_separate_frames(b'\x7e' + bytes(current) + b'\x7e')
                if len(checked) != 1:
                    raise RuntimeError('independent span decoder internal count')
                messages.extend(checked)
                current.clear()
                opened = not checked[0]['valid']
            else:
                opened = True
        elif opened:
            current.append(value)
    return messages


def verify(directory, include_data=False):
    directory = Path(directory)
    binary = (directory/'wire.bin').read_bytes()
    events = [json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    tx = bytearray()
    rx = bytearray()
    offset = 0
    previous_time = -1
    for sequence, row in enumerate(events):
        if row['sequence'] != sequence or row['offset'] != offset or row['monotonic_ns'] < previous_time:
            raise RuntimeError('record ordering/offset/clock')
        data = binary[offset:offset+row['length']]
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise RuntimeError('raw record hash mismatch')
        offset += row['length']
        previous_time = row['monotonic_ns']
        if row['kind'] == 'TX':
            tx.extend(data)
        elif row['kind'] == 'RX':
            rx.extend(data)
    if offset != len(binary):
        raise RuntimeError('unindexed trailing bytes')
    sent, received = parse(bytes(tx)), parse(bytes(rx))
    accepted = {}
    requests = {}
    frames = 0
    acks = 0
    raw_frames = {}
    for message in sent:
        if not message['valid']:
            continue
        key = (message['opcode'], message['view'], message['session'], message['generation'], message['frame'])
        # RESET appears once only; FRAME exact retry must preserve bytes per ID.
        if message['opcode'] == 4:
            identity = key[2:]
            if identity in requests and requests[identity] != message['payload']:
                # Intentional negative conflict is not an accepted new frame.
                continue
            requests[identity] = message['payload']
    for message in received:
        if not message['valid'] or len(message['payload']) < 4:
            continue
        status = int.from_bytes(message['payload'][:4], 'little')
        if message['opcode'] in (0x84, 0x85) and status == 0:
            count = 530 if message['view'] == 0 else 59
            if len(message['payload']) != 4+4*count:
                raise RuntimeError('successful snapshot truncated')
            words = list(struct.unpack('<'+str(count)+'I', message['payload'][4:]))
            tail = words[471:] if count == 530 else words
            if (tail[32], tail[39], tail[40], tail[41], tail[55], tail[56]) != (message['frame'], message['generation'], 1, 0xF1070001, 530, 0xF107A11D):
                raise RuntimeError('raw snapshot identity invalid')
            if (tail[35] or tail[36] or tail[42] or not 0 < tail[37] <= 500000 or
                    tail[38] & 0x1EF != 0x46 or tail[44] != message['frame'] or
                    tail[46] != message['generation'] or tail[48] != message['frame']+1 or
                    tail[52:55] != [6, 942, 0x20002] or
                    not tail[43] <= tail[57] <= 2*tail[43] or tail[58] <= tail[57]):
                raise RuntimeError('raw snapshot error/drop/cycles/commit/diagnostics invalid')
            identity = (message['session'], message['generation'], message['frame'])
            if message['opcode'] == 0x84:
                packet = requests.get(identity)
                if packet is None or len(packet) < 36 or len(packet) % 4:
                    raise RuntimeError('result without recorded request')
                inner = list(struct.unpack('<'+str(len(packet)//4)+'I', packet))
                n = inner[4]
                if len(inner) != 9+(10*n+31)//32 or not 0 <= n <= 942:
                    raise RuntimeError('inner event count')
                if inner[:4] != [0xF107C001, 0xF1070001, message['generation'], message['frame']] or inner[-1] != 0xF107C0DE:
                    raise RuntimeError('inner identity')
                if (zlib.crc32(packet[:28]+packet[32:-4]) != inner[7] or tail[45] != inner[7] or tail[43] != n or
                        inner[5] not in (0x10000, 0x10001) or inner[6] != message['frame'] or tail[47] != len(inner)):
                    raise RuntimeError('inner CRC/accept identity')
                packed = int.from_bytes(packet[32:-4], 'little')
                events_local = [(packed >> (10*i)) & 1023 for i in range(n)]
                if packed >> (10*n) or any(not (0<=x<=470 or 512<=x<=982) for x in events_local) or events_local != sorted(set(events_local)):
                    raise RuntimeError('inner lossless canonical order/padding')
                if identity not in accepted:
                    accepted[identity] = (tuple(tail), tuple(events_local))
                    raw_frames[identity] = dict(snapshot_words=words, events=events_local,
                                                accepted_request_crc32=inner[7])
                    frames += 1
                elif accepted[identity] != (tuple(tail), tuple(events_local)):
                    raise RuntimeError('retry mutated accepted result')
            else:
                if identity not in accepted or accepted[identity][0] != tuple(tail):
                    raise RuntimeError('VIEW does not match actual cached result')
                original = raw_frames[identity]['snapshot_words']
                if count == 530 and len(original) == 530 and words != original:
                    raise RuntimeError('full VIEW mutated cached states')
        elif message['opcode'] == 0x86 and status == 0:
            acks += 1
    result = dict(status='PASS', origin='INDEPENDENT_BYTE_REPLAY_NOT_CONTROLLER_ACCEPTANCE',
                records=len(events), tx_bytes=len(tx), rx_bytes=len(rx),
                tx_messages=len(sent), rx_messages=len(received), unique_successful_frames=frames,
                successful_ack_responses=acks, invalid_tx_messages=sum(not x['valid'] for x in sent),
                invalid_rx_messages=sum(not x['valid'] for x in received))
    return (result, raw_frames) if include_data else result


def records(directory):
    """Call after verify: exposes actual record boundaries for phase/timestamp review."""
    directory = Path(directory)
    binary = (directory/'wire.bin').read_bytes()
    rows = [json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    return [(row, binary[row['offset']:row['offset']+row['length']]) for row in rows]


if __name__ == '__main__':
    print(json.dumps(verify(sys.argv[1]), sort_keys=True))
