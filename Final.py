#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---- Muudetavad algväärtused (lävi ja taimer) ----
target_force   = 150.0   # N — Y väärtus; kui force_n > target_force -> alustab loendurit
TIMER_SECONDS  = 10      # s — loenduri pikkus

import argparse, struct, time, sys
from smbus2 import SMBus
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

REG_CMD   = 0x22
REG_PRESS = 0x30
REG_STAT  = 0x32

# -------------------- EDIT HERE: conversion logic --------------------
# Full-scale mapping for pressure (bar). counts in [-16000 .. +16000]
# Provide your sensor's actual range with --fs min:max  (e.g. 0:200)
def counts_to_bar(counts: int, fs_min_bar: float, fs_max_bar: float) -> float:
    # Linear map: fs_min -> -16000, fs_max -> +16000
    return (counts + 16000) * ((fs_max_bar - fs_min_bar) / 32000.0)

# Force conversion. Requirement: 3.3 bar -> 1500 N  (linear).
# You can change N_PER_BAR or add offsets if needed.
N_PER_BAR = 1500.0 / 3.3  # ≈ 454.545 N per bar
ZERO_FORCE_OFFSET_N = 0.0 # fixed offset after conversion if needed

def bar_to_newtons(pressure_bar: float) -> float:
    return pressure_bar * N_PER_BAR + ZERO_FORCE_OFFSET_N
# --------------------------------------------------------------------

def read_s16_be(bus: SMBus, addr: int, reg: int) -> int:
    raw = bus.read_word_data(addr, reg)  # smbus returns LE word
    val_be = struct.unpack('<H', struct.pack('<H', raw))[0]
    return struct.unpack('<h', struct.pack('<H', val_be))[0]

def read_u16_be(bus: SMBus, addr: int, reg: int) -> int:
    raw = bus.read_word_data(addr, reg)
    return struct.unpack('<H', struct.pack('<H', raw))[0]

def write_u16_be(bus: SMBus, addr: int, reg: int, value: int) -> None:
    msb, lsb = (value >> 8) & 0xFF, value & 0xFF
    bus.write_i2c_block_data(addr, reg, [msb, lsb])

class PTE7300Gui:
    def __init__(self, busnum: int, addr: int, interval_ms: int, fs_min: float, fs_max: float):
        self.busnum   = busnum
        self.addr     = addr
        self.interval = max(50, interval_ms)  # ms
        self.fs_min   = fs_min
        self.fs_max   = fs_max
        self.bus      = SMBus(self.busnum)

        # Device init
        self._reset()
        time.sleep(0.005)
        self._start()

        # ---- GUI (täisekraan + skaleeruv tekst) ----
        self.root = tk.Tk()
        self.root.title("PTE7300 → Newtons")
        self.root.attributes("-fullscreen", True)
        self.fullscreen = True
        self.root.bind("<F11>", self._toggle_fullscreen)
        self.root.bind("<Escape>", self._exit_fullscreen)

        # Timer state
        self.countdown_remaining = 0
        self.countdown_job = None

        # Colors
        self.default_bg = self.root.cget("bg")

        # Fonts (will be resized dynamically)
        self.font_force = tkfont.Font(family="Helvetica", size=56, weight="bold")
        self.font_timer = tkfont.Font(family="Helvetica", size=36)
        self.font_info  = tkfont.Font(family="Helvetica", size=14)

        # Layout
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.wrapper = tk.Frame(self.root, bg=self.default_bg, padx=20, pady=20)
        self.wrapper.grid(row=0, column=0, sticky="nsew")

        # Rows: [force big][timer][info/status]
        for r in range(3):
            self.wrapper.rowconfigure(r, weight=1)
        self.wrapper.columnconfigure(0, weight=1)

        # BIG force label (no "X =")
        self.lbl_force = tk.Label(self.wrapper, text="--", font=self.font_force,
                                  anchor="center", bg=self.default_bg)
        self.lbl_force.grid(row=0, column=0, sticky="nsew", pady=(10, 0))

        # Timer (hidden until active)
        self.lbl_timer = tk.Label(self.wrapper, text="", font=self.font_timer,
                                  anchor="center", bg=self.default_bg)
        self.lbl_timer.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.lbl_timer.grid_remove()

        # Info line(s)
        info_frame = tk.Frame(self.wrapper, bg=self.default_bg)
        info_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        info_frame.columnconfigure(0, weight=1)

        self.lbl_status = tk.Label(info_frame, text="STATUS: --", font=self.font_info, anchor="w", bg=self.default_bg)
        self.lbl_raw    = tk.Label(info_frame, text="RAW: --",     font=self.font_info, anchor="w", bg=self.default_bg)
        self.lbl_bar    = tk.Label(info_frame, text="PRESSURE: -- bar", font=self.font_info, anchor="w", bg=self.default_bg)
        self.lbl_thr    = tk.Label(info_frame, text=f"TARGET: {target_force:.1f} N", font=self.font_info, anchor="w", bg=self.default_bg)

        self.lbl_status.grid(row=0, column=0, sticky="w")
        self.lbl_raw.grid(   row=1, column=0, sticky="w")
        self.lbl_bar.grid(   row=2, column=0, sticky="w")
        self.lbl_thr.grid(   row=3, column=0, sticky="w")

        # Resize hook for dynamic font scaling
        self.root.bind("<Configure>", self._on_resize)
        self.root.after(50, self._on_resize)

        # Start periodic updates
        self._schedule_next()

    # -------- Device control --------
    def _schedule_next(self):
        self.root.after(self.interval, self.update_once)

    def _reset(self):
        write_u16_be(self.bus, self.addr, REG_CMD, 0xB169)

    def _start(self):
        write_u16_be(self.bus, self.addr, REG_CMD, 0x8B93)

    def _idle(self):
        write_u16_be(self.bus, self.addr, REG_CMD, 0x7BBA)

    def _sleep(self):
        write_u16_be(self.bus, self.addr, REG_CMD, 0x6C32)

    def _reset_then_start(self):
        self._reset()
        time.sleep(0.005)
        self._start()

    # -------- UI helpers --------
    def _set_bg(self, color: str):
        self.root.configure(bg=color)
        self.wrapper.configure(bg=color)
        self.lbl_force.configure(bg=color)
        self.lbl_timer.configure(bg=color)
        self.lbl_status.configure(bg=color)
        self.lbl_raw.configure(bg=color)
        self.lbl_bar.configure(bg=color)
        self.lbl_thr.configure(bg=color)

    def _reset_bg(self):
        self._set_bg(self.default_bg)

    def _on_resize(self, event=None):
        w = max(self.root.winfo_width(), 1)
        h = max(self.root.winfo_height(), 1)
        short = min(w, h)
        # Force number prominent, timer smaller, info compact
        size_force = max(24, int(short * 0.12))
        size_timer = max(18, int(short * 0.08))
        size_info  = max(12, int(short * 0.035))
        self.font_force.configure(size=size_force)
        self.font_timer.configure(size=size_timer)
        self.font_info.configure(size=size_info)

    def _toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def _exit_fullscreen(self, event=None):
        self.fullscreen = False
        self.root.attributes("-fullscreen", False)

    # -------- Timer logic --------
    def _start_countdown(self, seconds: int):
        self._reset_bg()  # just in case previous cycle was green
        self.countdown_remaining = int(seconds)
        self.lbl_timer.config(text=f"{self.countdown_remaining} s")
        self.lbl_timer.grid()  # show timer
        self._tick()

    def _tick(self):
        self.lbl_timer.config(text=f"{self.countdown_remaining} s")
        if self.countdown_remaining <= 0:
            self.countdown_job = None
            self._set_bg("green")
            return
        self.countdown_remaining -= 1
        self.countdown_job = self.root.after(1000, self._tick)

    def _stop_countdown(self):
        if self.countdown_job is not None:
            self.root.after_cancel(self.countdown_job)
            self.countdown_job = None
        self.countdown_remaining = 0
        self.lbl_timer.grid_remove()
        self._reset_bg()

    # -------- Data update --------
    def update_once(self):
        try:
            # on-demand measurement
            self._start()
            time.sleep(0.003)

            status = read_u16_be(self.bus, self.addr, REG_STAT)
            raw    = read_s16_be(self.bus, self.addr, REG_PRESS)
            p_bar  = counts_to_bar(raw, self.fs_min, self.fs_max)
            force_n = bar_to_newtons(p_bar)  # <-- X

            # Update GUI
            # Force value big (no "X="), show 0.1 N resolution
            self.lbl_force.config(text=f"{force_n:.1f} N")
            self.lbl_status.config(text=f"STATUS: 0x{status:04X}")
            self.lbl_raw.config(text=f"RAW: {raw:+d}")
            self.lbl_bar.config(text=f"PRESSURE: {p_bar:.3f} bar")

            # Threshold logic
            if force_n > target_force:
                if self.countdown_job is None and self.countdown_remaining == 0:
                    self._start_countdown(TIMER_SECONDS)
            else:
                self._stop_countdown()

        except Exception as e:
            self.lbl_status.config(text=f"ERROR: {e}")
        finally:
            self._schedule_next()

    def on_close(self):
        try:
            self.bus.close()
        except:
            pass
        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

def parse_args():
    ap = argparse.ArgumentParser(description="PTE7300 GUI reader → Newtons (fullscreen)")
    ap.add_argument("--bus", type=int, default=0, help="I2C bus number (e.g. 0 or 1). Default 0.")
    ap.add_argument("--addr", type=lambda x: int(x,0), default=0x6c,
                    help="7-bit I2C address (default 0x6c for no-CRC; CRC addr is 0x6d).")
    ap.add_argument("--interval", type=int, default=500, help="Update interval in ms (default 500).")
    ap.add_argument("--fs", type=str, default="0:40",
                    help="Full-scale range in bar as min:max (e.g. 0:200). Default 0:40.")
    args = ap.parse_args()

    try:
        fs_min, fs_max = map(float, args.fs.split(":"))
    except Exception:
        print("Bad --fs format, expected like 0:40", file=sys.stderr)
        sys.exit(2)

    return args.bus, args.addr, args.interval, fs_min, fs_max

if __name__ == "__main__":
    bus, addr, interval, fs_min, fs_max = parse_args()
    app = PTE7300Gui(bus, addr, interval, fs_min, fs_max)
    app.run()
