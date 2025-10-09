#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---- Muudetavad algväärtused ----
X_INIT = 0          # algne X väärtus
Y = 3000              # lävi; kui X > Y, käivitub taimer
TIMER_SECONDS = 10  # sekundeid loenduri pikkus

import tkinter as tk
from tkinter import ttk

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("X kuvamine + taimer")
        self.geometry("520x320")
        self.minsize(480, 300)

        # Seis
        self.x = X_INIT
        self.countdown_remaining = 0
        self.countdown_job = None

        # --- UI ---
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        wrapper = ttk.Frame(self, padding=20)
        wrapper.grid(row=0, column=0, sticky="nsew")
        for i in range(3):
            wrapper.rowconfigure(i, weight=1)
        wrapper.columnconfigure(0, weight=1)

        # X suur silt
        self.label_x = ttk.Label(wrapper, text=self._fmt_x(),
                                 anchor="center", font=("Helvetica", 56, "bold"))
        self.label_x.grid(row=0, column=0, sticky="nsew", pady=(10, 0))

        # Taimeri silt (algul peidus)
        self.label_timer = ttk.Label(wrapper, text="", anchor="center",
                                     font=("Helvetica", 36))
        self.label_timer.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.label_timer.grid_remove()

        # Sisendrida
        entry_row = ttk.Frame(wrapper)
        entry_row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        entry_row.columnconfigure(1, weight=1)

        ttk.Label(entry_row, text="Sisesta X ja vajuta Enter:").grid(row=0, column=0, padx=(0, 8))
        self.entry = ttk.Entry(entry_row, width=12, font=("Helvetica", 16))
        self.entry.grid(row=0, column=1, sticky="w")
        self.entry.insert(0, str(self.x))
        self.entry.focus_set()

        # Kiirnupud
        btns = ttk.Frame(entry_row)
        btns.grid(row=0, column=2, padx=(12, 0))
        ttk.Button(btns, text="−1", width=4, command=lambda: self.bump_x(-1)).grid(row=0, column=0)
        ttk.Button(btns, text="+1", width=4, command=lambda: self.bump_x(+1)).grid(row=0, column=1, padx=(6, 0))

        # Klahviseosed
        self.entry.bind("<Return>", self.apply_entry)
        self.bind("<Up>", lambda e: self.bump_x(+1))
        self.bind("<Down>", lambda e: self.bump_x(-1))
        self.bind("+", lambda e: self.bump_x(+1))
        self.bind("-", lambda e: self.bump_x(-1))

        # Esmane värskendus
        self.update_state()

    # --- Abi ---
    def _fmt_x(self) -> str:
        return f"X = {self.x}"

    def apply_entry(self, event=None):
        txt = self.entry.get().strip()
        try:
            # toetame täisarvu; vajadusel muuda int -> float
            val = int(txt)
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
        # Uuenda X kuvamist
        self.label_x.config(text=self._fmt_x())

        # Lävelogiika: kui X > Y ja loendur ei käi, käivita; kui X ≤ Y, peata/peida
        if self.x > Y:
            if self.countdown_job is None and self.countdown_remaining == 0:
                self.start_countdown(TIMER_SECONDS)
        else:
            self.stop_countdown()

    # --- Taimer ---
    def start_countdown(self, seconds: int):
        self.countdown_remaining = int(seconds)
        self.label_timer.config(text=f"{self.countdown_remaining} s")
        self.label_timer.grid()  # näita
        self.tick()

    def tick(self):
        # aegub nullini
        self.label_timer.config(text=f"{self.countdown_remaining} s")
        if self.countdown_remaining <= 0:
            self.countdown_job = None
            return
        self.countdown_remaining -= 1
        self.countdown_job = self.after(1000, self.tick)

    def stop_countdown(self):
        # katkesta ja peida
        if self.countdown_job is not None:
            self.after_cancel(self.countdown_job)
            self.countdown_job = None
        self.countdown_remaining = 0
        self.label_timer.grid_remove()

if __name__ == "__main__":
    App().mainloop()
