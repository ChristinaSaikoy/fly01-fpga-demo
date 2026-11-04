"""WORK18 I2C status and explicit, raised-wheel B/S console; no automatic motion."""
import argparse
import datetime
import json
from pathlib import Path
import sys
import time

from wire import Parser


def decode_status(payload):
    if len(payload) != 64 or payload[44:48] != b'I2C5':
        return None
    acks, status, fault_code, drive_low = payload[48:52]
    flags = int.from_bytes(payload[20:24], 'little')
    config = int.from_bytes(payload[61:64], 'little')
    version = config >> 22
    trim, cap = config & 1023, (config >> 10) & 2047
    supported = version == 1 and trim <= 800 and 1200 <= cap <= 2000
    return {
        'frames': int.from_bytes(payload[40:44], 'little'),
        'selected_pwm': int.from_bytes(payload[52:54], 'little'),
        'latched_pwm': int.from_bytes(payload[54:56], 'little'),
        'acked_left': int.from_bytes(payload[56:58], 'little', signed=True),
        'acked_right': int.from_bytes(payload[58:60], 'little', signed=True),
        'first_fault_acks': payload[60],
        'right_trim': trim if supported else None,
        'right_cap': cap if supported else None,
        'retry_epoch': (config >> 21) & 1 if supported else None,
        'manual_retry_supported': supported,
        'pwm_adjust_supported': supported,
        'last_acks': acks,
        'fault': bool(status & 1),
        'zero_ack': bool(status & 2),
        'busy': bool(status & 4),
        'motion_build': bool(status & 8),
        'fault_code': fault_code,
        'scl_drive_low': bool(drive_low & 1),
        'sda_drive_low': bool(drive_low & 2),
        'bench_active': bool(flags & (1 << 14)),
        'neural_armed': bool(flags & 4),
        'reserved_valid': not (status & 0xf0 or drive_low & 0xfc) and (config == 0 or supported) and int.from_bytes(payload[52:54], 'little') in (1200,1600,1800,2000),
    }


def bench_allowed(status, age_seconds):
    return bool(status and status['reserved_valid'] and age_seconds < 1.0 and
                status['motion_build'] and not status['bench_active'] and status['zero_ack'] and
                status['last_acks'] == 10 and status['fault_code'] == 0 and not status['fault'])


def blocked_reason(status, age_seconds):
    if not status:
        return 'No recognized FPGA status yet; no pulse was sent.'
    if age_seconds >= 1.0:
        return 'FPGA status is stale; check USB_UART connection. No pulse was sent.'
    if status['fault'] or status['fault_code']:
        code = status['fault_code']
        name = {1: 'BUS_STUCK', 2: 'SCL_TIMEOUT', 3: 'I2C_NACK',
                4: 'COMMAND_OUT_OF_RANGE', 5: 'ACK_COUNT_ERROR', 6: 'SCL_EDGE_LOST'}.get(code, 'UNKNOWN_FAULT')
        return ('Fault LATCHED: %s (code=%d). Recent ACK=%d/10 does not clear the fault. '
                'First fault ACK count=%d. Reopening CMD cannot clear it; stop repeated B and check power/wires.') % (name, code, status['last_acks'], status['first_fault_acks'])
    if status['bench_active']:
        return 'A pulse is already active; wait for automatic STOP.'
    if not status['motion_build']:
        return 'ZERO-only FPGA build: movement disabled.'
    if not status['zero_ack'] or status['last_acks'] != 10:
        return 'Complete initial zero-command ACK is missing; movement blocked.'
    return 'Invalid/reserved status fields; movement blocked.'


def select_port(ports, requested=None):
    choices = [p for p in ports if p.vid == 0x1a86 and p.pid == 0x7523 and
               (requested is None or p.device.upper() == requested.upper())]
    if len(choices) != 1:
        raise RuntimeError('Need exactly one FPGA CH340 USB_UART (1A86:7523); found %d' % len(choices))
    return choices[0].device


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port')
    ap.add_argument('--status-only', action='store_true')
    ap.add_argument('--seconds', type=float, default=10)
    args = ap.parse_args()
    if args.seconds <= 0:
        ap.error('--seconds must be positive')
    import serial
    from serial.tools.list_ports import comports
    import msvcrt

    port = select_port(comports(), args.port)
    root = Path(__file__).resolve().parent.parent
    out = root / 'board_runs' / datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out.mkdir(parents=True)
    (out / 'RUN_META.json').write_text(json.dumps({
        'version': 'WORK18_I2C5_MANUAL_LEVELS_V1',
        'port': port, 'baud': 115200, 'status_only': args.status_only,
        'automatic_motion': False, 'status_means_motor_motion': False,
    }, indent=2) + '\n', encoding='utf-8')
    print('FPGA I2C console: %s | 115200 baud' % port, flush=True)
    print('B = explicit 750 ms pulse; S/Space = STOP; Q = exit. Keep wheels raised.', flush=True)
    print('Default PWM=1800. L=1200 M=1600 H=1800 X=2000: select only, then press B.', flush=True)
    print('ACK is not motor execution feedback. No auto-start on level selection.', flush=True)
    print('Feedback: 1=no movement; 2=moved and stopped; 3=wrong/single wheel; 4=did not stop, power OFF.', flush=True)
    print('Logs: ' + str(out), flush=True)
    decoder = Parser()
    latest = None
    last_nonzero = (0, 0)
    received = 0
    shown = 0
    seen_packets = 0
    started = time.monotonic()
    with (out / 'uart_rx.bin').open('wb') as raw, (out / 'events.jsonl').open('w', encoding='utf-8') as events:
        def record(event, **fields):
            events.write(json.dumps({'time': time.monotonic(), 'event': event, **fields}) + '\n')
            events.flush()

        with serial.Serial(port, 115200, timeout=.1, write_timeout=.5) as connection:
            try:
                while not args.status_only or time.monotonic() - started < args.seconds:
                    chunk = connection.read(512)
                    if chunk:
                        raw.write(chunk)
                        raw.flush()
                        for kind, session, seq, payload in decoder.feed(chunk):
                            seen_packets += 1
                            if kind == 6:
                                row = decode_status(payload)
                                if row:
                                    latest = row
                                    if row['acked_left'] or row['acked_right']:
                                        last_nonzero = (row['acked_left'], row['acked_right'])
                                    received = time.monotonic()
                                    record('I2C_STATUS', session=session, seq=seq, **row)
                    now = time.monotonic()
                    if now - shown >= 1:
                        if latest and now - received < 1:
                            print('frames=%d ACK=%d/10 zero_ack=%s fault=%s code=%d motion_build=%s bench_active=%s' % (
                                latest['frames'], latest['last_acks'], latest['zero_ack'],
                                latest['fault'], latest['fault_code'], latest['motion_build'], latest['bench_active']), flush=True)
                            print('Next PWM=%d | latest ACKed=%d/%d | last nonzero ACKed=%d/%d' % (latest['selected_pwm'], latest['acked_left'], latest['acked_right'], *last_nonzero), flush=True)
                        elif latest:
                            print('I2C status STALE; B blocked. Check FPGA/USB_UART.', flush=True)
                        else:
                            print('Waiting for I2C5 status; packets=%d CRC_errors=%d. Old UART bit cannot pass.' % (
                                seen_packets, decoder.bad), flush=True)
                        shown = now
                    if not args.status_only and msvcrt.kbhit():
                        key = msvcrt.getwch().lower()
                        if key in ('\x00', '\xe0'):
                            if msvcrt.kbhit():
                                msvcrt.getwch()
                            continue
                        if key == 'q':
                            break
                        if key in ('1', '2', '3', '4'):
                            record('OPERATOR_PHYSICAL_FEEDBACK', choice=key)
                            print('Physical feedback recorded: ' + key, flush=True)
                        if key in ('s', ' '):
                            if latest and now - received < 1:
                                connection.write(b'S')
                                record('MANUAL_STOP')
                        if key in ('l', 'm', 'h', 'x'):
                            level, selector = {'l': (1200, b'1'), 'm': (1600, b'2'), 'h': (1800, b'3'), 'x': (2000, b'4')}[key]
                            if bench_allowed(latest, now - received):
                                connection.write(selector)
                                record('PWM_SELECTION_SENT', pwm=level)
                                print('Selection sent; wait for Next PWM=%d confirmation before B.' % level, flush=True)
                            else:
                                print('Selection BLOCKED: ' + blocked_reason(latest, now-received), flush=True)
                        if key == 'b':
                            if bench_allowed(latest, now - received):
                                connection.write(b'B')
                                record('MANUAL_BENCH_PULSE', requested_pwm=latest['selected_pwm'])
                            else:
                                reason = blocked_reason(latest, now - received)
                                print('B BLOCKED: ' + reason, flush=True)
                                record('BENCH_BLOCKED', reason=reason)
            finally:
                if not args.status_only and latest:
                    try:
                        connection.write(b'S')
                        record('EXIT_STOP_SENT')
                    except serial.SerialException as exc:
                        record('EXIT_STOP_FAILED', error=str(exc))
                        print('STOP send failed; turn chassis power OFF.', flush=True)
                record('EXIT', packets=seen_packets, crc_errors=decoder.bad)
    return 0 if latest and time.monotonic() - received < 1 else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR: ' + str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1)
