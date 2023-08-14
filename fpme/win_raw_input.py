"""
This is the Windows backend for keyboard events, and is implemented by invoking the Win32 API through the ctypes module.
This is error-prone and can introduce very unpythonic failure modes, such as segfaults and low level memory leaks.
But it is also dependency-free, very performant well documented on Microsoft's website and scattered examples.
"""
import ctypes
from ctypes import c_short, c_uint8, c_int, c_uint, c_long, Structure, CFUNCTYPE, POINTER, WINFUNCTYPE, byref, sizeof, Union, c_ushort
from ctypes.wintypes import WORD, DWORD, BOOL, HHOOK, MSG, LPWSTR, WCHAR, WPARAM, LPARAM, LONG, USHORT, HWND, UINT, HANDLE, LPCWSTR, ULONG, BYTE, HMENU, HINSTANCE, LPVOID, INT
from dataclasses import dataclass
from typing import Callable, Optional

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

LPMSG = POINTER(MSG)
ULONG_PTR = POINTER(DWORD)


class KBDLLHOOKSTRUCT(Structure):  # https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-kbdllhookstruct
    _fields_ = [("vk_code", DWORD),
                ("scan_code", DWORD),
                ("flags", DWORD),
                ("time", c_int),
                ("dwExtraInfo", ULONG_PTR)]


# Included for completeness.
class MOUSEINPUT(Structure):
    _fields_ = (('dx', LONG),
                ('dy', LONG),
                ('mouseData', DWORD),
                ('dwFlags', DWORD),
                ('time', DWORD),
                ('dwExtraInfo', ULONG_PTR))


class KEYBDINPUT(Structure):
    _fields_ = (('vk_code', WORD),
                ('scan_code', WORD),
                ('flags', DWORD),
                ('time', DWORD),
                ('dwExtraInfo', ULONG_PTR))


class HARDWAREINPUT(Structure):
    _fields_ = (('uMsg', DWORD),
                ('wParamL', WORD),
                ('wParamH', WORD))


class _INPUTunion(Union):
    _fields_ = (('mi', MOUSEINPUT),
                ('ki', KEYBDINPUT),
                ('hi', HARDWAREINPUT))


class INPUT(Structure):
    _fields_ = (('type', DWORD),
                ('union', _INPUTunion))


class RAWINPUTDEVICE(Structure):
    _fields_ = [("us_usage_page", USHORT),
                ("us_usage", USHORT),
                ("dw_flags", DWORD),
                ("hwnd_target", HWND)]


WNDPROCTYPE = WINFUNCTYPE(c_int, HWND, c_uint, WPARAM, LPARAM)
CS_HREDRAW = 2
CS_VREDRAW = 1
CW_USEDEFAULT = 0x80000000
WHITE_BRUSH = 0

RI_KEY_BREAK = 0x01
RI_KEY_MAKE = 0x00

RIM_TYPEMOUSE = 0x00000000
RIM_TYPEKEYBOARD = 0x00000001
RIM_TYPEHID = 0x00000002

RID_INPUT = 0x10000003

RIDEV_INPUTSINK = 0x00000100


class WNDCLASSEX(Structure):  # https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-wndclassexa
    _fields_ = [("cbSize", c_uint),
                ("style", c_uint),
                ("lpfnWndProc", WNDPROCTYPE),
                ("cbClsExtra", c_int),
                ("cbWndExtra", c_int),
                ("hInstance", HANDLE),
                ("hIcon", HANDLE),
                ("hCursor", HANDLE),
                ("hBrush", HANDLE),
                ("lpszMenuName", LPCWSTR),
                ("lpszClassName", LPCWSTR),
                ("hIconSm", HANDLE)]


class RAWINPUTHEADER(Structure):
    _fields_ = [
        ("dwType", DWORD),
        ("dwSize", DWORD),
        ("hDevice", HANDLE),
        ("wParam", WPARAM),
    ]


class RAWMOUSE(Structure):
    class _U1(Union):
        class _S2(Structure):
            _fields_ = [
                ("usButtonFlags", c_ushort),
                ("usButtonData", c_ushort),
            ]

        _fields_ = [
            ("ulButtons", ULONG),
            ("_s2", _S2),
        ]

    _fields_ = [
        ("usFlags", c_ushort),
        ("_u1", _U1),
        ("ulRawButtons", ULONG),
        ("lLastX", LONG),
        ("lLastY", LONG),
        ("ulExtraInformation", ULONG),
    ]
    _anonymous_ = ("_u1",)


class RAWKEYBOARD(Structure):
    _fields_ = [
        ("scan_code", c_ushort),
        ("flags", c_ushort),
        ("reserved", c_ushort),
        ("vk_code", c_ushort),
        ("message", UINT),
        ("dwExtraInfo", ULONG),
    ]


class RAWHID(Structure):
    _fields_ = [
        ("dwSizeHid", DWORD),
        ("dwCount", DWORD),
        ("bRawData", BYTE),
    ]


class _RAWINPUTUnion(Union):
    _fields_ = [
        ("mouse", RAWMOUSE),
        ("keyboard", RAWKEYBOARD),
        ("hid", RAWHID),
    ]


class RAWINPUT(Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", _RAWINPUTUnion),
    ]


RegisterRawInputDevices = user32.RegisterRawInputDevices
RegisterRawInputDevices.argtypes = [POINTER(RAWINPUTDEVICE), UINT, UINT]
RegisterRawInputDevices.restype = UINT

CreateWindowExW = user32.CreateWindowExW
CreateWindowExW.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD, INT, INT, INT, INT, HWND, HMENU, HINSTANCE, LPVOID]
CreateWindowExW.restype = HWND

LowLevelKeyboardProc = CFUNCTYPE(c_int, WPARAM, LPARAM, POINTER(KBDLLHOOKSTRUCT))

SetWindowsHookEx = user32.SetWindowsHookExA  # https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowshookexa
# SetWindowsHookEx.argtypes = [c_int, LowLevelKeyboardProc, c_int, c_int]
SetWindowsHookEx.restype = HHOOK

CallNextHookEx = user32.CallNextHookEx
# CallNextHookEx.argtypes = [c_int , c_int, c_int, POINTER(KBDLLHOOKSTRUCT)]
CallNextHookEx.restype = c_int

UnhookWindowsHookEx = user32.UnhookWindowsHookEx
UnhookWindowsHookEx.argtypes = [HHOOK]
UnhookWindowsHookEx.restype = BOOL

GetMessage = user32.GetMessageW
GetMessage.argtypes = [LPMSG, c_int, c_int, c_int]
GetMessage.restype = BOOL

GetLastError = kernel32.GetLastError
GetLastError.argtypes = []
GetLastError.restype = DWORD

TranslateMessage = user32.TranslateMessage
TranslateMessage.argtypes = [LPMSG]
TranslateMessage.restype = BOOL

DispatchMessage = user32.DispatchMessageA
DispatchMessage.argtypes = [LPMSG]

keyboard_state_type = c_uint8 * 256

GetKeyboardState = user32.GetKeyboardState
GetKeyboardState.argtypes = [keyboard_state_type]
GetKeyboardState.restype = BOOL

GetKeyNameText = user32.GetKeyNameTextW
GetKeyNameText.argtypes = [c_long, LPWSTR, c_int]
GetKeyNameText.restype = c_int

MapVirtualKey = user32.MapVirtualKeyW
MapVirtualKey.argtypes = [c_uint, c_uint]
MapVirtualKey.restype = c_uint

ToUnicode = user32.ToUnicode
ToUnicode.argtypes = [c_uint, c_uint, keyboard_state_type, LPWSTR, c_int, c_uint]
ToUnicode.restype = c_int

MAPVK_VK_TO_VSC = 0
MAPVK_VSC_TO_VK = 1

VkKeyScan = user32.VkKeyScanW
VkKeyScan.argtypes = [WCHAR]
VkKeyScan.restype = c_short

NULL = c_int(0)

WM_INPUT = 0x00FF

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x104  # Used for ALT key
WM_SYSKEYUP = 0x105


# List taken from the official documentation, but stripped of the OEM-specific keys. Keys are virtual key codes, values are pairs (name, is_keypad).
VIRTUAL_KEYBOARD = {
    0x03: ('control-break processing', False),
    0x08: ('backspace', False),
    0x09: ('tab', False),
    0x0c: ('clear', False),
    0x0d: ('enter', False),
    0x10: ('shift', False),
    0x11: ('ctrl', False),
    0x12: ('alt', False),
    0x13: ('pause', False),
    0x14: ('caps lock', False),
    0x15: ('ime kana mode', False),
    0x15: ('ime hanguel mode', False),
    0x15: ('ime hangul mode', False),
    0x17: ('ime junja mode', False),
    0x18: ('ime final mode', False),
    0x19: ('ime hanja mode', False),
    0x19: ('ime kanji mode', False),
    0x1b: ('esc', False),
    0x1c: ('ime convert', False),
    0x1d: ('ime nonconvert', False),
    0x1e: ('ime accept', False),
    0x1f: ('ime mode change request', False),
    0x20: ('spacebar', False),
    0x21: ('page up', False),
    0x22: ('page down', False),
    0x23: ('end', False),
    0x24: ('home', False),
    0x25: ('left', False),
    0x26: ('up', False),
    0x27: ('right', False),
    0x28: ('down', False),
    0x29: ('select', False),
    0x2a: ('print', False),
    0x2b: ('execute', False),
    0x2c: ('print screen', False),
    0x2d: ('insert', False),
    0x2e: ('delete', False),
    0x2f: ('help', False),
    0x30: ('0', False),
    0x31: ('1', False),
    0x32: ('2', False),
    0x33: ('3', False),
    0x34: ('4', False),
    0x35: ('5', False),
    0x36: ('6', False),
    0x37: ('7', False),
    0x38: ('8', False),
    0x39: ('9', False),
    0x41: ('a', False),
    0x42: ('b', False),
    0x43: ('c', False),
    0x44: ('d', False),
    0x45: ('e', False),
    0x46: ('f', False),
    0x47: ('g', False),
    0x48: ('h', False),
    0x49: ('i', False),
    0x4a: ('j', False),
    0x4b: ('k', False),
    0x4c: ('l', False),
    0x4d: ('m', False),
    0x4e: ('n', False),
    0x4f: ('o', False),
    0x50: ('p', False),
    0x51: ('q', False),
    0x52: ('r', False),
    0x53: ('s', False),
    0x54: ('t', False),
    0x55: ('u', False),
    0x56: ('v', False),
    0x57: ('w', False),
    0x58: ('x', False),
    0x59: ('y', False),
    0x5a: ('z', False),
    0x5b: ('left windows', False),
    0x5c: ('right windows', False),
    0x5d: ('applications', False),
    0x5f: ('sleep', False),
    0x60: ('0', True),
    0x61: ('1', True),
    0x62: ('2', True),
    0x63: ('3', True),
    0x64: ('4', True),
    0x65: ('5', True),
    0x66: ('6', True),
    0x67: ('7', True),
    0x68: ('8', True),
    0x69: ('9', True),
    0x6a: ('*', True),
    0x6b: ('+', True),
    0x6c: ('separator', True),
    0x6d: ('-', True),
    0x6e: ('decimal', True),
    0x6f: ('/', True),
    0x70: ('f1', False),
    0x71: ('f2', False),
    0x72: ('f3', False),
    0x73: ('f4', False),
    0x74: ('f5', False),
    0x75: ('f6', False),
    0x76: ('f7', False),
    0x77: ('f8', False),
    0x78: ('f9', False),
    0x79: ('f10', False),
    0x7a: ('f11', False),
    0x7b: ('f12', False),
    0x7c: ('f13', False),
    0x7d: ('f14', False),
    0x7e: ('f15', False),
    0x7f: ('f16', False),
    0x80: ('f17', False),
    0x81: ('f18', False),
    0x82: ('f19', False),
    0x83: ('f20', False),
    0x84: ('f21', False),
    0x85: ('f22', False),
    0x86: ('f23', False),
    0x87: ('f24', False),
    0x90: ('num lock', True),
    0x91: ('scroll lock', False),
    0xa0: ('left shift', False),
    0xa1: ('right shift', False),
    0xa2: ('left ctrl', False),
    0xa3: ('right ctrl', False),
    0xa4: ('left menu', False),
    0xa5: ('right menu', False),
    0xa6: ('browser back', False),
    0xa7: ('browser forward', False),
    0xa8: ('browser refresh', False),
    0xa9: ('browser stop', False),
    0xaa: ('browser search key ', False),
    0xab: ('browser favorites', False),
    0xac: ('browser start and home', False),
    0xad: ('volume mute', False),
    0xae: ('volume down', False),
    0xaf: ('volume up', False),
    0xb0: ('next track', False),
    0xb1: ('previous track', False),
    0xb2: ('stop media', False),
    0xb3: ('play/pause media', False),
    0xb4: ('start mail', False),
    0xb5: ('select media', False),
    0xb6: ('start application 1', False),
    0xb7: ('start application 2', False),
    0xbb: ('+', False),
    0xbc: (',', False),
    0xbd: ('-', False),
    0xbe: ('.', False),
    # 0xbe: ('/', False), # Used for miscellaneous characters; it can vary by keyboard. For the US standard keyboard, the '/?' key.
    0xe5: ('ime process', False),
    0xf6: ('attn', False),
    0xf7: ('crsel', False),
    0xf8: ('exsel', False),
    0xf9: ('erase eof', False),
    0xfa: ('play', False),
    0xfb: ('zoom', False),
    0xfc: ('reserved ', False),
    0xfd: ('pa1', False),
    0xfe: ('clear', False),
}

# TODO: add values from https://svn.apache.org/repos/asf/xmlgraphics/commons/tags/commons-1_0/src/java/org/apache/xmlgraphics/fonts/Glyphs.java
canonical_names = {
    'escape': 'esc',
    'return': 'enter',
    'del': 'delete',
    'control': 'ctrl',
    'altgr': 'alt gr',

    'left arrow': 'left',
    'up arrow': 'up',
    'down arrow': 'down',
    'right arrow': 'right',

    ' ': 'space',  # Prefer to spell out keys that would be hard to read.
    '\x1b': 'esc',
    '\x08': 'backspace',
    '\n': 'enter',
    '\t': 'tab',
    '\r': 'enter',

    'scrlk': 'scroll lock',
    'prtscn': 'print screen',
    'prnt scrn': 'print screen',
    'snapshot': 'print screen',
    'ins': 'insert',
    'pause break': 'pause',
    'ctrll lock': 'caps lock',
    'capslock': 'caps lock',
    'number lock': 'num lock',
    'numlock:': 'num lock',
    'space bar': 'space',
    'spacebar': 'space',
    'linefeed': 'enter',
    'win': 'windows',

    'app': 'menu',
    'apps': 'menu',
    'application': 'menu',
    'applications': 'menu',

    'pagedown': 'page down',
    'pageup': 'page up',
    'pgdown': 'page down',
    'pgup': 'page up',
    'next': 'page down',  # This looks wrong, but this is how Linux reports.
    'prior': 'page up',

    'underscore': '_',
    'equal': '=',
    'minplus': '+',
    'plus': '+',
    'add': '+',
    'subtract': '-',
    'minus': '-',
    'multiply': '*',
    'asterisk': '*',
    'divide': '/',

    'question': '?',
    'exclam': '!',
    'slash': '/',
    'bar': '|',
    'backslash': '\\',
    'braceleft': '{',
    'braceright': '}',
    'bracketleft': '[',
    'bracketright': ']',
    'parenleft': '(',
    'parenright': ')',

    'period': '.',
    'dot': '.',
    'comma': ',',
    'semicolon': ';',
    'colon': ':',

    'less': '<',
    'greater': '>',
    'ampersand': '&',
    'at': '@',
    'numbersign': '#',
    'hash': '#',
    'hashtag': '#',

    'dollar': '$',
    'sterling': '£',
    'pound': '£',
    'yen': '¥',
    'euro': '€',
    'cent': '¢',
    'currency': '¤',
    'registered': '®',
    'copyright': '©',
    'notsign': '¬',
    'percent': '%',
    'diaeresis': '"',
    'quotedbl': '"',
    'onesuperior': '¹',
    'twosuperior': '²',
    'threesuperior': '³',
    'onehalf': '½',
    'onequarter': '¼',
    'threequarters': '¾',
    'paragraph': '¶',
    'section': '§',
    'ssharp': '§',
    'division': '÷',
    'questiondown': '¿',
    'exclamdown': '¡',
    'degree': '°',
    'guillemotright': '»',
    'guillemotleft': '«',

    'acute': '´',
    'agudo': '´',
    'grave': '`',
    'tilde': '~',
    'asciitilde': '~',
    'til': '~',
    'cedilla': ',',
    'circumflex': '^',
    'apostrophe': '\'',

    'adiaeresis': 'ä',
    'udiaeresis': 'ü',
    'odiaeresis': 'ö',
    'oe': 'Œ',
    'oslash': 'ø',
    'ooblique': 'Ø',
    'ccedilla': 'ç',
    'ntilde': 'ñ',
    'eacute': 'é',
    'uacute': 'ú',
    'oacute': 'ó',
    'thorn': 'þ',
    'ae': 'æ',
    'eth': 'ð',
    'masculine': 'º',
    'feminine': 'ª',
    'iacute': 'í',
    'aacute': 'á',
    'mu': 'Μ',
    'aring': 'å',

    'zero': '0',
    'one': '1',
    'two': '2',
    'three': '3',
    'four': '4',
    'five': '5',
    'six': '6',
    'seven': '7',
    'eight': '8',
    'nine': '9',

    'play/pause': 'play/pause media',

    'num multiply': '*',
    'num divide': '/',
    'num add': '+',
    'num plus': '+',
    'num minus': '-',
    'num sub': '-',
    'num enter': 'enter',
    'num 0': '0',
    'num 1': '1',
    'num 2': '2',
    'num 3': '3',
    'num 4': '4',
    'num 5': '5',
    'num 6': '6',
    'num 7': '7',
    'num 8': '8',
    'num 9': '9',

    'left win': 'left windows',
    'right win': 'right windows',
    'left control': 'left ctrl',
    'right control': 'right ctrl',
    'left menu': 'left alt',  # Windows...
}


def normalize_name(name):
    if not name:
        return 'unknown'
    name = name.lower()
    if name != '_':
        name = name.replace('_', ' ')
    return canonical_names.get(name, name)


def _create_key_name_tables():
    """
    Build tables for scan codes.

    Returns:
        lower_case: `dict` mapping scan_code to lower-case key names
        upper_case: `dict` mapping scan code to upper-case key names
    """
    key_names_by_scan_code = {}
    scan_code_to_vk = {}

    for vk in range(0x01, 0x100):
        scan_code = MapVirtualKey(vk, MAPVK_VK_TO_VSC)
        if not scan_code: continue

        # Scan codes may map to multiple virtual key codes.
        # In this case prefer the officially defined ones.
        if scan_code_to_vk.get(scan_code, 0) not in VIRTUAL_KEYBOARD:
            scan_code_to_vk[scan_code] = vk

    name_buffer = ctypes.create_unicode_buffer(32)
    keyboard_state = keyboard_state_type()
    for scan_code in range(2 ** (23 - 16)):
        key_names_by_scan_code[scan_code] = ['unknown', 'unknown']

        # Get pure key name, such as "shift". This depends on locale and
        # may return a translated name.
        for enhanced in [1, 0]:
            ret = GetKeyNameText(scan_code << 16 | enhanced << 24, name_buffer, 1024)
            if not ret:
                continue
            name = normalize_name(name_buffer.value)
            key_names_by_scan_code[scan_code] = [name, name]

        if scan_code not in scan_code_to_vk: continue
        # Get associated character, such as "^", possibly overwriting the pure key name.
        for shift_state in [0, 1]:
            keyboard_state[0x10] = shift_state * 0xFF
            vk = scan_code_to_vk.get(scan_code, 0)
            ret = ToUnicode(vk, scan_code, keyboard_state, name_buffer, len(name_buffer), 0)
            if ret:
                # Sometimes two characters are written before the char we want,
                # usually an accented one such as Â. Couldn't figure out why.
                char = name_buffer.value[-1]
                key_names_by_scan_code[scan_code][shift_state] = char

    key_names_by_scan_code[541] = ['alt gr', 'alt gr']
    # key_names_by_vk_code = {vk: key_names_by_scan_code[scan_code] for scan_code, vk in scan_code_to_vk.items()}
    return {c: lower for c, (lower, upper) in key_names_by_scan_code.items()}, {c: upper for c, (lower, upper) in key_names_by_scan_code.items()}


KEY_NAMES_LOWER, KEY_NAMES_UPPER = _create_key_name_tables()

_REGISTERED_PROCEDURES_REFS = []  # do not garbage collect these


def set_window_procedure(hwnd, procedure: Callable, call_original=False):
    def process_message(hwnd, msg, wParam, lParam):
        procedure(hwnd, msg, wParam, lParam)
        if call_original:
            return user32.CallWindowProcA(prevWndProc, c_int(hwnd), c_int(msg), c_int(wParam), c_int(lParam))
        else:
            return user32.DefWindowProcA(c_int(hwnd), c_int(msg), c_int(wParam), c_int(lParam))

    GWL_WNDPROC = ctypes.c_int(-4)
    new_window_procedure = WNDPROCTYPE(process_message)
    _REGISTERED_PROCEDURES_REFS.append(new_window_procedure)
    prevWndProc = user32.SetWindowLongPtrA(hwnd, GWL_WNDPROC, new_window_procedure)
    if not prevWndProc:
        raise ctypes.WinError(GetLastError())


def enable_raw_input_for_window(hwnd, device_type='keyboard'):
    usage_page, usage = {  # https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/hid-architecture#hid-clients-supported-in-windows
        'keyboard': (1, 6),
        'controller': (1, 4),
        'mouse': (1, 2),
    }[device_type]
    raw_input_device = RAWINPUTDEVICE()
    raw_input_device.us_usage_page = usage_page
    raw_input_device.us_usage = usage
    raw_input_device.dw_flags = RIDEV_INPUTSINK
    raw_input_device.hwnd_target = hwnd  # 0 to follow the keyboard focus, else self.hWnd
    if not RegisterRawInputDevices(raw_input_device, 1, sizeof(RAWINPUTDEVICE)):
        raise ctypes.WinError(GetLastError())


MOUSE_BUTTONS = {
    1: ('down', 1, 'left'),
    2: ('up', 1, 'left'),
    4: ('down', 3, 'right'),
    8: ('up', 3, 'right'),
    16: ('down', 2, 'middle'),  # wheel pressed
    32: ('up', 2, 'middle'),  # wheel released
    64: ('down', 4, 'thumb1'),
    128: ('up', 4, 'thumb1'),
    256: ('down', 5, 'thumb2'),
    512: ('up', 5, 'thumb2'),
    7865344: ('wheel-up', 2, 'wheel'),  # wheel turned
    4287104000: ('wheel-down', 2, 'wheel')  # wheel turned
}

KEY_EVENT_TYPE = {256: 'down', 257: 'up', 260: 'down'}  # 260 for multi-key-down (alt gr)


@dataclass
class InputEvent:
    event_type: str  # 'up'/'down' for buttons, 'move' for mouse
    code: int  # button index or scan code
    name: Optional[str]  # mouse button or key name
    device_type: str  # 'keyboard', 'keypad', 'mouse', 'controller'
    device_id: int
    delta_x: Optional[int]  # mouse movement
    delta_y: Optional[int]  # mouse movement
    hwnd: int  # window id


def hook_raw_input_for_window(hwnd,
                              callback: Callable[[InputEvent], None],
                              device_types=('keyboard', 'mouse', 'controller')):
    """
    Listen to raw input events sent to a window by the operating system (Windows).

    This is implemented by overriding the window's procedure function which is the only function that receives raw input events.
    The new procedure calls the callback before executing the regular window procedure.

    The HWND can be retrieved from a TK instance using `window.winfo_id()` and similar functions exist for other libraries.

    Args:
        hwnd: Window id (HWND)
        callback: Function
        device_types: Types of devices to listen for. Supports 'keyboard' and 'mouse'.
    """
    def process_message(hwnd, msg, wParam, lParam):  # Called by Windows to handle window events.
        if msg == WM_INPUT:  # raw input. other events don't reference the device
            dwSize = c_uint()
            if user32.GetRawInputData(lParam, RID_INPUT, NULL, byref(dwSize), sizeof(RAWINPUTHEADER)):
                raise ctypes.WinError(GetLastError())
            if dwSize.value == 40:  # Keyboard
                raw = RAWINPUT()
                assert user32.GetRawInputData(lParam, RID_INPUT, byref(raw), byref(dwSize), sizeof(RAWINPUTHEADER)) == dwSize.value
                message = raw.data.keyboard.message
                vk_code = raw.data.keyboard.vk_code
                scan_code = raw.data.keyboard.scan_code
                # flags = raw.data.keyboard.flags
                if vk_code in VIRTUAL_KEYBOARD:
                    key_name, is_keypad = VIRTUAL_KEYBOARD[vk_code]
                else:
                    key_name, is_keypad = KEY_NAMES_LOWER[scan_code], False
                evt_type = KEY_EVENT_TYPE[message]
                callback(InputEvent(evt_type, scan_code, key_name, 'keypad' if is_keypad else 'keyboard', raw.header.hDevice, None, None, hwnd))
            elif dwSize.value == 48:  # Mouse
                raw = RAWINPUT()
                assert user32.GetRawInputData(lParam, RID_INPUT, byref(raw), byref(dwSize), sizeof(RAWINPUTHEADER)) == dwSize.value
                button = raw.data.mouse.ulButtons
                if button == 0:
                    callback(InputEvent('move', -1, None, 'mouse', raw.header.hDevice, raw.data.mouse.lLastX, raw.data.mouse.lLastY, hwnd))
                else:
                    evt_type, button_id, button_name = MOUSE_BUTTONS[button]
                    callback(InputEvent(evt_type, button_id, button_name, 'mouse', raw.header.hDevice, None, None, hwnd))
            else:
                raise NotImplementedError

    set_window_procedure(hwnd, process_message, call_original=True)
    for device_type in device_types:
        enable_raw_input_for_window(hwnd, device_type)


if __name__ == '__main__':
    from threading import Thread
    from time import sleep

    HWND = None

    def open_window():
        import tkinter as tk
        window = tk.Tk()
        window.title("Keyboard ID")
        window.geometry('400x200')
        inputtxt = tk.Text(window, height=5, width=20)
        inputtxt.pack()
        label = tk.Label(text="This is a window.")
        label.pack()
        global HWND
        HWND = window.winfo_id()
        window.mainloop()

    Thread(target=open_window).start()
    sleep(1)
    hook_raw_input_for_window(HWND, lambda e: print(e))
