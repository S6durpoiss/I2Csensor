#!/usr/bin/env python3
# PTE7300 quick GUI reader with CRC (I2C 0x6D)
import argparse, struct, time, sys
from smbus2 import SMBus, i2c_msg
import tkinter as tk

REG_CMD   = 0x22
REG_PRESS = 0x30
REG_STAT  = 0x32

# ===========================================================
# === CONFIGURABLE SECTION: CONVERSION PARAMETERS & LOGIC ===
# ===========================================================

# Full-scale mapping for pressure (bar). Default: counts in [-16000 .. +16000]
DEFAULT_FS_MIN_BAR = 0.0   # Change this for your sensor's minimum pressure, in bar
DEFAULT_FS_MAX_BAR = 40.0 # Change this for your sensor's maximum pressure, in bar

def counts_to_bar(counts: int, fs_min_bar: float = DEFAULT_FS_MIN_BAR, fs_max_bar: float = DEFAULT_FS_MAX_BAR) -> float:
    """
    Convert the sensor 'counts' to Bar.
    Edit this function and the DEFAULT_FS_MIN_BAR/DEFAULT_FS_MAX_BAR above for calibration!
    """
    # Linear map: fs_min -> -16000, fs_max -> +16000
    return fs_min_bar + (counts + 16000) * ((fs_max_bar - fs_min_bar) / 32000.0)

N_PER_BAR = 1500.0 / 3.3
ZERO_FORCE_OFFSET_N = 0.0
def bar_to_newtons(pressure_bar: float) -> float:
    return pressure_bar * N_PER_BAR + ZERO_FORCE_OFFSET_N
# ===========================================================
# === END CONFIGURABLE SECTION ==============================
# ===========================================================
# CRC-8 with polynomial 0x31, initial 0xFF (per PTE7300 datasheet)
def crc8(data: bytes) -> int:
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc

# ----------------------------------------------------------

def read_s16_be_crc(bus: SMBus, addr: int, reg: int) -> int:
    # Write register address with CRC
    reg_bytes = bytes([reg])
    crc_reg = crc8(reg_bytes)
    write = i2c_msg.write(addr, [reg, crc_reg])
    bus.i2c_rdwr(write)

    # Read 2 data bytes + CRC
    read = i2c_msg.read(addr, 3)
    bus.i2c_rdwr(read)
    b = bytes(read)
    val = (b[0] << 8) | b[1]
    crc_recv = b[2]
    crc_calc = crc8(b[:2])
    if crc_recv != crc_calc:
        raise IOError(f"CRC mismatch: got {crc_recv:02X}, expected {crc_calc:02X}")
    return struct.unpack('>h', b[:2])[0]

def read_u16_be_crc(bus: SMBus, addr: int, reg: int) -> int:
    # Write register address with CRC
    reg_bytes = bytes([reg])
    crc_reg = crc8(reg_bytes)
    write = i2c_msg.write(addr, [reg, crc_reg])
    bus.i2c_rdwr(write)

    # Read 2 data bytes + CRC
    read = i2c_msg.read(addr, 3)
    bus.i2c_rdwr(read)
    b = bytes(read)
    val = (b[0] << 8) | b[1]
    crc_recv = b[2]
    crc_calc = crc8(b[:2])
    if crc_recv != crc_calc:
        raise IOError(f"CRC mismatch: got {crc_recv:02X}, expected {crc_calc:02X}")
    return val

def write_u16_be_crc(bus: SMBus, addr: int, reg: int, value: int) -> None:
    msb, lsb = (value >> 8) & 0xFF, value & 0xFF
    data_bytes = bytes([reg, msb, lsb])
    crc_cmd = crc8(data_bytes)
    write = i2c_msg.write(addr, [reg, msb, lsb, crc_cmd])
    bus.i2c_rdwr(write)

class PTE7300Gui:
    def __init__(self, busnum: int, addr: int, interval_ms: int, fs_min: float, fs_max: float, sample_count: int = 10):
        self.busnum = busnum
        self.addr = addr
        self.interval = max(50, interval_ms)
        self.fs_min = fs_min
        self.fs_max = fs_max
        self.bus = SMBus(self.busnum)
        self.sample_count = sample_count  # <-- Number of readings to average

        self._reset()
        time.sleep(0.005)
        self._start()

        self.root = tk.Tk()
        self.root.title("PTE7300 (CRC) → Newtons")
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

        self._schedule_next()

    def _schedule_next(self):
        self.root.after(self.interval, self.update_once)

    def _reset(self):
        write_u16_be_crc(self.bus, self.addr, REG_CMD, 0xB169)

    def _start(self):
        write_u16_be_crc(self.bus, self.addr, REG_CMD, 0x8B93)

    def _idle(self):
        write_u16_be_crc(self.bus, self.addr, REG_CMD, 0x7BBA)

    def _sleep(self):
        write_u16_be_crc(self.bus, self.addr, REG_CMD, 0x6C32)

    def _reset_then_start(self):
        self._reset()
        time.sleep(0.005)
        self._start()

    def update_once(self):
        """Take several samples, average, then update GUI."""
        try:
            raw_samples = []
            bar_samples = []
            for _ in range(self.sample_count):
                self._start()
                time.sleep(0.003)  # tiny wait
                # Only sample pressure; status can be from last reading
                raw = read_s16_be_crc(self.bus, self.addr, REG_PRESS)
                raw_samples.append(raw)
                bar_samples.append(counts_to_bar(raw, self.fs_min, self.fs_max))
                time.sleep(0.001)  # brief pause between samples

            avg_raw = sum(raw_samples) / len(raw_samples)
            avg_bar = sum(bar_samples) / len(bar_samples)
            force_n = bar_to_newtons(avg_bar)
            status = read_u16_be_crc(self.bus, self.addr, REG_STAT)

            self.lbl_status.config(text=f"STATUS: 0x{status:04X}")
            self.lbl_raw.config(text=f"RAW: {avg_raw:+.1f}")
            self.lbl_bar.config(text=f"PRESSURE: {avg_bar:.3f} bar")
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
    ap = argparse.ArgumentParser(description="PTE7300 GUI reader (CRC) → Newtons")
    ap.add_argument("--bus", type=int, default=0, help="I2C bus number (default 0).")
    ap.add_argument("--addr", type=lambda x: int(x,0), default=0x6d,
                    help="7-bit I2C address (default 0x6d for CRC).")
    ap.add_argument("--interval", type=int, default=500, help="Update interval in ms (default 500).")
    ap.add_argument("--fs", type=str, default="0:200",
                    help="Full-scale range in bar as min:max (default 0:200).")
    ap.add_argument("--samples", type=int, default=10,
                    help="Number of samples per update (default 10).")
    args = ap.parse_args()

    try:
        fs_min, fs_max = map(float, args.fs.split(":"))
    except Exception:
        print("Bad --fs format, expected like 0:200", file=sys.stderr)
        sys.exit(2)

    return args.bus, args.addr, args.interval, fs_min, fs_max, args.samples

if __name__ == "__main__":
    bus, addr, interval, fs_min, fs_max, samples = parse_args()
    app = PTE7300Gui(bus, addr, interval, fs_min, fs_max, sample_count=samples)
    app.run()
