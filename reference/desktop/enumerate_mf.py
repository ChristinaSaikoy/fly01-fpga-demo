"""Metadata-only MF enumeration; never activates a camera."""
import ctypes as C
from ctypes import wintypes as W
import json
import uuid

class GUID(C.Structure):
    _fields_ = [('data', C.c_ubyte * 16)]
    @classmethod
    def parse(cls, text):
        return cls((C.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le))

def method(obj, index, restype, *args):
    table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(restype, C.c_void_p, *args)(table[index])

def check(hr):
    if hr < 0:
        raise OSError(f'HRESULT 0x{hr & 0xffffffff:08x}')

def enumerate_devices():
    ole = C.OleDLL('ole32')
    plat = C.WinDLL('mfplat')
    mf = C.WinDLL('mf')
    ole.CoTaskMemFree.argtypes = [C.c_void_p]
    check(ole.CoInitializeEx(None, 0))
    check(plat.MFStartup(0x00020070, 0))
    attrs = C.c_void_p()
    sources = C.POINTER(C.c_void_p)()
    count = W.DWORD()
    try:
        check(plat.MFCreateAttributes(C.byref(attrs), 1))
        key = GUID.parse('c60ac5fe-252a-478f-a0ef-bc8fa5f7cad3')
        value = GUID.parse('8ac3587a-4ae7-42d8-99e0-0a6013eef90f')
        check(method(attrs, 24, C.c_long, C.POINTER(GUID), C.POINTER(GUID))(attrs, C.byref(key), C.byref(value)))
        check(mf.MFEnumDeviceSources(attrs, C.byref(sources), C.byref(count)))
        result = []
        for index in range(count.value):
            obj = sources[index]
            row = {'index': index, 'backend': 'MSMF'}
            for field, key_text in [('name', '60d0e559-52f8-4fa2-bbce-acdb34a8ec01'), ('symbolic_link', '58f0aad8-22bf-4f8a-bb3d-d2c4978c6e2f')]:
                key = GUID.parse(key_text)
                pointer = C.c_void_p()
                length = W.UINT()
                check(method(obj, 13, C.c_long, C.POINTER(GUID), C.POINTER(C.c_void_p), C.POINTER(W.UINT))(obj, C.byref(key), C.byref(pointer), C.byref(length)))
                try:
                    row[field] = C.wstring_at(pointer, length.value)
                finally:
                    ole.CoTaskMemFree(pointer)
            result.append(row)
        return result
    finally:
        if sources:
            for index in range(count.value):
                method(sources[index], 2, W.ULONG)(sources[index])
            ole.CoTaskMemFree(sources)
        if attrs:
            method(attrs, 2, W.ULONG)(attrs)
        plat.MFShutdown()
        ole.CoUninitialize()

if __name__ == '__main__':
    print(json.dumps(enumerate_devices(), indent=2))
