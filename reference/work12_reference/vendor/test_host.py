"""Software/PTY tests only: no real UART opens, no hardware/science PASS claim."""
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
import time
import unittest
import zlib

from packed10 import make_packet
from uart_wire import *
from uart_host import Client, EvidenceLog, LinkFault, LinuxPort, select_device, validate_snapshot


def independent_raw(message):
    values = [0xF8, 1, message.opcode, message.view]
    body = bytes(values)
    for value in (message.session, message.generation, message.frame):
        body += value.to_bytes(4, 'little')
    body += len(message.payload).to_bytes(2, 'little') + b'\0\0' + message.payload
    crc = 0xFFFFFFFF
    for value in body:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return body + (crc ^ 0xFFFFFFFF).to_bytes(4, 'little')


def snapshot(packet, full=True):
    count = packet[4]
    tail = [0]*32 + [packet[3], 0, 0, 0, 0, 3000, 0x46, packet[2], 1,
                     0xF1070001, 0, count, packet[3], packet[7], packet[2], len(packet),
                     packet[3]+1, 0, 0, 0, 6, 942, 0x20002, 530, 0xF107A11D, count*2, count*2+100]
    return [0]*471+tail if full else tail


class NullLog:
    def __init__(self):
        self.records = []
    def record(self, kind, data=b'', **fields):
        self.records.append((kind, data, fields))


class MockPort:
    """Transport state emulator, explicitly not neural or RTL evidence."""
    def __init__(self):
        self.evidence = NullLog()
        self.parser = Parser()
        self.responses = bytearray()
        self.generation, self.owner, self.next_frame = 0, 0, 0
        self.packet = None
        self.commits = self.resets = self.acks = 0
        self.drop_once = None
        self.alter_reply = None

    def reply(self, request, words, generation=None):
        if self.drop_once == request.opcode:
            self.drop_once = None
            return
        reply = Message(request.opcode | 0x80, request.view, request.session,
                        request.generation if generation is None else generation, request.frame, words_payload([0]+words))
        if self.alter_reply:
            reply = self.alter_reply(reply)
        self.responses.extend(encode(reply))

    def write(self, data, deadline):
        self.evidence.record('TX', data)
        for request in self.parser.feed(data):
            if request.opcode == HELLO:
                self.reply(request, [0xF1081C01, 0xF1080001, 0xF1070001, 50000000, 2000000,
                                    530, 59, 2124, self.generation, self.next_frame, self.owner,
                                    int(self.packet is not None), 0], self.generation)
            elif request.opcode == CLAIM:
                if self.owner not in (0, request.session):
                    raise LinkFault('busy owner')
                self.owner = request.session
                self.reply(request, [])
            elif request.opcode == RESET:
                self.generation += 1
                self.next_frame = 0
                self.packet = None
                self.resets += 1
                self.reply(request, [self.generation], self.generation)
            elif request.opcode == FRAME:
                packet = payload_words(request.payload)
                if self.packet is None:
                    self.packet = packet
                    self.commits += 1
                elif self.packet != packet:
                    raise LinkFault('conflict')
                self.reply(request, snapshot(packet, request.view == 0))
            elif request.opcode == VIEW:
                self.reply(request, snapshot(self.packet, request.view == 0))
            elif request.opcode == ACK:
                if self.packet is not None:
                    self.packet = None
                    self.next_frame += 1
                    self.acks += 1
                self.reply(request, [])
            elif request.opcode == RELEASE:
                self.owner = 0
                self.reply(request, [])

    def read(self, deadline):
        if not self.responses:
            raise TimeoutError('mock deadline')
        data = bytes(self.responses[:7])
        del self.responses[:7]
        self.evidence.record('RX', data)
        return data


class Tests(unittest.TestCase):
    def test_all_lengths_and_escape(self):
        rng = random.Random(108)
        for size in range(MAX_PAYLOAD+1):
            message = Message(4, size % 2, 0x7D7E7D7E, 0x12345678, size,
                              bytes(rng.randrange(256) for _ in range(size)))
            self.assertEqual(raw_encode(message), independent_raw(message))
            wire = encode(message)
            self.assertLessEqual(len(wire), MAX_WIRE)
            parser = Parser()
            actual = []
            for start in range(0, len(wire), 17):
                actual.extend(parser.feed(wire[start:start+17]))
            self.assertEqual(actual, [message])
            self.assertEqual(parser.errors, 0)

    def test_corrupt_resync(self):
        good = encode(Message(HELLO))
        raw = raw_encode(Message(FRAME, payload=b'a'*16))
        malformed = [b'\x7E\x7D\x7E', b'\x7E\x7D\x01\x7E',
                     b'\x7E'+b'A'*5000+b'\x7E', b'\x7E'+raw[:-1]+bytes([raw[-1]^1])+b'\x7E',
                     b'\x7E'+raw[:16]+b'\xFF\xFF'+raw[18:]+b'\x7E',
                     b'\x7E'+raw[:18]+b'\x01\x00'+raw[20:]+b'\x7E']
        for bad in malformed:
            parser = Parser()
            self.assertEqual(parser.feed(b'garbage'+bad+good), [Message(HELLO)])
            self.assertGreater(parser.errors, 0)
            self.assertLessEqual(len(parser.buffer), MAX_RAW)

    def test_partial_abandon(self):
        parser = Parser()
        parser.feed(encode(Message(FRAME, payload=b'abc'))[:15])
        parser.abandon_partial()
        self.assertEqual(parser.feed(encode(Message(HELLO))), [Message(HELLO)])

    def test_garbage_after_closed_packet_ignored(self):
        parser = Parser()
        first = Message(HELLO)
        second = Message(CLAIM, session=1)
        self.assertEqual(parser.feed(encode(first)+b'garbage'+encode(second)), [first, second])
        self.assertEqual(parser.errors, 0)

    def test_independent_raw_replay(self):
        from verify_wire_log import verify
        with tempfile.TemporaryDirectory() as directory:
            logdir = Path(directory)/'wire'
            port = MockPort()
            port.evidence = EvidenceLog(logdir, 'MOCK_ONLY')
            client = Client(port, 108)
            client.claim()
            client.reset()
            client.frame(make_packet(client.generation, 0, [0, 470, 512, 982]), 0)
            client.ack()
            client.release()
            port.evidence.close()
            result = verify(logdir)
            self.assertEqual(result['unique_successful_frames'], 1)
            self.assertEqual(result['successful_ack_responses'], 1)

    def test_full_min_and_ack(self):
        port = MockPort()
        client = Client(port, 123)
        client.claim()
        client.reset()
        packet = make_packet(client.generation, 0, [0, 470, 512, 982])
        full = client.frame(packet, 0)
        self.assertEqual(full['read_words'], 530)
        minimal = client.view(0, 1)
        self.assertEqual(minimal, full['words'][471:])
        with self.assertRaises(LinkFault):
            client.frame(make_packet(client.generation, 1, []))
        client.ack()
        self.assertEqual((port.commits, port.acks), (1, 1))
        client.release()
        self.assertEqual(port.owner, 0)

    def test_lost_frame_and_ack_response_exact_retry(self):
        port = MockPort()
        client = Client(port, 123)
        client.claim()
        client.reset()
        port.drop_once = FRAME
        client.frame(make_packet(client.generation, 0, [1, 513]))
        port.drop_once = ACK
        client.ack()
        self.assertEqual((port.commits, port.acks), (1, 1))
        attempts = [record for record in port.evidence.records if record[0] == 'REQUEST' and record[2]['attempt'] == 1]
        self.assertEqual(len(attempts), 2)

    def test_reset_lost_not_repeated(self):
        port = MockPort()
        client = Client(port, 123)
        client.claim()
        port.drop_once = RESET
        with self.assertRaises(TimeoutError):
            client.reset()
        self.assertEqual(port.resets, 1)
        self.assertTrue(client.fault)

    def test_host_restart_pending_requires_recovery(self):
        port = MockPort()
        client = Client(port, 123)
        client.claim()
        client.reset()
        client.frame(make_packet(client.generation, 0, []))
        restarted = Client(port, 123)
        info = restarted.claim()
        self.assertEqual(info['flags'], 1)
        with self.assertRaises(LinkFault):
            restarted.frame(make_packet(restarted.generation, 0, []))
        foreign = Client(port, 456)
        with self.assertRaises(LinkFault):
            foreign.claim()

    def test_invalid_snapshot(self):
        packet = make_packet(1, 0, [0, 512])
        for index in [503, *range(506, 520), 524, 525, 526, 527, 528, 529]:
            words = snapshot(packet)
            words[index] = 0 if index == 529 else words[index] ^ (4 if index == 509 else 0x10000000)
            with self.assertRaises(LinkFault, msg=str(index)):
                validate_snapshot(words, 0, 1, 0, packet)

    def test_device_no_first_match(self):
        identity = dict(vid='1a86', pid='7523', physical_path='/sys/device/exact')
        item = dict(identity, device='/dev/ttyUSB9', by_id=['/dev/serial/by-id/specific'])
        self.assertEqual(select_device(identity, [item]), item)
        with self.assertRaises(LinkFault):
            select_device(identity, [item, item])
        with self.assertRaises(LinkFault):
            select_device(dict(vid='1a86', pid='7523'), [item])

    def test_no_authority_never_opens(self):
        if os.name != 'posix':
            self.skipTest('Linux-only import')
        with tempfile.TemporaryDirectory() as directory:
            approval, receipt = Path(directory)/'approval.json', Path(directory)/'receipt.json'
            approval.write_text('{}')
            receipt.write_text('{}')
            with self.assertRaises(LinkFault):
                LinuxPort.open_approved({}, 2000000, approval, receipt, NullLog())

    def test_binary_log_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            logdir = Path(directory)/'log'
            log = EvidenceLog(logdir, 'MOCK_ONLY')
            log.record('TX', b'\x00\x7E\x7D')
            log.record('RX', b'\xF8\x00')
            log.close()
            binary = (logdir/'wire.bin').read_bytes()
            for row in map(json.loads, (logdir/'events.jsonl').read_text().splitlines()):
                data = binary[row['offset']:row['offset']+row['length']]
                self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])

    @unittest.skipUnless(os.name == 'posix', 'actual Linux PTY only')
    def test_linux_pty_fragment_and_disconnect(self):
        import pty
        import termios
        import threading
        master, slave = pty.openpty()
        attrs = termios.tcgetattr(slave)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        os.set_blocking(slave, False)
        log = NullLog()
        port = LinuxPort(slave, log)  # PTY only; bypass real-device approval by explicit fd.
        emulator = MockPort()
        errors = []
        stopped = threading.Event()
        def peer():
            try:
                while not stopped.is_set():
                    import select
                    if not select.select([master], [], [], 0.02)[0]:
                        continue
                    data = os.read(master, 23)
                    emulator.write(data, time.monotonic()+1)
                    while emulator.responses:
                        os.write(master, emulator.read(time.monotonic()+1))
            except OSError:
                if not stopped.is_set():
                    errors.append('unexpected peer error')
        thread = threading.Thread(target=peer)
        thread.start()
        try:
            client = Client(port, 0x7D7E7D7E, timeout=1)
            client.claim()
            client.reset()
            client.frame(make_packet(client.generation, 0, [0, 470, 512, 982]), 0)
            self.assertEqual(len(client.view(0)), 530)
            client.ack()
            client.release()
            self.assertEqual((emulator.commits, emulator.acks), (1, 1))
        finally:
            stopped.set()
            thread.join(timeout=2)
            os.close(master)
            port.close()
        self.assertFalse(errors)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any(record[0] == 'RX' for record in log.records))


if __name__ == '__main__':
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    identity = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    report = dict(origin='MOCK_ONLY_NOT_HARDWARE_NOT_NEURAL', tests=result.testsRun,
                  failures=[str(x[0])+': '+x[1] for x in result.failures],
                  errors=[str(x[0])+': '+x[1] for x in result.errors],
                  skipped=[str(x[0])+': '+x[1] for x in result.skipped],
                  linux_pty_executed=os.name == 'posix', source_sha256=identity,
                  status='PASS' if result.wasSuccessful() else 'FAIL')
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
    print(json.dumps(report, sort_keys=True))
    sys.exit(0 if result.wasSuccessful() else 1)
