"""Persistent Linux UART host. No serial port is opened without exact authorization."""
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import time

from uart_wire import ACK, CLAIM, FRAME, HELLO, RELEASE, RESET, VIEW, Message, Parser, encode, payload_words, words_payload


class LinkFault(RuntimeError):
    pass


class EvidenceLog:
    """One binary append-only file and bounded-record JSON index, both exclusive-create."""
    def __init__(self, directory, origin):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        self.binary = (directory/'wire.bin').open('xb')
        self.index = (directory/'events.jsonl').open('x', encoding='utf-8')
        self.origin = origin
        self.seq = 0

    def record(self, kind, data=b'', **fields):
        offset = self.binary.tell()
        self.binary.write(data)
        self.binary.flush()
        row = dict(sequence=self.seq, monotonic_ns=time.monotonic_ns(), kind=kind,
                   origin=self.origin, offset=offset, length=len(data), sha256=hashlib.sha256(data).hexdigest(), **fields)
        self.index.write(json.dumps(row, sort_keys=True)+'\n')
        self.index.flush()
        self.seq += 1

    def close(self):
        for stream in (self.binary, self.index):
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()


def identify_devices(sysroot='/sys', devroot='/dev'):
    """Read-only enumeration: no tty file open, no probe bytes, no first-match selection."""
    result = []
    devroot, sysroot = Path(devroot), Path(sysroot)
    aliases = {}
    for path in (devroot/'serial/by-id').glob('*'):
        aliases.setdefault(str(path.resolve()), []).append(str(path))
    for entry in (sysroot/'class/tty').glob('ttyUSB*'):
        physical = (entry/'device').resolve()
        usb = next((p for p in [physical, *physical.parents] if (p/'idVendor').is_file()), None)
        if usb is None:
            continue
        read = lambda name: (usb/name).read_text().strip() if (usb/name).is_file() else None
        device = str(devroot/entry.name)
        result.append(dict(device=device, by_id=sorted(aliases.get(device, [])), physical_path=str(physical),
                           vid=read('idVendor'), pid=read('idProduct'), usb_serial=read('serial')))
    return result


def select_device(identity, devices=None):
    devices = identify_devices() if devices is None else devices
    required = ('vid', 'pid', 'physical_path')
    if any(not identity.get(k) for k in required):
        raise LinkFault('explicit VID/PID/physical topology required')
    matches = [d for d in devices if all(d[k] == identity[k] for k in required)
               and (not identity.get('by_id') or identity['by_id'] in d['by_id'])]
    if len(matches) != 1:
        raise LinkFault('device identity is absent or ambiguous')
    return matches[0]


class LinuxPort:
    """2M/1M 8N1, raw nonblocking fd with exclusive kernel+flock ownership."""
    def __init__(self, fd, evidence):
        self.fd, self.evidence = fd, evidence

    @classmethod
    def open_approved(cls, identity, baud, approval, receipt, evidence):
        import fcntl
        import termios
        if baud not in (1000000, 2000000):
            raise LinkFault('unsupported baud')
        auth = json.loads(Path(approval).read_text(encoding='utf-8'))
        loaded = json.loads(Path(receipt).read_text(encoding='utf-8'))
        if (auth.get('status') != 'APPROVED_EXACT_ARTIFACT' or auth.get('uart_data_test_authorized') is not True
                or auth.get('bit_sha256') != loaded.get('bitstream_sha256')
                or loaded.get('programming_status') != 'PASS' or auth.get('uart_identity') != identity
                or auth.get('uart_baud') != baud):
            raise LinkFault('exact UART test authority / load identity missing')
        device = select_device(identity)
        fd = os.open(device['device'], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.ioctl(fd, termios.TIOCEXCL)
            attrs = termios.tcgetattr(fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
            attrs[4] = attrs[5] = getattr(termios, 'B'+str(baud))
            attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            # No implicit flush: residual bytes are logged and parsed, never hidden.
            evidence.record('OPEN', identity=device, baud=baud, actual_termios=termios.tcgetattr(fd))
        except BaseException:
            os.close(fd)
            raise
        return cls(fd, evidence)

    def write(self, data, deadline):
        offset = 0
        while offset != len(data):
            remain = deadline-time.monotonic()
            if remain <= 0:
                raise TimeoutError('UART write deadline')
            if select.select([], [self.fd], [], remain)[1]:
                try:
                    count = os.write(self.fd, data[offset:])
                except BlockingIOError:
                    continue
                if count <= 0:
                    raise LinkFault('UART write closed')
                self.evidence.record('TX', data[offset:offset+count])
                offset += count

    def read(self, deadline):
        remain = deadline-time.monotonic()
        if remain <= 0 or not select.select([self.fd], [], [], remain)[0]:
            raise TimeoutError('UART response deadline')
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return b''
        if not data:
            raise LinkFault('UART EOF/disconnected')
        self.evidence.record('RX', data)
        return data

    def close(self):
        if self.fd is not None:
            self.evidence.record('CLOSE')
            os.close(self.fd)
            self.fd = None


class Client:
    """Explicit sessions and resets; validate a snapshot before explicit ACK."""
    def __init__(self, port, session, timeout=0.5, retries=1):
        if type(session) is not int or not 1 <= session <= 0xFFFFFFFF or not 0 <= retries <= 2:
            raise ValueError('nonzero session, retries <=2 required')
        self.port, self.session, self.timeout, self.retries = port, session, timeout, retries
        self.parser = Parser()
        self.generation = self.next_frame = None
        self.pending = None
        self.fault = None

    def exchange(self, request, *, retry=True, generation_change=False):
        wire = encode(request)
        for attempt in range(1+(self.retries if retry else 0)):
            deadline = time.monotonic()+self.timeout
            self.port.evidence.record('REQUEST', wire, opcode=request.opcode, attempt=attempt)
            self.port.write(wire, deadline)
            try:
                while True:
                    for reply in self.parser.feed(self.port.read(deadline)):
                        if reply.opcode == 0xFF:
                            raise LinkFault('endpoint rejected corrupt/untrusted request')
                        if (reply.opcode != request.opcode | 0x80 or reply.session != request.session
                                or reply.frame != request.frame or reply.view != request.view
                                or (not generation_change and reply.generation != request.generation)):
                            self.port.evidence.record('STALE_RESPONSE', encode(reply))
                            continue
                        words = payload_words(reply.payload)
                        if not words or words[0] != 0:
                            raise LinkFault('endpoint status '+repr(words))
                        self.port.evidence.record('RESPONSE_VALIDATED', encode(reply), attempt=attempt)
                        return reply, words[1:]
            except TimeoutError:
                self.parser.abandon_partial()
                if attempt == (self.retries if retry else 0):
                    self.fault = 'UNCERTAIN_REQUEST_COMPLETION'
                    raise
        raise AssertionError('unreachable')

    def hello(self):
        reply, values = self.exchange(Message(HELLO), generation_change=True)
        if len(values) != 13 or values[:4] != [0xF1081C01, 0xF1080001, 0xF1070001, 50000000] or values[5:8] != [530, 59, 2124]:
            raise LinkFault('capability mismatch')
        names = ('capability', 'version', 'inner_version', 'clock_hz', 'baud', 'full_words', 'minimal_words',
                 'max_payload', 'generation', 'next_frame', 'active_session', 'flags', 'uart_errors')
        capabilities = dict(zip(names, values))
        if reply.generation != capabilities['generation']:
            raise LinkFault('capability generation mismatch')
        return capabilities

    def claim(self):
        info = self.hello()
        if info['active_session'] not in (0, self.session):
            raise LinkFault('another session owns core')
        self.exchange(Message(CLAIM, session=self.session, generation=info['generation']))
        self.generation, self.next_frame = info['generation'], info['next_frame']
        # Pending cannot be implicitly reused after host restart.
        if info['flags'] & 1:
            self.fault = 'RECOVERY_REQUIRED_PENDING_RESULT'
        return info

    def reset(self):
        if self.generation is None:
            raise LinkFault('claim first')
        old = self.generation
        reply, values = self.exchange(Message(RESET, session=self.session, generation=old,
                                            payload=words_payload([0xC0DEF00D])), retry=False, generation_change=True)
        if values != [reply.generation] or reply.generation != (old+1) & 0xFFFFFFFF:
            self.fault = 'RESET_IDENTITY_UNCERTAIN'
            raise LinkFault(self.fault)
        self.generation, self.next_frame, self.pending, self.fault = reply.generation, 0, None, None
        return self.generation

    def frame(self, packet, view=1):
        if self.fault or self.pending is not None or self.generation is None:
            raise LinkFault('fault/pending/unclaimed')
        from packed10 import decode_packet
        decode_packet(packet, expected_generation=self.generation, expected_frame=self.next_frame)
        request = Message(FRAME, view, self.session, self.generation, self.next_frame, words_payload(packet))
        try:
            reply, words = self.exchange(request)
            result = validate_snapshot(words, view, self.generation, self.next_frame, packet)
        except BaseException:
            self.fault = 'FRAME_OUTPUT_INVALID_OR_UNCERTAIN'
            raise
        self.pending = (self.generation, self.next_frame, tuple(packet), result)
        return result

    def view(self, frame, view=0):
        if self.generation is None:
            raise LinkFault('unclaimed')
        _, words = self.exchange(Message(VIEW, view, self.session, self.generation, frame))
        return words

    def ack(self):
        if self.pending is None:
            raise LinkFault('no verified result to acknowledge')
        generation, frame, _, _ = self.pending
        _, words = self.exchange(Message(ACK, session=self.session, generation=generation, frame=frame))
        if words:
            raise LinkFault('unexpected ACK data')
        self.pending = None
        self.next_frame += 1

    def release(self):
        if self.pending or self.fault:
            raise LinkFault('pending/fault requires explicit recovery, not release')
        self.exchange(Message(RELEASE, session=self.session, generation=self.generation or 0))
        self.generation = self.next_frame = None


def validate_snapshot(words, view, generation, frame, packet):
    expected_words = 530 if view == 0 else 59
    if len(words) != expected_words:
        raise LinkFault('snapshot length mismatch')
    tail = words[471:] if view == 0 else words
    keys = ('completed_id', 'acc_sat', 'state_sat', 'overflow', 'drop', 'cycles', 'status', 'hardware_generation',
            'snapshot_valid', 'version', 'error_status', 'accepted_events', 'request_id', 'accepted_request_crc32',
            'request_generation', 'packet_words', 'hardware_commits', 'replays', 'rejects', 'timeouts', 'phase',
            'capacity', 'queue_capacity', 'snapshot_word_count', 'stamp', 'decode_cycles', 'protocol_cycles')
    result = dict(zip(keys, tail[32:]))
    checks = {'completed_id': frame, 'hardware_generation': generation, 'snapshot_valid': 1, 'version': 0xF1070001,
              'error_status': 0, 'overflow': 0, 'drop': 0, 'accepted_events': packet[4], 'request_id': frame,
              'accepted_request_crc32': packet[7], 'request_generation': generation, 'packet_words': len(packet),
              'hardware_commits': frame+1, 'phase': 6, 'capacity': 942, 'queue_capacity': 0x20002,
              'snapshot_word_count': 530, 'stamp': 0xF107A11D}
    if any(result[k] != value for k, value in checks.items()) or result['status'] & 0x1EF != 0x46:
        raise LinkFault('snapshot accepted identity/diagnostics mismatch')
    if not 0 < result['cycles'] <= 500000 or not packet[4] <= result['decode_cycles'] <= 2*packet[4] or result['protocol_cycles'] <= result['decode_cycles']:
        raise LinkFault('snapshot cycle counter mismatch')
    states = [value-(1 << 32) if value >= 1 << 31 else value for value in words[:471]] if view == 0 else []
    if any(not -131072 <= value <= 131071 for value in states):
        raise LinkFault('state outside S18')
    return dict(result, states=states, counts=tail[:32], words=list(words), read_words=len(words))
