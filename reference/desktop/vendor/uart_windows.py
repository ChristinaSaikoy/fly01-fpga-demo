"""Approval-gated native Windows UART. No purge, implicit reset, or port-number guessing."""
import ctypes as ct
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import time

from uart_host import LinkFault

DWORD = ct.c_uint32
WORD = ct.c_uint16
BYTE = ct.c_uint8
HANDLE = ct.c_void_p
MAXDWORD = 0xFFFFFFFF


class DCB(ct.Structure):
    _fields_ = [('DCBlength', DWORD), ('BaudRate', DWORD), ('flags', DWORD),
        ('wReserved', WORD), ('XonLim', WORD), ('XoffLim', WORD), ('ByteSize', BYTE),
        ('Parity', BYTE), ('StopBits', BYTE), ('XonChar', ct.c_char), ('XoffChar', ct.c_char),
        ('ErrorChar', ct.c_char), ('EofChar', ct.c_char), ('EvtChar', ct.c_char), ('wReserved1', WORD)]


class COMMTIMEOUTS(ct.Structure):
    _fields_ = [(name, DWORD) for name in ('ReadIntervalTimeout', 'ReadTotalTimeoutMultiplier',
        'ReadTotalTimeoutConstant', 'WriteTotalTimeoutMultiplier', 'WriteTotalTimeoutConstant')]


class COMSTAT(ct.Structure):
    _fields_ = [('flags', DWORD), ('cbInQue', DWORD), ('cbOutQue', DWORD)]


IDENTITY_KEYS = ('device', 'vid', 'pid', 'pnp_instance_id', 'parent_instance_id', 'physical_path')
RUNTIME=Path(__file__).resolve().parent.parent


def inventory():
    script = Path(__file__).resolve().with_name('inventory_windows.ps1')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(script)],
        capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise LinkFault('passive Windows PnP inventory failed')
    return json.loads(result.stdout.decode('utf-8-sig'))


def select_device(identity, observed=None):
    if not isinstance(identity, dict) or any(not isinstance(identity.get(k), str) or not identity[k] for k in IDENTITY_KEYS):
        raise LinkFault('complete Windows device identity required')
    if identity['vid'] != '1a86' or identity['pid'] != '7523' or not re.fullmatch(r'COM[1-9][0-9]*', identity['device']):
        raise LinkFault('expected board CH340 USB_UART identity required')
    devices = inventory()['ports'] if observed is None else observed
    matches = [row for row in devices if row.get('status') == 'OK'
               and all(row.get(key) == identity[key] for key in IDENTITY_KEYS)]
    if len(matches) != 1:
        raise LinkFault('Windows serial identity absent or ambiguous')
    return matches[0]


def validate_authority(identity, baud, approval, receipt):
    auth = json.loads(Path(approval).read_text(encoding='utf-8'))
    loaded = json.loads(Path(receipt).read_text(encoding='utf-8'))
    if (baud not in (1000000, 2000000) or auth.get('status') != 'APPROVED_EXACT_ARTIFACT'
        or auth.get('uart_data_test_authorized') is not True or auth.get('uart_identity') != identity
        or auth.get('uart_baud') != baud or auth.get('host_platform') != 'windows-native'
        or auth.get('execution_host') != socket.gethostname()
        or auth.get('bit_sha256') != loaded.get('bitstream_sha256')
        or loaded.get('programming_status') not in ('PASS','REUSED_AFTER_READONLY_IDENTITY') or loaded.get('target_serial') != '210512180081'
        or loaded.get('suite_id') != auth.get('suite_id') or loaded.get('volatile_only') is not True):
        raise LinkFault('exact Windows UART authority/load identity missing')
    if loaded.get('programming_status')=='REUSED_AFTER_READONLY_IDENTITY' and (
        auth.get('programming_mode')!='REUSE_APPROVED_LOAD' or auth.get('power_continuity_confirmed') is not True
        or loaded.get('prior_receipt_sha256')!=auth.get('prior_receipt_sha256')
        or loaded.get('fresh_debug_identity_verified') is not True):
        raise LinkFault('exact current-load reuse scope missing')
    lock=json.loads((RUNTIME/'CANDIDATE_LOCK.json').read_text(encoding='utf-8'))
    if auth.get('candidate_sha256')!=lock['candidate_sha256'] or auth.get('suite_id') in lock['previously_consumed_suite_ids']:
        raise LinkFault('new host candidate scope or consumed permission mismatch')
    return auth


class NativeAPI:
    """Thin synchronous Win32 calls with finite per-I/O timeouts and exclusive handles."""
    def __init__(self, evidence=None):
        self.evidence = evidence
        if os.name != 'nt':
            raise RuntimeError('native Windows required')
        self.dll = ct.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateFileW': (HANDLE, [ct.c_wchar_p, DWORD, DWORD, HANDLE, DWORD, DWORD, HANDLE]),
            'CloseHandle': (ct.c_int, [HANDLE]),
            'GetCommState': (ct.c_int, [HANDLE, ct.POINTER(DCB)]),
            'SetCommState': (ct.c_int, [HANDLE, ct.POINTER(DCB)]),
            'SetCommTimeouts': (ct.c_int, [HANDLE, ct.POINTER(COMMTIMEOUTS)]),
            'SetupComm': (ct.c_int, [HANDLE, DWORD, DWORD]),
            'ClearCommError': (ct.c_int, [HANDLE, ct.POINTER(DWORD), ct.POINTER(COMSTAT)]),
            'ReadFile': (ct.c_int, [HANDLE, ct.c_void_p, DWORD, ct.POINTER(DWORD), HANDLE]),
            'WriteFile': (ct.c_int, [HANDLE, ct.c_void_p, DWORD, ct.POINTER(DWORD), HANDLE])}
        for name, (result, args) in signatures.items():
            method = getattr(self.dll, name)
            method.restype, method.argtypes = result, args

    def _call(self,name,*args,requested=0,completed=None):
        function=getattr(self.dll,name)
        trace=getattr(self.evidence,'trace',None)
        if trace is None:
            return function(*args)
        seq=self.evidence.seq
        wall,cpu=time.perf_counter_ns(),time.thread_time_ns()
        value=function(*args)
        end,cpu_end=time.perf_counter_ns(),time.thread_time_ns()
        error=ct.get_last_error()
        try:
            trace.record(name,wall,end,cpu,cpu_end,seq,requested=requested,
                actual=completed.value if completed is not None else 0,value=int(value),error=0 if value else error)
        finally:
            ct.set_last_error(error)
        return value

    @staticmethod
    def checked(value, label):
        if not value:
            raise LinkFault(label + ' WinError=' + str(ct.get_last_error()))

    def open(self, device, baud):
        # OPEN_EXISTING, zero sharing and non-inheritable: exclusive physical COM ownership.
        name = chr(92) * 2 + '.' + chr(92) + device
        handle = self.dll.CreateFileW(name, 0xC0000000, 0, None, 3, 0, None)
        if handle == ct.c_void_p(-1).value or handle is None:
            raise LinkFault('exclusive COM open failed WinError=' + str(ct.get_last_error()))
        try:
            self.checked(self.dll.SetupComm(handle, 16384, 16384), 'SetupComm')
            settings = DCB()
            settings.DCBlength = ct.sizeof(DCB)
            self.checked(self.dll.GetCommState(handle, ct.byref(settings)), 'GetCommState')
            settings.BaudRate, settings.flags = baud, 1
            settings.ByteSize, settings.Parity, settings.StopBits = 8, 0, 0
            self.checked(self.dll.SetCommState(handle, ct.byref(settings)), 'SetCommState')
            self.checked(self.dll.GetCommState(handle, ct.byref(settings)), 'GetCommState readback')
            if (settings.BaudRate, settings.ByteSize, settings.Parity, settings.StopBits, settings.flags) != (baud, 8, 0, 0, 1):
                raise LinkFault('actual DCB does not match 8N1/no-flow/DTR-RTS-disabled')
            self.timeouts(handle, 500)
            return handle, dict(baud=settings.BaudRate, data_bits=8, parity='NONE', stop_bits=1,
                flags=settings.flags, exclusive=True, purge_performed=False,
                note='Driver/OS line transitions at open are not claimed glitch-free')
        except BaseException:
            self.dll.CloseHandle(handle)
            raise

    def timeouts(self, handle, milliseconds):
        # Documented MAXDWORD/MAXDWORD first-byte behavior, never an infinite timeout.
        values = COMMTIMEOUTS(MAXDWORD, MAXDWORD, milliseconds, 0, milliseconds)
        self.checked(self._call('SetCommTimeouts',handle,ct.byref(values)), 'SetCommTimeouts')

    def errors(self, handle):
        flags, status = DWORD(), COMSTAT()
        self.checked(self._call('ClearCommError',handle,ct.byref(flags),ct.byref(status),completed=flags), 'ClearCommError')
        return flags.value

    def read(self, handle, size):
        data, count = ct.create_string_buffer(size), DWORD()
        self.checked(self._call('ReadFile',handle,data,size,ct.byref(count),None,requested=size,completed=count), 'ReadFile')
        return data.raw[:count.value]

    def write(self, handle, data):
        buffer, count = ct.create_string_buffer(data), DWORD()
        self.checked(self._call('WriteFile',handle,buffer,len(data),ct.byref(count),None,requested=len(data),completed=count), 'WriteFile')
        return count.value

    def close(self, handle):
        self.checked(self.dll.CloseHandle(handle), 'CloseHandle')


class WindowsPort:
    def __init__(self, handle, evidence, api):
        self.handle, self.evidence, self.api = handle, evidence, api

    @classmethod
    def open_approved(cls, identity, baud, approval, receipt, evidence):
        # No native API object, enumeration or device open before exact authority validation.
        validate_authority(identity, baud, approval, receipt)
        selected = select_device(identity)
        api = NativeAPI(evidence)
        handle, settings = api.open(selected['device'], baud)
        port = cls(handle, evidence, api)
        try:
            evidence.record('OPEN', identity=selected, baud=baud, actual_windows_dcb=settings)
            port._check_errors()
        except BaseException:
            api.close(handle)
            port.handle = None
            raise
        return port

    def _check_errors(self):
        if self.handle is None:
            raise LinkFault('Windows UART already closed')
        flags = self.api.errors(self.handle)
        if flags:
            self.evidence.record('UART_NATIVE_ERROR', windows_comm_errors=flags)
            raise LinkFault('Windows UART framing/overrun/parity error ' + hex(flags))

    def _timeout(self, deadline):
        remain = deadline - time.monotonic()
        if not math.isfinite(remain) or remain <= 0:
            raise TimeoutError('Windows UART deadline')
        self.api.timeouts(self.handle, max(1, min(500, int(remain * 1000))))

    def write(self, data, deadline):
        offset = 0
        while offset < len(data):
            self._check_errors()
            self._timeout(deadline)
            count = self.api.write(self.handle, data[offset:])
            if not 0 < count <= len(data) - offset:
                raise LinkFault('Windows UART zero/invalid write completion')
            self.evidence.record('TX', data[offset:offset + count])
            offset += count
        self._check_errors()

    def read(self, deadline):
        while True:
            self._check_errors()
            self._timeout(deadline)
            data = self.api.read(self.handle, 4096)
            if data:
                self.evidence.record('RX', data)
            self._check_errors()
            if data:
                return data

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            try:
                self.evidence.record('CLOSE')
            finally:
                self.api.close(handle)
