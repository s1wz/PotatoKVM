#!/usr/bin/env python3
"""
hi

Optimizations & Timing:
  - FADE_STEPS = 30 @ 30 TARGET_FPS guarantees each fade takes exactly 1.0 second.
  - Boot logo static hold time reduced to 1.5 seconds.
  - Total boot sequence duration tightly capped under 4 seconds (~3.5s total execution).
"""

import sys
sys.path.insert(0, "/opt/lepotato-gpio")

import time
import socket
import os
import requests
import spidev
import gpiod
import numpy as np
from gpiod.line import Direction, Value
from PIL import Image, ImageDraw, ImageFont
from requests.auth import HTTPBasicAuth

SCREEN_WIDTH  = 320
SCREEN_HEIGHT = 172

COL_OFFSET = 0
ROW_OFFSET = 34

GPIO_CHIP = "/dev/gpiochip1"
DC_LINE   = 94
RST_LINE  = 79

BLACK      = (0,   0,   0)
WHITE      = (255, 255, 255)
SOFT_WHITE = (220, 225, 230)
MUTED      = (150, 157, 165)
GREEN      = (0,   232, 132)
RED        = (255, 72,  72)
YELLOW     = (255, 203, 56)
CARD_BG    = (15,  18,  20)

UPDATE_INTERVAL = 2

PIKVM_STREAM_URL  = "http://192.168.3.228/streamer/state"
PIKVM_HID_URL     = "http://192.168.3.228/api/hid"
API_AUTH          = HTTPBasicAuth("admin", "admin")

BOOT_IMAGE_PATH   = "/home/ubuntu/sjwz.png"
GITHUB_AVATAR_URL = "https://avatars.githubusercontent.com/u/139400125?v=4"

# ══════════════════════════════════════════
# Fonts
# ══════════════════════════════════════════
def fnt(size, bold=False, mono=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    ] if mono else [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    for p in candidates:
        try:    return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()

TEXT_AA_SCALE = 3

def draw_text_aa(canvas, xy, value, size, fill, bold=False, mono=False, anchor=None, shadow=False):
    x, y  = int(xy[0]), int(xy[1])
    font  = fnt(size * TEXT_AA_SCALE, bold=bold, mono=mono)
    dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    dd    = ImageDraw.Draw(dummy)
    bbox  = dd.textbbox((0, 0), value, font=font)
    w     = max(1, bbox[2] - bbox[0] + 18 * TEXT_AA_SCALE)
    h     = max(1, bbox[3] - bbox[1] + 18 * TEXT_AA_SCALE)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld    = ImageDraw.Draw(layer)
    tx    = 9 * TEXT_AA_SCALE - bbox[0]
    ty    = 9 * TEXT_AA_SCALE - bbox[1]
    if shadow:
        ld.text((tx + TEXT_AA_SCALE, ty + TEXT_AA_SCALE), value, font=font, fill=(0, 0, 0, 120))
    ld.text((tx, ty), value, font=font, fill=fill + (255,) if len(fill) == 3 else fill)
    layer = layer.resize((max(1, w // TEXT_AA_SCALE), max(1, h // TEXT_AA_SCALE)), Image.LANCZOS)
    if anchor == "center": x -= layer.width  // 2
    elif anchor == "right": x -= layer.width
    canvas.paste(layer, (x - 3, y - 3), layer)
    return layer.width, layer.height

# ══════════════════════════════════════════
# Vector Icons
# ══════════════════════════════════════════
def draw_ethernet_icon(canvas, x, y, color):
    d = ImageDraw.Draw(canvas)
    d.rectangle((x, y + 4, x + 12, y + 12), outline=color, width=1)
    d.rectangle((x + 4, y, x + 8, y + 4), fill=color)
    d.line((x + 3, y + 7, x + 3, y + 10), fill=color)
    d.line((x + 6, y + 7, x + 6, y + 10), fill=color)
    d.line((x + 9, y + 7, x + 9, y + 10), fill=color)

def draw_card_icon(canvas, name, cx, cy, color):
    d = ImageDraw.Draw(canvas)
    if name == "temp":
        d.rectangle((cx - 2, cy - 8, cx + 2, cy + 2), fill=color)
        d.ellipse((cx - 4, cy + 1, cx + 4, cy + 9), fill=color)
    elif name == "storage":
        d.rounded_rectangle((cx - 8, cy - 7, cx + 8, cy - 2), radius=1, outline=color, width=1)
        d.ellipse((cx - 6, cy - 5, cx - 4, cy - 3), fill=color)
        d.rounded_rectangle((cx - 8, cy - 1, cx + 8, cy + 4), radius=1, outline=color, width=1)
        d.ellipse((cx - 6, cy + 1, cx - 4, cy + 3), fill=color)
        d.rounded_rectangle((cx - 8, cy + 5, cx + 8, cy + 10), radius=1, outline=color, width=1)
        d.ellipse((cx - 6, cy + 7, cx - 4, cy + 9), fill=color)
    elif name == "usb":
        d.rounded_rectangle((cx - 9, cy - 5, cx + 9, cy + 5), radius=2, outline=color, width=1)
        d.rectangle((cx - 5, cy - 2, cx - 1, cy + 2), fill=color)
        d.rectangle((cx + 1, cy - 2, cx + 5, cy + 2), fill=color)
    elif name == "clients":
        d.ellipse((cx - 4, cy - 6, cx, cy - 2), fill=color)
        d.chord((cx - 7, cy, cx + 3, cy + 8), 180, 360, fill=color)
        d.ellipse((cx + 1, cy - 4, cx + 4, cy - 1), fill=color)

def draw_metric_card(canvas, left, top, width, height, label, icon_name, value, value_color):
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle((left, top, left + width, top + height), radius=4, fill=CARD_BG)
    cx = left + (width // 2)
    draw_text_aa(canvas, (cx, top + 4),  label, 8,  MUTED,       bold=True, anchor="center")
    draw_card_icon(canvas, icon_name, cx, top + 24, value_color)
    draw_text_aa(canvas, (cx, top + 40), value, 14, value_color, bold=True, anchor="center")

# ══════════════════════════════════════════
# System Metrics
# ══════════════════════════════════════════
def get_system_metrics():
    clients_count   = 0
    usb_status_str  = "DISC"
    temp            = 0.0
    storage_free_gb = "0G"
    eth_connected   = False

    try:
        r = requests.get(PIKVM_STREAM_URL, auth=API_AUTH, timeout=1.2)
        if r.status_code == 200:
            clients_count = int(r.json().get("result", {}).get("stream", {}).get("clients", 0))
    except Exception:
        pass

    try:
        r = requests.get(PIKVM_HID_URL, auth=API_AUTH, timeout=1.2)
        if r.status_code == 200:
            usb_status_str = "CONN" if r.json().get("result", {}).get("mouse", {}).get("online", False) else "DISC"
    except Exception:
        pass

    for i in range(5):
        try:
            with open(f"/sys/class/thermal/thermal_zone{i}/temp") as f:
                temp = int(f.read().strip()) / 1000.0
                break
        except Exception:
            pass

    try:
        st = os.statvfs('/')
        storage_free_gb = f"{st.f_bavail * st.f_frsize / (1024**3):.1f}G"
    except Exception:
        storage_free_gb = "ERR"

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        eth_connected = not ip.startswith("127.")
    except Exception:
        ip = "NO NETWORK"

    return ip, eth_connected, clients_count, usb_status_str, temp, storage_free_gb

# ══════════════════════════════════════════
# RGB565 Encoding
# ══════════════════════════════════════════
def encode_rgb565(arr: np.ndarray) -> bytes:
    """Streamlined bit-masking logic for swift RGB565 conversion."""
    r = (arr[:, :, 0] & 0xF8).astype(np.uint16) << 8
    g = (arr[:, :, 1] & 0xFC).astype(np.uint16) << 3
    b = (arr[:, :, 2] >> 3).astype(np.uint16)
    return (r | g | b).astype(">u2").tobytes()

# ══════════════════════════════════════════
# SPI Push
# ══════════════════════════════════════════
def _set_window(spi, req, x0, y0, x1, y1):
    cmd(spi, req, 0x2A); dat(spi, req, [x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
    cmd(spi, req, 0x2B); dat(spi, req, [y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
    cmd(spi, req, 0x2C)
    set_dc(req, 1)

def push_bytes_full(spi, req, frame_bytes: bytes):
    """Send a full-resolution (320×172) pre-encoded frame."""
    _set_window(spi, req,
                COL_OFFSET,            ROW_OFFSET,
                COL_OFFSET + SCREEN_WIDTH  - 1,
                ROW_OFFSET + SCREEN_HEIGHT - 1)
    spi.writebytes2(frame_bytes)

def push_array_full(spi, req, rgb_array: np.ndarray):
    push_bytes_full(spi, req, encode_rgb565(rgb_array))

# ══════════════════════════════════════════
# Smooth Fade (Optimized Full Resolution)
# ══════════════════════════════════════════
FADE_STEPS    = 30      # 30 frames total
TARGET_FPS    = 30      # 30 frames per second = exactly 1.0s duration per fade
_FRAME_BUDGET = 1.0 / TARGET_FPS          

def smooth_fade(spi, req, from_array, to_array):
    """
    Fade from_array → to_array over FADE_STEPS frames at TARGET_FPS.
    Uses pre-allocated arrays and in-place addition to minimize GC churn.
    """
    src = from_array.astype(np.int16) if from_array is not None else np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH, 3), dtype=np.int16)
    dst = to_array.astype(np.int16)   if to_array   is not None else np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH, 3), dtype=np.int16)
    diff = dst - src  

    t = np.linspace(0.0, 1.0, FADE_STEPS, endpoint=True)
    alpha_ints = (t * t * (3.0 - 2.0 * t) * 256).astype(np.int32)

    # Pre-allocate output buffer to avoid thrashing CPU memory allocations
    frame_buffer = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH, 3), dtype=np.uint8)

    for a_int in alpha_ints:
        t_start = time.perf_counter()

        # In-place addition directly into the pre-allocated frame buffer
        np.add(src, ((diff * a_int) >> 8), out=frame_buffer, casting='unsafe')
        push_array_full(spi, req, frame_buffer)

        # Pace to TARGET_FPS
        elapsed = time.perf_counter() - t_start
        remaining = _FRAME_BUDGET - elapsed
        if remaining > 0:
            time.sleep(remaining)

# ══════════════════════════════════════════
# Boot Splash
# ══════════════════════════════════════════
def show_boot_image(spi, req):
    try:
        if not os.path.exists(BOOT_IMAGE_PATH):
            print("[*] sjwz.png not found locally. Attempting download...")
            try:
                r = requests.get(GITHUB_AVATAR_URL, timeout=5)
                if r.status_code == 200:
                    with open(BOOT_IMAGE_PATH, "wb") as f:
                        f.write(r.content)
            except Exception as e:
                print(f"[*] Download error: {e}")

        canvas = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), BLACK + (255,))

        if os.path.exists(BOOT_IMAGE_PATH):
            logo = Image.open(BOOT_IMAGE_PATH).convert("RGBA")
            max_h     = 120
            new_w     = int(logo.size[0] * max_h / logo.size[1])
            logo      = logo.resize((new_w, max_h), Image.Resampling.LANCZOS)
            canvas.paste(logo, ((SCREEN_WIDTH - logo.width) // 2, (SCREEN_HEIGHT - logo.height) // 2), logo)
        else:
            draw_text_aa(canvas, (SCREEN_WIDTH // 2, 55), "PiKVM SYSTEM",    24, WHITE, bold=True, anchor="center")
            draw_text_aa(canvas, (SCREEN_WIDTH // 2, 95), "INITIALIZING...", 11, GREEN, bold=True, anchor="center")

        logo_array = np.array(canvas.convert("RGB"), dtype=np.uint8)

        # Phase 1: Fade-In (1.0 Second)
        print(f"[*] Boot fade-in  ({FADE_STEPS} frames @ {TARGET_FPS} FPS = 1.0s)...")
        smooth_fade(spi, req, from_array=None, to_array=logo_array)

        # Phase 2: Static Hold (1.5 Seconds)
        push_array_full(spi, req, logo_array)
        time.sleep(1.5)

        # Phase 3: Fade-Out (1.0 Second)
        print(f"[*] Boot fade-out ({FADE_STEPS} frames @ {TARGET_FPS} FPS = 1.0s)...")
        smooth_fade(spi, req, from_array=logo_array, to_array=None)

    except Exception as e:
        print(f"[-] Boot image error: {e}")

# ══════════════════════════════════════════
# UI Screen
# ══════════════════════════════════════════
def draw_screen(ip, eth_connected, clients_count, usb_status_str, temp, storage_free_gb):
    img = Image.new("RGBA", (SCREEN_WIDTH, SCREEN_HEIGHT), BLACK + (255,))

    draw_ethernet_icon(img, 16, 12, WHITE if eth_connected else RED)
    draw_text_aa(img, (SCREEN_WIDTH - 16, 9), time.strftime("%H:%M:%S"), 14, SOFT_WHITE, bold=True, anchor="right", mono=True)
    draw_text_aa(img, (SCREEN_WIDTH // 2, 38), ip, 26 if len(ip) <= 15 else 20, WHITE, bold=True, anchor="center")

    card_y   = 96
    card_h   = 62
    card_w   = 68
    gap      = 8
    margin_x = (SCREEN_WIDTH - (card_w * 4 + gap * 3)) // 2

    draw_metric_card(img, margin_x + 0*(card_w+gap), card_y, card_w, card_h, "TEMP",    "temp",    f"{temp:.0f}°C",    RED if temp > 75 else YELLOW if temp > 60 else GREEN)
    draw_metric_card(img, margin_x + 1*(card_w+gap), card_y, card_w, card_h, "STORAGE", "storage", storage_free_gb,   SOFT_WHITE)
    draw_metric_card(img, margin_x + 2*(card_w+gap), card_y, card_w, card_h, "USB",     "usb",     usb_status_str,     GREEN if usb_status_str == "CONN" else RED)
    draw_metric_card(img, margin_x + 3*(card_w+gap), card_y, card_w, card_h, "CLIENTS", "clients", f"{clients_count}", GREEN if clients_count > 0 else YELLOW)

    return img.convert("RGB")

# ══════════════════════════════════════════
# ST7789 Low-Level Drivers
# ══════════════════════════════════════════
def set_dc(req, val):
    req.set_value(DC_LINE, Value.ACTIVE if val else Value.INACTIVE)

def set_rst(req, val):
    req.set_value(RST_LINE, Value.ACTIVE if val else Value.INACTIVE)

def cmd(spi, req, val):
    set_dc(req, 0); spi.writebytes([val])

def dat(spi, req, data):
    set_dc(req, 1); spi.writebytes(data if isinstance(data, list) else [data])

def init_display(spi, req):
    set_rst(req, 1); time.sleep(0.1)
    set_rst(req, 0); time.sleep(0.1)
    set_rst(req, 1); time.sleep(0.2)
    cmd(spi, req, 0x01); time.sleep(0.15)
    cmd(spi, req, 0x11); time.sleep(0.5)
    cmd(spi, req, 0x3A); dat(spi, req, 0x55)
    cmd(spi, req, 0x36); dat(spi, req, 0x70)
    cmd(spi, req, 0x21)
    cmd(spi, req, 0x29); time.sleep(0.1)
    print("[+] ST7789 Display Initialised.")

# ══════════════════════════════════════════
# Main
# ══════════════════════════════════════════
def main():
    print("[*] Opening GPIO...")
    req = gpiod.request_lines(
        GPIO_CHIP,
        consumer="pikvm-dashboard-v2",
        config={
            DC_LINE:  gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
            RST_LINE: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
        }
    )

    print("[*] Opening SPI @ 80 MHz...")
    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz = 80_000_000
    spi.mode = 0

    init_display(spi, req)

    # Wipe VRAM before boot logo
    push_bytes_full(spi, req, bytes(SCREEN_HEIGHT * SCREEN_WIDTH * 2))

    show_boot_image(spi, req)

    print("[*] Fetching initial metrics...")
    ip, eth_connected, clients_count, usb_status_str, temp, storage_free_gb = get_system_metrics()
    first_ui = np.array(draw_screen(ip, eth_connected, clients_count, usb_status_str, temp, storage_free_gb), dtype=np.uint8)

    print(f"[*] Fade-in to dashboard ({FADE_STEPS} frames @ {TARGET_FPS} FPS = 1.0s)...")
    smooth_fade(spi, req, from_array=None, to_array=first_ui)

    push_array_full(spi, req, first_ui)

    print("[*] Entering dashboard loop...")
    try:
        while True:
            ip, eth_connected, clients_count, usb_status_str, temp, storage_free_gb = get_system_metrics()
            img = draw_screen(ip, eth_connected, clients_count, usb_status_str, temp, storage_free_gb)
            push_array_full(spi, req, np.array(img))
            time.sleep(UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
    finally:
        spi.close()
        req.release()

if __name__ == "__main__":
    main()