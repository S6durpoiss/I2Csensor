#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---- Muudetavad algväärtused ----
X_INIT = 0          # algne X väärtus
Y = 10              # lävi; kui X > Y, käivitub taimer
TIMER_SECONDS = 10  # sekundeid loenduri pikkus

import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("X kuvamine + taimer")
        self.attributes("-fullscreen", True)   # käivitu täisekraanil

        # Seis
        self.x = X_INIT
        self.countdown_remaining = 0
        self.countdown_job = None
        self.fullscreen = True

        # Taustavärvi vaikimisi meelde
        self.default_bg = self.cget("bg")

        # --- Fondiobjektid (muudetavad jooksvalt) ---
        self.font_x     = tkfont.Font(family="Helvetica", size=56, weight="bold")
        self.font_timer = tkfont.Font(family="Helvetica", size=36, weight="normal")
        self.font_entry = tkfont.Font(family="Helvetica", size=16, weight="normal")
        self.font_label = tkfont.Font(family="Helvetica", size=14, weight="normal")
        self.font_btn   = tkfont.Font(family="Helvetica", size=16, weight="normal")

        # --- UI ---
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.wrapper = tk.Frame(self, bg=self.default_bg, padx=20, pady=20)
        self.wrapper.grid(row=0, column=0, sticky="nsew")
        for i in range(3):
            self.wrapper.rowconfigure(i, weight=1)
        self.wrapper.columnconfigure(0, weight=1)

        # X suur silt (ilma "X =")
        self.label_x = tk.Label(self.wrapper, text=self._fmt_x(),
                                anchor="center", font=self.font_x,
                                bg=self.default_bg)
        self.label_x.grid(row=0, column=0, sticky="nsew", pady=(10, 0))

        # Taimeri silt (algul peidus)
        self.label_timer = tk.Label(self.wrapper, text="", anchor="center",
                                    font=self.font_timer, bg=self.default_bg)
        self.label_timer.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.label_timer.grid_remove()

        # Sisendrida
        entry_row = ttk.Frame(self.wrapper)
        entry_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        entry_row.columnconfigure(1, weight=1)

        self.lbl_prompt = ttk.Label(entry_row, text="Sisesta X ja vajuta Enter:")
        self.lbl_prompt.grid(row=0, column=0, padx=(0, 8))
        self.entry = ttk.Entry(entry_row, width=12)
        self.entry.grid(row=0, column=1, sticky="w")
        self.entry.insert(0, str(self.x))
        self.entry.focus_set()

        # Kiirnupud
        btns = ttk.Frame(entry_row)
        btns.grid(row=0, column=2, padx=(12, 0))
        self.btn_minus = ttk.Button(btns, text="−1", width=4, command=lambda: self.bump_x(-1))
        self.btn_plus  = ttk.Button(btns, text="+1", width=4, command=lambda: self.bump_x(+1))
        self.btn_minus.grid(row=0, column=0)
        self.btn_plus.grid(row=0, column=1, padx=(6, 0))

        # Klahviseosed
        self.entry.bind("<Return>", self.apply_entry)
        self.bind("<Up>",   lambda e: self.bump_x(+1))
        self.bind("<Down>", lambda e: self.bump_x(-1))
        self.bind("+",      lambda e: self.bump_x(+1))
        self.bind("-",      lambda e: self.bump_x(-1))

        # Täisekraani kiirklahvid
        self.bind("<F11>", self.toggle_fullscreen)
        self.bind("<Escape>", self.exit_fullscreen)

        # Fondi skaleerimine akna muutumisel
        self.bind("<Configure>", self._on_resize)

        # Rakendame algse skaleerimise ja seisu
        self.after(50, self._on_resize)  # lase aknal esmane suurus võtta
        self.update_state()

    # --- Abi ---
    def _fmt_x(self) -> str:
        return f"{self.x}"  # ainult väärtus

    def set_bg(self, color: str):
        self.configure(bg=color)
        self.wrapper.configure(bg=color)
        self.label_x.configure(bg=color)
        self.label_timer.configure(bg=color)

    def reset_bg(self):
        self.set_bg(self.default_bg)

    def apply_entry(self, event=None):
        txt = self.entry.get().strip()
        try:
            val = int(txt)  # vajadusel muuda int -> float
        except ValueError:
            self.bell()
            return
        self.x = val
        self.update_state()

    def bump_x(self, delta: int):
        self.x += delta
        self.entry.delete(0, tk.END)
        self.entry.insert(0, str(self.x))
        self.update_state()

    def update_state(self):
        self.label_x.config(text=self._fmt_x())

        if self.x > Y:
            if self.countdown_job is None and self.countdown_remaining == 0:
                self.start_countdown(TIMER_SECONDS)
        else:
            self.stop_countdown()

    # --- Taimer ---
    def start_countdown(self, seconds: int):
        self.reset_bg()  # eelmine tsükkel võis olla roheline
        self.countdown_remaining = int(seconds)
        self.label_timer.config(text=f"{self.countdown_remaining} s")
        self.label_timer.grid()  # näita taimerit
        self.tick()

    def tick(self):
        self.label_timer.config(text=f"{self.countdown_remaining} s")
        if self.countdown_remaining <= 0:
            self.countdown_job = None
            self.set_bg("green")  # täis -> roheline taust
            return
        self.countdown_remaining -= 1
        self.countdown_job = self.after(1000, self.tick)

    def stop_countdown(self):
        if self.countdown_job is not None:
            self.after_cancel(self.countdown_job)
            self.countdown_job = None
        self.countdown_remaining = 0
        self.label_timer.grid_remove()
        self.reset_bg()

    # --- Täisekraan ---
    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.attributes("-fullscreen", self.fullscreen)

    def exit_fullscreen(self, event=None):
        self.fullscreen = False
        self.attributes("-fullscreen", False)

    # --- Dünaamiline fondi skaleerimine ---
    def _on_resize(self, event=None):
        # Kasuta akna sisemõõte; vali konservatiivne baas suurus
        w = max(self.winfo_width(),  1)
        h = max(self.winfo_height(), 1)
        short = min(w, h)

        # Skaalafaktorid (tunned vabalt timmida)
        size_x     = max(24, int(short * 0.12))  # peamine suur number
        size_timer = max(18, int(short * 0.08))  # taimer
        size_entry = max(14, int(short * 0.04))  # sisend
        size_label = max(12, int(short * 0.035)) # "Sisesta..." silt
        size_btn   = max(14, int(short * 0.04))  # nupud

        # Rakenda
        self.font_x.configure(size=size_x)
        self.font_timer.configure(size=size_timer)
        self.font_entry.configure(size=size_entry)
        self.font_label.configure(size=size_label)
        self.font_btn.configure(size=size_btn)

        # Seo fondid vidinate külge (kui OS/teema ei rakenda automaatselt)
        self.label_x.configure(font=self.font_x)
        self.label_timer.configure(font=self.font_timer)
        self.entry.configure(font=self.font_entry)
        self.lbl_prompt.configure(font=self.font_label)
        self.btn_minus.configure(style="Scaled.TButton")
        self.btn_plus.configure(style="Scaled.TButton")

        # Ttk nuppude jaoks loome stiili, mis kasutab tkfonti
        style = ttk.Style()
        style.configure("Scaled.TButton", font=self.font_btn)

if __name__ == "__main__":
    App().mainloop()
