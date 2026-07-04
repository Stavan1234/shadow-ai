import os
import json
import time
import threading
import webview
import win32api
import win32con
import win32gui
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATUS_FILE = PROJECT_ROOT / "data" / "status.json"
BUBBLE_HTML = PROJECT_ROOT / "src" / "overlay" / "bubble.html"

def poll_status(window):
    """Poll data/status.json and update the webview state accordingly."""
    last_state = None
    while True:
        try:
            if STATUS_FILE.exists():
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    state = data.get("state", "ASLEEP")
                    if state != last_state:
                        # Evaluate JS function in bubble.html
                        window.evaluate_js(f"updateBubbleState('{state}')")
                        last_state = state
        except Exception:
            # Silently ignore read/write lock collisions on status.json
            pass
        time.sleep(0.2)

def force_windows_transparency(window):
    """
    Directly manipulate the OS window handle (HWND) using the Win32 API.
    Enables WS_EX_LAYERED and sets the color key for absolute transparency.
    """
    hwnd = None
    # Retry loop to allow the window handle to be instantiated by the OS
    for _ in range(20):
        hwnd = win32gui.FindWindow(None, window.title)
        if hwnd:
            break
        time.sleep(0.1)

    if hwnd:
        print(f"[Overlay] HWND resolved: {hwnd}. Applying transparency key...")
        # Get current window style and add WS_EX_LAYERED + WS_EX_TOPMOST
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(
            hwnd,
            win32con.GWL_EXSTYLE,
            ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST
        )
        # Chroma-key the color black (0, 0, 0) as transparent
        win32gui.SetLayeredWindowAttributes(
            hwnd,
            win32api.RGB(0, 0, 0),
            255,
            win32con.LWA_COLORKEY
        )

def main():
    # Retrieve screen resolution dynamically using pywin32
    try:
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    except Exception:
        # Fallback to standard 1080p resolution coordinates
        screen_w = 1920
        screen_h = 1080

    # Overlay specifications
    window_w = 140
    window_h = 140
    
    # Position in bottom-right corner
    x_pos = screen_w - window_w - 20
    y_pos = screen_h - window_h - 60  # Shift up slightly to clear the taskbar

    # Load HTML code directly to ensure WebView2 renders inline
    html_content = ""
    try:
        with open(BUBBLE_HTML, "r", encoding="utf-8") as f:
            html_content = f.read()
    except Exception as e:
        print(f"[Overlay Error] Failed to read HTML file: {e}")
        html_content = "<html><body style='background:black;color:white;'>Error</body></html>"

    # Create frameless, transparent, on-top window
    window = webview.create_window(
        "S.H.A.D.O.W.",
        html=html_content,
        width=window_w,
        height=window_h,
        x=x_pos,
        y=y_pos,
        frameless=True,
        on_top=True,
        transparent=False
    )

    # Start status polling thread
    t = threading.Thread(target=poll_status, args=(window,), daemon=True)
    t.start()

    # Launch webview and trigger the Win32 transparency hooks when the window starts
    webview.start(force_windows_transparency, window)

if __name__ == "__main__":
    main()
