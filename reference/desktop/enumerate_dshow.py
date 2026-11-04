"""Read DirectShow moniker properties only; no filter/camera activation."""
import ctypes as C
from ctypes import wintypes as W
import json
from enumerate_mf import GUID, check, method

def enumerate_devices():
    ole = C.OleDLL('ole32')
    auto = C.OleDLL('oleaut32')
    check(ole.CoInitializeEx(None, 0))
    dev = C.c_void_p()
    enum = C.c_void_p()
    def release(obj):
        if obj:
            method(obj, 2, W.ULONG)(obj)
    try:
        cls = GUID.parse('62be5d10-60eb-11d0-bd3b-00a0c911ce86')
        iid = GUID.parse('29840822-5b84-11d0-bd3b-00a0c911ce86')
        check(ole.CoCreateInstance(C.byref(cls), None, 1, C.byref(iid), C.byref(dev)))
        category = GUID.parse('860bb310-5d01-11d0-bd3b-00a0c911ce86')
        hr = method(dev, 3, C.c_long, C.POINTER(GUID), C.POINTER(C.c_void_p), W.DWORD)(dev, C.byref(category), C.byref(enum), 0)
        check(hr)
        if hr == 1:
            return []
        result = []
        while True:
            moniker = C.c_void_p()
            hr = method(enum, 3, C.c_long, W.ULONG, C.POINTER(C.c_void_p), C.c_void_p)(enum, 1, C.byref(moniker), None)
            if hr == 1:
                break
            check(hr)
            bag = C.c_void_p()
            try:
                iid = GUID.parse('55272a00-42cb-11ce-8135-00aa004bb851')
                check(method(moniker, 9, C.c_long, C.c_void_p, C.c_void_p, C.POINTER(GUID), C.POINTER(C.c_void_p))(moniker, None, None, C.byref(iid), C.byref(bag)))
                row = {'index': len(result), 'backend': 'DSHOW'}
                for field, key in [('name', 'FriendlyName'), ('symbolic_link', 'DevicePath')]:
                    variant = (C.c_uint64 * 3)()
                    check(method(bag, 3, C.c_long, W.LPCWSTR, C.c_void_p, C.c_void_p)(bag, key, C.byref(variant), None))
                    try:
                        if variant[0] & 0xffff != 8:
                            raise RuntimeError('Property must be BSTR')
                        row[field] = C.wstring_at(variant[1])
                    finally:
                        auto.VariantClear(C.byref(variant))
                result.append(row)
            finally:
                release(bag)
                release(moniker)
        return result
    finally:
        release(enum)
        release(dev)
        ole.CoUninitialize()

if __name__ == '__main__':
    print(json.dumps(enumerate_devices(), indent=2))
