#!/usr/bin/env python3
# PTE7300 quick GUI reader -> Newtons
# - Opens a small Tkinter GUI, shows Raw counts, Pressure (bar) and Force (N)
# - No console interaction needed after start
# - Bus/address/interval/full-scale are CLI args (see --help)
#
# >>> EDIT HERE section <<<  for easy conversion tweaking:
#   counts_to_bar() and bar_to_newtons() can be adjusted for your calibration.

import argparse, struct, time, sys
from smbus2 import SMBus
import tkinter as tk

REG_CMD   = 0x22
REG_PRESS = 0x30
REG_STAT  = 0x32

# -------------------- EDIT HERE: conversion logic --------------------
# Full-scale mapping for pressure (bar). counts in [-16000 .. +16000]
# Provide your sensor's actual range with --fs min:max  (e.g. 0:200)
def counts_to_bar(counts: int, fs_min_bar: float, fs_max_bar: float) -> float:
    # Linear map: fs_min -> -16000, fs_max -> +16000
    return  (counts+16000) * ((fs_max_bar - fs_min_bar) / 32000.0)

# Force conversion. Requirement: 3.3 bar -> 1500 N  (linear).
# You can change N_PER_BAR or add offsets if needed.
N_PER_BAR = 1500.0 / 3.3  # ≈ 454.545 N per bar
ZERO_FORCE_OFFSET_N =0.0 # add/subtract a fixed offset after conversion if you like

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
        self.busnum = busnum
        self.addr = addr
        self.interval = max(50, interval_ms)  # avoid too-fast refresh
        self.fs_min = fs_min
        self.fs_max = fs_max
        self.bus = SMBus(self.busnum)

        # Soft reset + tiny wait, then do a first start
        self._reset()
        time.sleep(0.005)
        self._start()

        # Build GUI
        self.root = tk.Tk()
        self.root.title("PTE7300 → Newtons")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        font_h = ("TkDefaultFont", 16, "bold")
        font_b = ("TkDefaultFont", 13)
        pad = {"padx": 10, "pady": 6}

        self.lbl_status = tk.Label(self.root, text="STATUS: --", font=font_b)
        self.lbl_raw    = tk.Label(self.root, text="RAW: --",    font=font_b)
        self.lbl_bar    = tk.Label(self.root, text="PRESSURE: -- bar", font=font_h)
        self.lbl_n      = tk.Label(self.root, text="FORCE: -- N",      font=font_h)

        self.lbl_status.grid(row=0, column=0, sticky="w", **pad)
        self.lbl_raw.grid(   row=1, column=0, sticky="w", **pad)
        self.lbl_bar.grid(   row=2, column=0, sticky="w", **pad)
        self.lbl_n.grid(     row=3, column=0, sticky="w", **pad)

        self.btn_frame = tk.Frame(self.root)
        self.btn_frame.grid(row=4, column=0, sticky="w", **pad)

        self.btn_start = tk.Button(self.btn_frame, text="Start", command=self._start)
        self.btn_idle  = tk.Button(self.btn_frame, text="Idle",  command=self._idle)
        self.btn_sleep = tk.Button(self.btn_frame, text="Sleep", command=self._sleep)
        self.btn_reset = tk.Button(self.btn_frame, text="Reset", command=self._reset_then_start)

        self.btn_start.grid(row=0, column=0, **pad)
        self.btn_idle.grid( row=0, column=1, **pad)
        self.btn_sleep.grid(row=0, column=2, **pad)
        self.btn_reset.grid(row=0, column=3, **pad)

        # Kick off periodic updates
        self._schedule_next()

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

    def update_once(self):
        try:
            # start a new measurement every cycle (on-demand)
            self._start()
            time.sleep(0.003)  # tiny wait

            status = read_u16_be(self.bus, self.addr, REG_STAT)
            raw = read_s16_be(self.bus, self.addr, REG_PRESS)
            p_bar = counts_to_bar(raw, self.fs_min, self.fs_max)
            force_n = bar_to_newtons(p_bar)

            self.lbl_status.config(text=f"STATUS: 0x{status:04X}")
            self.lbl_raw.config(text=f"RAW: {raw:+d}")
            self.lbl_bar.config(text=f"PRESSURE: {p_bar:.3f} bar")
            self.lbl_n.config(text=f"FORCE: {force_n:.1f} N")
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
        self.root.mainloop()

def parse_args():
    ap = argparse.ArgumentParser(description="PTE7300 GUI reader → Newtons")
    ap.add_argument("--bus", type=int, default=0, help="I2C bus number (e.g. 0 or 1). Default 1.")
    ap.add_argument("--addr", type=lambda x: int(x,0), default=0x6c,
                    help="7-bit I2C address (default 0x6c for no-CRC; CRC addr is 0x6d).")
    ap.add_argument("--interval", type=int, default=500, help="Update interval in ms (default 500).")
    ap.add_argument("--fs", type=str, default="0:40",
                    help="Full-scale range in bar as min:max (e.g. 0:200). Default 0:200.")
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
