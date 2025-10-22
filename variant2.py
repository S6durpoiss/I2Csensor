#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---- Muudetavad algväärtused ----
TARGET_PRESETS   = [1500.0, 3000.0, 6000.0, 10000.0, 15000.0]  # N — valitav vasak/parem noolega
PRESET_INDEX_INIT = 1                                   # millise presetiga alustada
TIMER_SECONDS     = 10                                   # s hoideaeg enne “rohelist”
SUCCESS_HOLD_SEC  = 10                                   # s roheline ekraan pärast edu
SAMPLE_INTERVAL_MS = 80                                  # kui tihti toome ühe proovilugemi (~12.5 Hz)
DISPLAY_PERIOD_MS  = 500                                 # kui tihti arvutame keskmise ja värskendame GUI-d
OFF_CANCEL_GRACE_MS = 800                                # kui kaua peab OFF püsima, et tühistada loendur

# EVDEV pult (vasak/parem/enter/esc) – valikuline
DEVICE_PATH = "/dev/input/event6"  # muuda vastavalt

import argparse, struct, time, sys, threading, queue
from smbus2 import SMBus
import tkinter as tk
from tkinter import font as tkfont

# --- evdev on valikuline (võib puududa Windowsis vms) ---
try:
    from evdev import InputDevice, categorize, ecodes
    HAS_EVDEV = True
except Exception:
    HAS_EVDEV = False

REG_CMD   = 0x22
REG_PRESS = 0x30
REG_STAT  = 0x32

# -------------------- EDIT HERE: conversion logic --------------------
def counts_to_bar(counts: int, fs_min_bar: float, fs_max_bar: float) -> float:
    return (counts + 16000) * ((fs_max_bar - fs_min_bar) / 32000.0)

N_PER_BAR = 386  # ≈ 454.545 N/bar
ZERO_FORCE_OFFSET_N = 0.0

def bar_to_newtons(pressure_bar: float) -> float:
    return pressure_bar * N_PER_BAR + ZERO_FORCE_OFFSET_N
# --------------------------------------------------------------------

def read_s16_be(bus: SMBus, addr: int, reg: int) -> int:
    raw = bus.read_word_data(addr, reg)
    val_be = struct.unpack('<H', struct.pack('<H', raw))[0]
    return struct.unpack('<h', struct.pack('<H', val_be))[0]

def read_u16_be(bus: SMBus, addr: int, reg: int) -> int:
    raw = bus.read_word_data(addr, reg)
    return struct.unpack('<H', struct.pack('<H', raw))[0]

def write_u16_be(bus: SMBus, addr: int, reg: int, value: int) -> None:
    msb, lsb = (value >> 8) & 0xFF, value & 0xFF
    bus.write_i2c_block_data(addr, reg, [msb, lsb])

# --- EVDEV lugemine eraldi lõimes ---
def evdev_reader(devpath, q: queue.Queue):
    if not HAS_EVDEV:
        return
    try:
        dev = InputDevice(devpath)
    except Exception:
        return
    for event in dev.read_loop():
        if event.type == ecodes.EV_KEY:
            key_event = categorize(event)
            if key_event.keystate == key_event.key_down:
                code = key_event.keycode
                if code in ("KEY_LEFT","KEY_RIGHT","KEY_ENTER","KEY_ESC"):
                    q.put(code)

class PTE7300Gui:
    def __init__(self, busnum: int, addr: int, fs_min: float, fs_max: float,
                 schmitt_on: float, schmitt_off: float):
        self.bus = SMBus(busnum)
        self.addr = addr
        self.fs_min = fs_min
        self.fs_max = fs_max

        # Seadme algseadistus
        self._reset(); time.sleep(0.005); self._start()

        # Siht/Schmitt
        self.presets = TARGET_PRESETS[:]
        self.preset_index = max(0, min(PRESET_INDEX_INIT, len(self.presets)-1))
        self.target_force = self.presets[self.preset_index]
        self.schmitt_on  = schmitt_on  if schmitt_on  is not None else self.target_force
        self.schmitt_off = schmitt_off if schmitt_off is not None else max(0.0, self.target_force * 0.9)
        if self.schmitt_on <= self.schmitt_off:
            # tagame korrektsuse
            self.schmitt_on = max(self.schmitt_off + 1.0, self.schmitt_off * 1.05 or 1.0)

        # Mõõtmise puhver viimase ~0.5 s keskmiseks
        self.samples = []  # list of (timestamp, force_n)
        self.sample_lock = threading.Lock()

        # Loogika olekud
        self.trigger_state = False       # Schmitt ON/OFF
        self.timer_remaining = 0         # s
        self.timer_job = None            # after-handle
        self.off_since = None            # OFF oleku algus (grace jaoks)
        self.success_hold_job = None     # rohelise ekraani “hoidmine”
        self.success_until = 0.0         # epoch sekundites

        # GUI
        self.root = tk.Tk()
        self.root.title("PTE7300 → Newtons")
        self.root.attributes("-fullscreen", True)
        self.fullscreen = True
        self.default_bg = self.root.cget("bg")

        # fondid (skaleeritakse dünaamiliselt)
        self.font_force = tkfont.Font(family="Helvetica", size=56, weight="bold")
        self.font_timer = tkfont.Font(family="Helvetica", size=36)
        self.font_info  = tkfont.Font(family="Helvetica", size=14)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.wrapper = tk.Frame(self.root, bg=self.default_bg, padx=20, pady=20)
        self.wrapper.grid(row=0, column=0, sticky="nsew")

        for r in range(3):
            self.wrapper.rowconfigure(r, weight=1)
        self.wrapper.columnconfigure(0, weight=1)

        self.lbl_force = tk.Label(self.wrapper, text="--", font=self.font_force,
                                  anchor="center", bg=self.default_bg)
        self.lbl_force.grid(row=0, column=0, sticky="nsew", pady=(10, 0))

        self.lbl_timer = tk.Label(self.wrapper, text="", font=self.font_timer,
                                  anchor="center", bg=self.default_bg)
        self.lbl_timer.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.lbl_timer.grid_remove()

        info = tk.Frame(self.wrapper, bg=self.default_bg)
        info.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        info.columnconfigure(0, weight=1)
        self.lbl_status = tk.Label(info, text="STATUS: --", font=self.font_info, anchor="w", bg=self.default_bg)
        self.lbl_raw    = tk.Label(info, text="RAW: --",     font=self.font_info, anchor="w", bg=self.default_bg)
        self.lbl_bar    = tk.Label(info, text="PRESSURE: -- bar", font=self.font_info, anchor="w", bg=self.default_bg)
        self.lbl_thr    = tk.Label(info, text=self._thr_text(), font=self.font_info, anchor="w", bg=self.default_bg)

        self.lbl_status.grid(row=0, column=0, sticky="w")
        self.lbl_raw.grid(   row=1, column=0, sticky="w")
        self.lbl_bar.grid(   row=2, column=0, sticky="w")
        self.lbl_thr.grid(   row=3, column=0, sticky="w")

        # Sündmused
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<F11>", self._toggle_fullscreen)
        self.root.bind("<Escape>", self._exit_fullscreen)
        self.root.bind("<Configure>", self._on_resize)
        # Klaviatuuri vasak/parem presetite jaoks
        self.root.bind("<Left>",  lambda e: self._cycle_preset(-1))
        self.root.bind("<Right>", lambda e: self._cycle_preset(+1))

        # EVDEV pult
        self.q = queue.Queue()
        if HAS_EVDEV:
            t = threading.Thread(target=evdev_reader, args=(DEVICE_PATH, self.q), daemon=True)
            t.start()
            self.root.after(50, self._poll_evdev)

        # Mõõtmise taustasilmus (kiiremad proovivõtud)
        self._sample_loop()
        # Kuvamise värskendus iga 0.5s
        self.root.after(DISPLAY_PERIOD_MS, self._display_update)
        # Esmane skaleerimine
        self.root.after(50, self._on_resize)

    # ------------- Seadme käsud -------------
    def _reset(self):
        write_u16_be(self.bus, self.addr, REG_CMD, 0xB169)
    def _start(self):
        write_u16_be(self.bus, self.addr, REG_CMD, 0x8B93)

    # ------------- EVDEV sündmused -------------
    def _poll_evdev(self):
        try:
            while True:
                code = self.q.get_nowait()
                if code == "KEY_LEFT":
                    self._cycle_preset(-1)
                elif code == "KEY_RIGHT":
                    self._cycle_preset(+1)
                elif code == "KEY_ESC":
                    self.on_close()
                # KEY_ENTER – hetkel ei kasuta
        except queue.Empty:
            pass
        self.root.after(50, self._poll_evdev)

    # ------------- Presetid / läved -------------
    def _thr_text(self):
        return f"TARGET: {self.target_force:.0f} N   •   Schmitt ON/OFF: {self.schmitt_on:.0f}/{self.schmitt_off:.0f} N"

    def _cycle_preset(self, delta):
        if not self.presets:
            return
        self.preset_index = (self.preset_index + delta) % len(self.presets)
        self.target_force = self.presets[self.preset_index]
        # vaikimisi sünkroniseerime Schmitti ON uue targetiga, OFF jätame proportsionaalseks
        span = max(1.0, self.target_force * 0.1)  # 10% hüsterees vaikimisi
        self.schmitt_on  = self.target_force
        self.schmitt_off = max(0.0, self.target_force - span)
        self.lbl_thr.config(text=self._thr_text())

    # ------------- Taustamõõtmine -------------
    def _sample_loop(self):
        """Võtab ühe mõõdu (kui õnnestub) ja lisab libiseva keskmise puhvritesse."""
        try:
            self._start()
            time.sleep(0.003)  # väike ooteaeg
            status = read_u16_be(self.bus, self.addr, REG_STAT)
            raw    = read_s16_be(self.bus, self.addr, REG_PRESS)
            p_bar  = counts_to_bar(raw, self.fs_min, self.fs_max)
            force  = bar_to_newtons(p_bar)
            ts = time.time()

            # ei lase negatiivset — kärbime nullist ülespoole
            force = max(0.0, force)

            with self.sample_lock:
                self.samples.append((ts, force, status, raw, p_bar))
                # hoia umbes viimase 1.0 s andmeid (rohkem kui 0.5 s, et keskmist oleks alati võtta)
                cutoff = ts - 1.0
                while self.samples and self.samples[0][0] < cutoff:
                    self.samples.pop(0)

        except Exception as e:
            # Üksik viga: ära tee midagi; taimerit ei katkesta
            pass
        finally:
            self.root.after(SAMPLE_INTERVAL_MS, self._sample_loop)

    # ------------- Kuvamise värskendus (0.5 s) -------------
    def _display_update(self):
        now = time.time()
        avg_force = None
        status = "--"; raw = 0; p_bar = 0.0

        with self.sample_lock:
            # võta viimase 0.5 s sees olevad proovid
            window_start = now - (DISPLAY_PERIOD_MS / 1000.0)
            window = [s for s in self.samples if s[0] >= window_start]
            if window:
                forces = [s[1] for s in window]
                avg_force = sum(forces) / len(forces)
                # viimase proovi metainfo kuvamiseks
                _, _, status_last, raw_last, pbar_last = window[-1]
                status = f"0x{int(status_last):04X}"
                raw    = int(raw_last)
                p_bar  = float(pbar_last)

        # kui aknas 0.5 s polnud ühtki edukat proovi, hoia eelmisi näite; ära katkesta loogikat
        if avg_force is None:
            # jäta tekstid muutmata, ajasta uuesti
            self.root.after(DISPLAY_PERIOD_MS, self._display_update)
            return

        # ümarda sajaste kaupa
        shown = round(avg_force / 100.0) * 100.0
        self.lbl_force.config(text=f"{shown:.0f} N")
        self.lbl_status.config(text=f"STATUS: {status}")
        self.lbl_raw.config(text=f"RAW: {raw:+d}")
        self.lbl_bar.config(text=f"PRESSURE: {p_bar:.3f} bar")
        self.lbl_thr.config(text=self._thr_text())

        # Schmitti trigger
        prev_state = self.trigger_state
        if self.trigger_state:
            # olek ON; lülitu OFF ainult siis, kui keskmine on allpool OFF-läve
            if avg_force <= self.schmitt_off:
                # alusta OFF grace mõõtmist
                if self.off_since is None:
                    self.off_since = now
                # kui OFF püsib üle grace'i ja meil pole edukas roheline “hoidmine” käimas
                if (now - self.off_since) * 1000.0 >= OFF_CANCEL_GRACE_MS and not self._is_success_hold_active(now):
                    self.trigger_state = False
                    self.off_since = None
            else:
                self.off_since = None
        else:
            # olek OFF; lülitu ON, kui keskmine ületab ON-läve
            if avg_force >= self.schmitt_on:
                self.trigger_state = True
                self.off_since = None

        # Taimeri loogika
        if not prev_state and self.trigger_state:
            # läks ON -> käivita loendur ainult siis, kui parasjagu ei hoia rohelist-järgselt
            if not self._is_success_hold_active(now) and self.timer_job is None and self.timer_remaining == 0:
                self._start_timer(TIMER_SECONDS)
        elif prev_state and not self.trigger_state:
            # läks OFF -> kui loendur käib, tühista ainult siis, kui OFF püsis üle grace'i (käsitleti ülal)
            if self.timer_job is not None and self.off_since is not None:
                self._cancel_timer()

        # kui edukas roheline “hoidmine” on aktiivne ja aeg läbi, taasta taust
        if self._is_success_hold_active(now):
            # mitte midagi; roheline jääb kuni success_until
            pass
        else:
            # kui mitte roheline, hoia normaalne taust
            if self.timer_job is None and self.timer_remaining == 0:
                self._reset_bg()

        self.root.after(DISPLAY_PERIOD_MS, self._display_update)

    # ------------- Taimer / edu -------------
    def _start_timer(self, seconds: int):
        self.timer_remaining = int(seconds)
        self.lbl_timer.config(text=f"{self.timer_remaining} s")
        self.lbl_timer.grid()
        self._reset_bg()
        self._tick_timer()

    def _tick_timer(self):
        self.lbl_timer.config(text=f"{self.timer_remaining} s")
        if self.timer_remaining <= 0:
            self.timer_job = None
            self._on_success()
            return
        self.timer_remaining -= 1
        self.timer_job = self.root.after(1000, self._tick_timer)

    def _cancel_timer(self):
        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None
        self.timer_remaining = 0
        self.lbl_timer.grid_remove()

    def _on_success(self):
        # roheline ekraan + hoidmine SUCCESS_HOLD_SEC
        self._set_bg("green")
        self.lbl_timer.grid_remove()
        self.success_until = time.time() + SUCCESS_HOLD_SEC
        # planeeri kontroll, millal roheline aeg läbi (lihtne heartbeat)
        if self.success_hold_job is not None:
            self.root.after_cancel(self.success_hold_job)
        self.success_hold_job = self.root.after(200, self._success_hold_tick)

    def _success_hold_tick(self):
        now = time.time()
        if now >= self.success_until:
            self._reset_bg()
            self.success_hold_job = None
            return
        self.success_hold_job = self.root.after(200, self._success_hold_tick)

    def _is_success_hold_active(self, now_ts=None) -> bool:
        if now_ts is None:
            now_ts = time.time()
        return now_ts < self.success_until

    # ------------- UI abid -------------
    def _set_bg(self, color: str):
        for w in (self.root, self.wrapper, self.lbl_force, self.lbl_timer,
                  self.lbl_status, self.lbl_raw, self.lbl_bar, self.lbl_thr):
            w.configure(bg=color)

    def _reset_bg(self):
        self._set_bg(self.default_bg)

    def _toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def _exit_fullscreen(self, event=None):
        self.fullscreen = False
        self.root.attributes("-fullscreen", False)

    def _on_resize(self, event=None):
        w = max(self.root.winfo_width(), 1)
        h = max(self.root.winfo_height(), 1)
        short = min(w, h)
        size_force = max(24, int(short * 0.12))
        size_timer = max(18, int(short * 0.08))
        size_info  = max(12, int(short * 0.035))
        self.font_force.configure(size=size_force)
        self.font_timer.configure(size=size_timer)
        self.font_info.configure(size=size_info)

    # ------------- Elutsükkel -------------
    def on_close(self):
        try:
            if self.timer_job is not None:
                self.root.after_cancel(self.timer_job)
            if self.success_hold_job is not None:
                self.root.after_cancel(self.success_hold_job)
            self.bus.close()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()

# ---- CLI ----
def parse_args():
    ap = argparse.ArgumentParser(description="PTE7300 GUI → Newtons (avg+Schmitt+hysteresis)")
    ap.add_argument("--bus", type=int, default=0, help="I2C bus number (e.g. 0 or 1). Default 0.")
    ap.add_argument("--addr", type=lambda x: int(x,0), default=0x6c,
                    help="7-bit I2C address (default 0x6c for no-CRC; CRC addr is 0x6d).")
    ap.add_argument("--fs", type=str, default="0:40",
                    help="Full-scale range in bar as min:max (e.g. 0:200). Default 0:40.")
    ap.add_argument("--schmitt", type=str, default=None,
                    help="Schmitt thresholds as ON:OFF in N (e.g. 160:140). If omitted, uses target & ~10% hysteresis.")
    args = ap.parse_args()

    try:
        fs_min, fs_max = map(float, args.fs.split(":"))
    except Exception:
        print("Bad --fs format, expected like 0:40", file=sys.stderr)
        sys.exit(2)

    sch_on = sch_off = None
    if args.schmitt:
        try:
            sch_on, sch_off = map(float, args.schmitt.split(":"))
        except Exception:
            print("Bad --schmitt format, expected like 160:140", file=sys.stderr)
            sys.exit(2)
        if sch_on <= sch_off:
            print("Schmitt ON must be > OFF (e.g. 160:140)", file=sys.stderr)
            sys.exit(2)

    return args.addr, fs_min, fs_max, sch_on, sch_off, args

if __name__ == "__main__":
    addr, fs_min, fs_max, sch_on, sch_off, _ = parse_args()
    app = PTE7300Gui(busnum=0, addr=addr, fs_min=fs_min, fs_max=fs_max,
                     schmitt_on=sch_on, schmitt_off=sch_off)
    app.run()
