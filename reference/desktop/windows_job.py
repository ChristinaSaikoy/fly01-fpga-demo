"""Own only newly spawned processes; bind a waiting child before allowing it to run."""
import ctypes as ct
import os
import subprocess

DWORD = ct.c_uint32
HANDLE = ct.c_void_p
SIZE_T = ct.c_size_t


class BASIC_LIMIT(ct.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ct.c_int64), ('PerJobUserTimeLimit', ct.c_int64),
        ('LimitFlags', DWORD), ('MinimumWorkingSetSize', SIZE_T), ('MaximumWorkingSetSize', SIZE_T),
        ('ActiveProcessLimit', DWORD), ('Affinity', SIZE_T), ('PriorityClass', DWORD), ('SchedulingClass', DWORD)]


class IO_COUNTERS(ct.Structure):
    _fields_ = [(name, ct.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount',
        'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class EXTENDED_LIMIT(ct.Structure):
    _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', SIZE_T), ('JobMemoryLimit', SIZE_T),
        ('PeakProcessMemoryUsed', SIZE_T), ('PeakJobMemoryUsed', SIZE_T)]


class ACCOUNTING(ct.Structure):
    _fields_ = [(name, ct.c_int64) for name in ('TotalUserTime', 'TotalKernelTime',
        'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')] + [
        (name, DWORD) for name in ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')]


class OwnedJob:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Windows process job required')
        self.dll = ct.WinDLL('kernel32', use_last_error=True)
        for name, result, args in (
            ('CreateJobObjectW', HANDLE, [HANDLE, ct.c_wchar_p]),
            ('SetInformationJobObject', ct.c_int, [HANDLE, ct.c_int, ct.c_void_p, DWORD]),
            ('AssignProcessToJobObject', ct.c_int, [HANDLE, HANDLE]),
            ('TerminateJobObject', ct.c_int, [HANDLE, ct.c_uint]),
            ('QueryInformationJobObject', ct.c_int, [HANDLE, ct.c_int, ct.c_void_p, DWORD, ct.POINTER(DWORD)]),
            ('CloseHandle', ct.c_int, [HANDLE])):
            function = getattr(self.dll, name)
            function.restype, function.argtypes = result, args
        self.handle = self.dll.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ct.get_last_error(), 'CreateJobObjectW')
        settings = EXTENDED_LIMIT()
        settings.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.dll.SetInformationJobObject(self.handle, 9, ct.byref(settings), ct.sizeof(settings)):
            self.close()
            raise OSError(ct.get_last_error(), 'SetInformationJobObject')

    def assign_waiting_child(self, child):
        # Callers must spawn their bootstrap with an unread stdin gate. No release on failure.
        if not self.dll.AssignProcessToJobObject(self.handle, HANDLE(int(child._handle))):
            child.terminate()
            child.wait(timeout=5)
            raise OSError(ct.get_last_error(), 'AssignProcessToJobObject')

    def active(self):
        counts = ACCOUNTING()
        if not self.dll.QueryInformationJobObject(self.handle, 1, ct.byref(counts), ct.sizeof(counts), None):
            raise OSError(ct.get_last_error(), 'QueryInformationJobObject')
        return counts.ActiveProcesses

    def terminate(self, code=124):
        if self.handle and not self.dll.TerminateJobObject(self.handle, code):
            raise OSError(ct.get_last_error(), 'TerminateJobObject')

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.dll.CloseHandle(handle):
                raise OSError(ct.get_last_error(), 'CloseHandle job')


def stop_owned_tree(child):
    if child is not None and child.poll() is None:
        # This PID is an owned, still-live Popen handle, not a name/pattern-selected user process.
        subprocess.run(['taskkill.exe', '/PID', str(child.pid), '/T', '/F'],
                       capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        child.wait(timeout=5)
