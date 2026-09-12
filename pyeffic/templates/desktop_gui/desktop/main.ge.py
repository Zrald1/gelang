"""Desktop entry point for {app_name} — thin Rust shell.

The shell owns only the window and the message loop. All rendering is
delegated to the C++ UI layer; all computation to the C++ core layer.

  Rust  — window, event loop, bounded state, input handling
  C++   — ui_draw_frame(...) rendering, factorial/fibonacci/... compute

Memory model (Rust): fixed-size scalar state, no collections that grow,
no per-frame heap allocation, ownership handles all cleanup.

Build:  python build.py --run
"""
from __future__ import annotations
from app.main import (
    mem_clamp_input, mem_step_up, mem_step_down, mem_normalize_input,
    mem_initial_input, mem_initial_result, mem_initial_op, mem_next_op,
    factorial, fibonacci, is_prime, gcd,
)

# File-scope Win32 FFI declarations for the Rust shell.
ge_preamble("rust", """
// Note: warnings are suppressed by the build (rustc -A warnings) because
// this file is generated; inner attributes cannot appear mid-file.

// === Win32 type aliases ===
type HWND = *mut std::ffi::c_void;
type HDC = *mut std::ffi::c_void;
type HINSTANCE = *mut std::ffi::c_void;
type HMENU = *mut std::ffi::c_void;
type HCURSOR = *mut std::ffi::c_void;
type HICON = *mut std::ffi::c_void;
type WPARAM = usize;
type LPARAM = isize;
type LRESULT = isize;
type UINT = u32;
type DWORD = u32;
type LONG = i32;
type BOOL = i32;
type BYTE = u8;
type ATOM = u16;

#[repr(C)]
struct RECT { left: LONG, top: LONG, right: LONG, bottom: LONG }
#[repr(C)]
struct POINT { x: LONG, y: LONG }
#[repr(C)]
struct MSG {
    hwnd: HWND,
    message: UINT,
    wParam: WPARAM,
    lParam: LPARAM,
    time: DWORD,
    pt: POINT,
}
#[repr(C)]
struct PAINTSTRUCT {
    hdc: HDC,
    fErase: BOOL,
    rcPaint: RECT,
    fRestore: BOOL,
    fIncUpdate: BOOL,
    rgbReserved: [BYTE; 32],
}
#[repr(C)]
struct WNDCLASSEXA {
    cbSize: UINT,
    style: UINT,
    lpfnWndProc: Option<unsafe extern "system" fn(HWND, UINT, WPARAM, LPARAM) -> LRESULT>,
    cbClsExtra: i32,
    cbWndExtra: i32,
    hInstance: HINSTANCE,
    hIcon: HICON,
    hCursor: HCURSOR,
    hbrBackground: *mut std::ffi::c_void,
    lpszMenuName: *const u8,
    lpszClassName: *const u8,
    hIconSm: HICON,
}

// === Win32 constants ===
const CS_HREDRAW: u32 = 2;
const CS_VREDRAW: u32 = 1;
const CW_USEDEFAULT: i32 = -2147483648;
const SW_SHOWDEFAULT: i32 = 10;
const WM_PAINT: u32 = 15;
const WM_DESTROY: u32 = 2;
const WM_KEYDOWN: u32 = 256;
const WM_CLOSE: u32 = 16;
const WM_ERASEBKGND: u32 = 20;
const VK_ESCAPE: i32 = 27;
const VK_RETURN: i32 = 13;
const VK_UP: i32 = 0x26;
const VK_DOWN: i32 = 0x28;
const VK_F: i32 = 0x46;
const VK_P: i32 = 0x50;
const VK_G: i32 = 0x47;
const WS_OVERLAPPEDWINDOW: u32 = 13565952;

// === Win32 FFI ===
extern "system" {
    fn BeginPaint(hwnd: HWND, lpPaint: *mut PAINTSTRUCT) -> HDC;
    fn EndPaint(hwnd: HWND, lpPaint: *const PAINTSTRUCT) -> BOOL;
    fn GetClientRect(hwnd: HWND, lpRect: *mut RECT) -> BOOL;
    fn InvalidateRect(hwnd: HWND, lpRect: *const RECT, bErase: BOOL) -> BOOL;
    fn RegisterClassExA(lpwcx: *const WNDCLASSEXA) -> ATOM;
    fn CreateWindowExA(dwExStyle: u32, lpClassName: *const u8, lpWindowName: *const u8,
                       dwStyle: u32, x: i32, y: i32, nWidth: i32, nHeight: i32,
                       hWndParent: HWND, hMenu: HMENU, hInstance: HINSTANCE,
                       lpParam: *mut std::ffi::c_void) -> HWND;
    fn ShowWindow(hwnd: HWND, nCmdShow: i32) -> BOOL;
    fn UpdateWindow(hwnd: HWND) -> BOOL;
    fn GetMessageA(lpMsg: *mut MSG, hwnd: HWND, wMsgFilterMin: u32, wMsgFilterMax: u32) -> BOOL;
    fn TranslateMessage(lpMsg: *const MSG) -> BOOL;
    fn DispatchMessageA(lpMsg: *const MSG) -> LRESULT;
    fn DefWindowProcA(hwnd: HWND, msg: u32, wParam: WPARAM, lParam: LPARAM) -> LRESULT;
    fn PostQuitMessage(nExitCode: i32);
    fn DestroyWindow(hwnd: HWND) -> BOOL;
    fn GetModuleHandleA(lpModuleName: *const u8) -> HINSTANCE;
    fn LoadCursorA(hInstance: HINSTANCE, lpCursorName: *const u8) -> HCURSOR;
    fn LoadIconA(hInstance: HINSTANCE, lpIconName: *const u8) -> HICON;
}

// The C++ functions this shell calls are declared automatically by
// `ge build` (mixed-backend link step), so no hand-written extern block
// is needed here.

// === Bounded state ===
static mut G_HWND: HWND = std::ptr::null_mut();
static mut G_INPUT: i64 = 10;
static mut G_RESULT: i64 = 0;
static mut G_OP: i64 = 0;

fn run_op(op: i64, input: i64) -> i64 {
    unsafe {
        match op {
            0 => factorial(input),
            1 => fibonacci(input),
            2 => is_prime(input),
            3 => gcd(input, input / 2 + 1),
            _ => 0,
        }
    }
}

unsafe extern "system" fn wnd_proc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    unsafe {
        match msg {
            WM_PAINT => {
                let mut ps: PAINTSTRUCT = std::mem::zeroed();
                let hdc = BeginPaint(hwnd, &mut ps);
                let mut rc: RECT = std::mem::zeroed();
                GetClientRect(hwnd, &mut rc);
                let w = (rc.right - rc.left) as i64;
                let h = (rc.bottom - rc.top) as i64;
                ui_draw_frame(hdc as i64, w, h, G_INPUT, G_RESULT, G_OP);
                EndPaint(hwnd, &ps);
                0
            }
            WM_ERASEBKGND => 1,
            WM_KEYDOWN => {
                let k = wparam as i32;
                if k == VK_ESCAPE {
                    DestroyWindow(hwnd);
                } else if k == VK_RETURN {
                    G_RESULT = run_op(G_OP, G_INPUT);
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                } else if k == VK_UP {
                    G_INPUT = mem_step_up(G_INPUT);
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                } else if k == VK_DOWN {
                    G_INPUT = mem_step_down(G_INPUT);
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                } else if k == VK_F {
                    G_OP = 1;
                    G_RESULT = run_op(1, G_INPUT);
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                } else if k == VK_P {
                    G_OP = 2;
                    G_RESULT = run_op(2, G_INPUT);
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                } else if k == VK_G {
                    G_OP = 3;
                    G_RESULT = run_op(3, G_INPUT);
                    InvalidateRect(hwnd, std::ptr::null(), 0);
                }
                0
            }
            WM_CLOSE => { DestroyWindow(hwnd); 0 }
            WM_DESTROY => { PostQuitMessage(0); 0 }
            _ => DefWindowProcA(hwnd, msg, wparam, lparam),
        }
    }
}
""")


@rust
def desktop_bootstrap() -> int:
    """Initialize bounded state from the memory layer."""
    ge_inline("rust", """
    unsafe {
        G_INPUT = mem_normalize_input(mem_initial_input());
        G_RESULT = mem_initial_result();
        G_OP = mem_initial_op();
    }
    return 0;
    """)
    return 0


@rust
def desktop_run() -> int:
    """Create the window and run the message loop."""
    ge_inline("rust", """
    unsafe {
    let class_name = b"GEAppWnd\0".as_ptr();
    let hinst = GetModuleHandleA(std::ptr::null());
    let wc = WNDCLASSEXA {
        cbSize: std::mem::size_of::<WNDCLASSEXA>() as u32,
        style: CS_HREDRAW | CS_VREDRAW,
        lpfnWndProc: Some(wnd_proc),
        cbClsExtra: 0,
        cbWndExtra: 0,
        hInstance: hinst,
        hIcon: LoadIconA(std::ptr::null_mut(), std::ptr::null()),
        hCursor: LoadCursorA(std::ptr::null_mut(), std::ptr::null()),
        hbrBackground: std::ptr::null_mut(),
        lpszMenuName: std::ptr::null(),
        lpszClassName: class_name,
        hIconSm: std::ptr::null_mut(),
    };
    if RegisterClassExA(&wc) == 0 { return 1; }

    let title = b"{app_name} - Rust + C++ Desktop\0".as_ptr();
    G_HWND = CreateWindowExA(0, class_name, title,
        WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 1040, 680,
        std::ptr::null_mut(), std::ptr::null_mut(), hinst, std::ptr::null_mut());
    if G_HWND.is_null() { return 1; }

    ShowWindow(G_HWND, SW_SHOWDEFAULT);
    UpdateWindow(G_HWND);

    let mut msg: MSG = std::mem::zeroed();
    while GetMessageA(&mut msg, std::ptr::null_mut(), 0, 0) > 0 {
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }
    msg.wParam as i64
    }
    """)
    return 0


def main() -> int:
    """Entry point: bootstrap state, then run the window loop."""
    desktop_bootstrap()
    return desktop_run()
