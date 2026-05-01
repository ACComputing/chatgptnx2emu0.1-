#!/usr/bin/env python3.14
# -*- coding: utf-8 -*-
"""
NX2EMU by AC - Homebrew Tkinter Edition
Python 3.14, single-file, assets/files off.

This is NOT a real Nintendo Switch/Switch 2 emulator and does not boot
commercial games, firmware, encrypted containers, BIOS files, prod.keys, NSP,
XCI, NCA, NSO, or NRO content. It is a legal educational fantasy-console
emulator with a Switch-inspired UI shell.

Run:
    python3.14 nx2emu_by_ac_homebrew_tk.py

Controls in demo:
    Arrow keys / WASD = move blue square
    Space / Enter     = pulse color
"""
from __future__ import annotations

import math
import random
import struct
import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "NX2EMU by AC - Homebrew Edition"
VERSION = "1.0.0-safe"

BG = "#000000"
PANEL = "#050810"
BLUE = "#4da6ff"
BLUE_BRIGHT = "#66ccff"
BLUE_DIM = "#2266aa"
WHITE = "#d7ecff"
WARN = "#ffbb33"
ERR = "#ff5566"
OK = "#55ff99"

SCREEN_W = 320
SCREEN_H = 180
SCALE = 3
MEM_SIZE = 1024 * 1024
PROGRAM_BASE = 0x1000
FRAME_MS = 16
TIMER_MS = 1000 // 60

# NX2HB instruction opcodes. Every instruction is 4 bytes:
#   byte0 opcode, byte1 a, byte2 b, byte3 c/immediate
OP_NOP   = 0x00
OP_CLS   = 0x01
OP_SET   = 0x02   # SET Ra, imm8
OP_ADD   = 0x03   # ADD Ra, imm8 signed
OP_MOV   = 0x04   # MOV Ra, Rb
OP_JMP   = 0x05   # JMP addr16 = b<<8|c
OP_JNZ   = 0x06   # JNZ Ra, addr16 = b<<8|c
OP_RECT  = 0x07   # RECT x=R[a], y=R[b], size=c, color=R15
OP_RAND  = 0x08   # RAND Ra, max=c
OP_KEY   = 0x09   # KEY Ra, keycode c -> 1/0
OP_BEEP  = 0x0A   # BEEP frames=c
OP_WAIT  = 0x0B   # WAIT frames=c
OP_HALT  = 0xFF

KEY_LEFT = 1
KEY_RIGHT = 2
KEY_UP = 3
KEY_DOWN = 4
KEY_A = 5


def rgb565_to_hex(value: int) -> str:
    r = ((value >> 11) & 0x1F) * 255 // 31
    g = ((value >> 5) & 0x3F) * 255 // 63
    b = (value & 0x1F) * 255 // 31
    return f"#{r:02x}{g:02x}{b:02x}"


def signed8(value: int) -> int:
    value &= 0xFF
    return value - 256 if value & 0x80 else value


@dataclass(slots=True)
class CpuState:
    regs: list[int] = field(default_factory=lambda: [0] * 16)
    pc: int = PROGRAM_BASE
    halted: bool = False
    wait_frames: int = 0
    cycles: int = 0


class NX2HomebrewVM:
    """Tiny homebrew VM used by the Tkinter shell."""

    def __init__(self) -> None:
        self.memory = bytearray(MEM_SIZE)
        self.cpu = CpuState()
        self.framebuffer = [0] * (SCREEN_W * SCREEN_H)  # RGB565 pixels
        self.keys: set[int] = set()
        self.draw_flag = True
        self.sound_timer = 0
        self.program_name = "AC Built-in Demo"
        self.reset(load_demo=True)

    def reset(self, load_demo: bool = False) -> None:
        self.memory[:] = b"\x00" * MEM_SIZE
        self.cpu = CpuState()
        self.framebuffer[:] = [0] * len(self.framebuffer)
        self.keys.clear()
        self.draw_flag = True
        self.sound_timer = 0
        if load_demo:
            self.load_program(make_demo_program(), "AC Built-in Demo")

    def load_program(self, data: bytes, name: str = "homebrew") -> None:
        if len(data) + PROGRAM_BASE > MEM_SIZE:
            raise ValueError(f"Program too large: {len(data)} bytes")
        self.memory[:] = b"\x00" * MEM_SIZE
        self.memory[PROGRAM_BASE:PROGRAM_BASE + len(data)] = data
        self.cpu = CpuState()
        self.framebuffer[:] = [0] * len(self.framebuffer)
        self.draw_flag = True
        self.program_name = name

    def load_nx2hb_text(self, text: str, name: str = "text homebrew") -> None:
        program = assemble_nx2hb(text)
        self.load_program(program, name)

    def set_key(self, key_code: int, pressed: bool) -> None:
        if pressed:
            self.keys.add(key_code)
        else:
            self.keys.discard(key_code)

    def timer_tick(self) -> None:
        if self.sound_timer > 0:
            self.sound_timer -= 1

    def clear(self, color: int = 0) -> None:
        self.framebuffer[:] = [color & 0xFFFF] * len(self.framebuffer)
        self.draw_flag = True

    def rect(self, x: int, y: int, size: int, color: int) -> None:
        size = max(1, min(64, size))
        color &= 0xFFFF
        for yy in range(y, y + size):
            if yy < 0 or yy >= SCREEN_H:
                continue
            row = yy * SCREEN_W
            for xx in range(x, x + size):
                if 0 <= xx < SCREEN_W:
                    self.framebuffer[row + xx] = color
        self.draw_flag = True

    def step(self) -> None:
        cpu = self.cpu
        if cpu.halted:
            return
        if cpu.wait_frames > 0:
            cpu.wait_frames -= 1
            return

        pc = cpu.pc
        if pc < 0 or pc + 4 > MEM_SIZE:
            cpu.halted = True
            raise RuntimeError(f"PC out of memory: 0x{pc:05X}")

        op, a, b, c = self.memory[pc:pc + 4]
        cpu.pc = (pc + 4) & 0xFFFFF
        cpu.cycles += 1
        r = cpu.regs

        if op == OP_NOP:
            return
        if op == OP_CLS:
            self.clear(((b << 8) | c) if a else 0)
            return
        if op == OP_SET:
            r[a & 0xF] = c
            return
        if op == OP_ADD:
            r[a & 0xF] = (r[a & 0xF] + signed8(c)) & 0xFFFF
            return
        if op == OP_MOV:
            r[a & 0xF] = r[b & 0xF]
            return
        if op == OP_JMP:
            cpu.pc = ((b << 8) | c) & 0xFFFFF
            return
        if op == OP_JNZ:
            if r[a & 0xF] != 0:
                cpu.pc = ((b << 8) | c) & 0xFFFFF
            return
        if op == OP_RECT:
            color = r[15] or 0x04BF  # blue-ish fallback
            self.rect(int(r[a & 0xF]), int(r[b & 0xF]), c, color)
            return
        if op == OP_RAND:
            r[a & 0xF] = random.randrange(max(1, c + 1))
            return
        if op == OP_KEY:
            r[a & 0xF] = 1 if c in self.keys else 0
            return
        if op == OP_BEEP:
            self.sound_timer = max(self.sound_timer, c)
            return
        if op == OP_WAIT:
            cpu.wait_frames = c
            return
        if op == OP_HALT:
            cpu.halted = True
            return
        raise RuntimeError(f"Unknown opcode 0x{op:02X} at 0x{pc:05X}")


class AsmError(ValueError):
    pass


def parse_reg(token: str) -> int:
    token = token.strip().upper()
    if not token.startswith("R"):
        raise AsmError(f"Expected register, got {token!r}")
    idx = int(token[1:], 0)
    if not 0 <= idx <= 15:
        raise AsmError(f"Register out of range: {token}")
    return idx


def parse_int(token: str, labels: dict[str, int] | None = None) -> int:
    token = token.strip()
    if labels and token in labels:
        return labels[token]
    if token.startswith("#"):
        token = token[1:]
    return int(token, 0)


def clean_line(line: str) -> str:
    return line.split(";", 1)[0].split("//", 1)[0].strip()


def tokenize(line: str) -> list[str]:
    return [p.strip() for p in line.replace(",", " ").split() if p.strip()]


def require_parts(parts: list[str], count: int, mnemonic: str) -> None:
    if len(parts) != count:
        raise AsmError(f"{mnemonic} expects {count - 1} argument(s), got {len(parts) - 1}")


def assemble_nx2hb(source: str) -> bytes:
    labels: dict[str, int] = {}
    cleaned: list[tuple[int, str]] = []
    pc = PROGRAM_BASE

    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = clean_line(raw)
        if not line:
            continue
        while ":" in line:
            label, rest = line.split(":", 1)
            label = label.strip()
            if not label or any(ch.isspace() for ch in label):
                raise AsmError(f"Line {lineno}: bad label")
            labels[label] = pc
            line = rest.strip()
            if not line:
                break
        if line:
            cleaned.append((lineno, line))
            pc += 4

    out = bytearray()
    for lineno, line in cleaned:
        parts = tokenize(line)
        if not parts:
            continue
        mnem = parts[0].upper()
        try:
            if mnem == "NOP":
                require_parts(parts, 1, "NOP")
                out += bytes([OP_NOP, 0, 0, 0])
            elif mnem == "CLS":
                color = parse_int(parts[1], labels) if len(parts) > 1 else 0
                out += bytes([OP_CLS, 1 if len(parts) > 1 else 0, (color >> 8) & 0xFF, color & 0xFF])
            elif mnem == "SET":
                require_parts(parts, 3, "SET")
                out += bytes([OP_SET, parse_reg(parts[1]), 0, parse_int(parts[2], labels) & 0xFF])
            elif mnem == "ADD":
                require_parts(parts, 3, "ADD")
                out += bytes([OP_ADD, parse_reg(parts[1]), 0, parse_int(parts[2], labels) & 0xFF])
            elif mnem == "MOV":
                require_parts(parts, 3, "MOV")
                out += bytes([OP_MOV, parse_reg(parts[1]), parse_reg(parts[2]), 0])
            elif mnem == "JMP":
                require_parts(parts, 2, "JMP")
                addr = parse_int(parts[1], labels)
                out += bytes([OP_JMP, 0, (addr >> 8) & 0xFF, addr & 0xFF])
            elif mnem == "JNZ":
                require_parts(parts, 3, "JNZ")
                addr = parse_int(parts[2], labels)
                out += bytes([OP_JNZ, parse_reg(parts[1]), (addr >> 8) & 0xFF, addr & 0xFF])
            elif mnem == "RECT":
                require_parts(parts, 4, "RECT")
                out += bytes([OP_RECT, parse_reg(parts[1]), parse_reg(parts[2]), parse_int(parts[3], labels) & 0xFF])
            elif mnem == "RAND":
                require_parts(parts, 3, "RAND")
                out += bytes([OP_RAND, parse_reg(parts[1]), 0, parse_int(parts[2], labels) & 0xFF])
            elif mnem == "KEY":
                require_parts(parts, 3, "KEY")
                key_names = {
                    "LEFT": KEY_LEFT,
                    "RIGHT": KEY_RIGHT,
                    "UP": KEY_UP,
                    "DOWN": KEY_DOWN,
                    "A": KEY_A,
                    "SPACE": KEY_A,
                    "ENTER": KEY_A,
                }
                key_token = parts[2].upper()
                key = key_names[key_token] if key_token in key_names else parse_int(parts[2], labels)
                out += bytes([OP_KEY, parse_reg(parts[1]), 0, key & 0xFF])
            elif mnem == "BEEP":
                require_parts(parts, 2, "BEEP")
                out += bytes([OP_BEEP, 0, 0, parse_int(parts[1], labels) & 0xFF])
            elif mnem == "WAIT":
                require_parts(parts, 2, "WAIT")
                out += bytes([OP_WAIT, 0, 0, parse_int(parts[1], labels) & 0xFF])
            elif mnem == "HALT":
                require_parts(parts, 1, "HALT")
                out += bytes([OP_HALT, 0, 0, 0])
            else:
                raise AsmError(f"Unknown mnemonic {mnem!r}")
        except (IndexError, ValueError, AsmError) as exc:
            raise AsmError(f"Line {lineno}: {line!r}: {exc}") from exc
    return bytes(out)


def make_demo_program() -> bytes:
    # Tiny animated square demo, written directly as bytecode. R0=x, R1=y, R15=color.
    src = """
        SET R0, 150
        SET R1, 80
        SET R15, 191
    loop:
        CLS 0
        KEY R2, LEFT
        JNZ R2, left
    after_left:
        KEY R2, RIGHT
        JNZ R2, right
    after_right:
        KEY R2, UP
        JNZ R2, up
    after_up:
        KEY R2, DOWN
        JNZ R2, down
    after_down:
        KEY R2, A
        JNZ R2, pulse
    after_pulse:
        RECT R0, R1, 18
        WAIT 1
        JMP loop
    left:
        ADD R0, -3
        JMP after_left
    right:
        ADD R0, 3
        JMP after_right
    up:
        ADD R1, -3
        JMP after_up
    down:
        ADD R1, 3
        JMP after_down
    pulse:
        RAND R15, 255
        BEEP 4
        JMP after_pulse
    """
    return assemble_nx2hb(src)


class NX2TkApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.vm = NX2HomebrewVM()
        self.running = False
        self.cycles_per_frame = tk.IntVar(value=900)
        self.last_bell = False
        self.pixel_items: list[int] = []
        self._build_ui()
        self._bind_keys()
        self.render_full()
        self._frame_loop()
        self._timer_loop()

    def _button(self, parent: tk.Misc, text: str, cmd=None, width: int = 12) -> tk.Button:
        return tk.Button(
            parent, text=text, command=cmd, width=width,
            bg=BG, fg=BLUE, activebackground="#08182c", activeforeground=BLUE_BRIGHT,
            relief="ridge", borderwidth=2, highlightthickness=1,
            highlightbackground=BLUE_DIM, font=("TkDefaultFont", 10, "bold"), cursor="hand2",
        )

    def _build_ui(self) -> None:
        root = self.root
        title = tk.Label(root, text="NX2EMU by AC", bg=BG, fg=BLUE_BRIGHT, font=("TkDefaultFont", 22, "bold"), pady=10)
        title.grid(row=0, column=0, columnspan=2, sticky="ew")

        left = tk.Frame(root, bg=BG, padx=12, pady=8)
        left.grid(row=1, column=0, sticky="n")

        self.canvas = tk.Canvas(left, width=SCREEN_W * SCALE, height=SCREEN_H * SCALE, bg=BG,
                                highlightthickness=2, highlightbackground=BLUE)
        self.canvas.grid(row=0, column=0, columnspan=6)

        controls = tk.Frame(left, bg=BG, pady=10)
        controls.grid(row=1, column=0, columnspan=6, sticky="ew")
        self._button(controls, "Open .nx2hb", self.open_homebrew).grid(row=0, column=0, padx=4)
        self._button(controls, "Load Demo", self.load_demo).grid(row=0, column=1, padx=4)
        self.run_btn = self._button(controls, "Run", self.toggle_run)
        self.run_btn.grid(row=0, column=2, padx=4)
        self._button(controls, "Step", self.step_once).grid(row=0, column=3, padx=4)
        self._button(controls, "Reset", self.reset).grid(row=0, column=4, padx=4)

        speed = tk.Frame(left, bg=BG)
        speed.grid(row=2, column=0, columnspan=6, sticky="ew")
        tk.Label(speed, text="Cycles/frame", bg=BG, fg=WHITE).pack(side="left")
        tk.Scale(speed, from_=1, to=4000, orient="horizontal", variable=self.cycles_per_frame,
                 bg=BG, fg=BLUE, troughcolor=PANEL, highlightthickness=0, length=360).pack(side="left", padx=8)

        self.status = tk.Label(left, text="Ready. Homebrew-only NX2 VM loaded.", bg=BG, fg=WHITE,
                               anchor="w", justify="left", wraplength=SCREEN_W * SCALE)
        self.status.grid(row=3, column=0, columnspan=6, sticky="ew", pady=8)

        right = tk.Frame(root, bg=PANEL, padx=12, pady=8, highlightthickness=1, highlightbackground=BLUE_DIM)
        right.grid(row=1, column=1, sticky="n", padx=(0, 12))
        tk.Label(right, text="System", bg=PANEL, fg=BLUE_BRIGHT, font=("TkDefaultFont", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.info = tk.Text(right, width=38, height=18, bg=BG, fg=WHITE, insertbackground=BLUE,
                            relief="flat", font=("Menlo", 10))
        self.info.grid(row=1, column=0, pady=8)
        self.info.configure(state="disabled")

        sample = tk.Label(right, text="Homebrew text format supports:\nCLS, SET, ADD, MOV, JMP, JNZ, RECT, RAND, KEY, BEEP, WAIT, HALT",
                          bg=PANEL, fg=WHITE, justify="left", wraplength=300)
        sample.grid(row=2, column=0, sticky="w")
        self.refresh_info()

    def _bind_keys(self) -> None:
        self.key_map = {
            "Left": KEY_LEFT, "a": KEY_LEFT,
            "Right": KEY_RIGHT, "d": KEY_RIGHT,
            "Up": KEY_UP, "w": KEY_UP,
            "Down": KEY_DOWN, "s": KEY_DOWN,
            "space": KEY_A, "Return": KEY_A,
        }
        self.root.bind_all("<KeyPress>", self.on_key_down)
        self.root.bind_all("<KeyRelease>", self.on_key_up)
        self.root.focus_set()

    def log_status(self, text: str) -> None:
        self.status.config(text=text)

    def refresh_info(self) -> None:
        c = self.vm.cpu
        text = (
            f"{APP_TITLE}\n"
            f"Version: {VERSION}\n"
            f"Mode: Legal homebrew VM\n"
            f"Program: {self.vm.program_name}\n"
            f"PC: 0x{c.pc:05X}\n"
            f"Cycles: {c.cycles}\n"
            f"Halted: {c.halted}\n"
            f"Sound timer: {self.vm.sound_timer}\n\n"
            "R0-R7:\n" + " ".join(f"{v:04X}" for v in c.regs[:8]) + "\n"
            "R8-RF:\n" + " ".join(f"{v:04X}" for v in c.regs[8:]) + "\n\n"
            "Commercial ROM/firmware/keys: disabled\n"
            "Supported: .nx2hb text or raw NX2HB bytecode"
        )
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text)
        self.info.configure(state="disabled")

    def render_full(self) -> None:
        self.canvas.delete("pixel")
        s = SCALE
        # Coalesce into rectangles per pixel. 57,600 rectangles is acceptable but not cheap;
        # only draw non-black pixels plus a dim scanline grid effect.
        fb = self.vm.framebuffer
        for y in range(SCREEN_H):
            row = y * SCREEN_W
            for x in range(SCREEN_W):
                color = fb[row + x]
                if color:
                    hx = rgb565_to_hex(color)
                    self.canvas.create_rectangle(x*s, y*s, (x+1)*s, (y+1)*s, fill=hx, outline=hx, tags="pixel")
        self.vm.draw_flag = False

    def open_homebrew(self) -> None:
        path = filedialog.askopenfilename(
            title="Open NX2 homebrew",
            filetypes=[("NX2 homebrew", "*.nx2hb *.txt *.bin"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
            name = path.split("/")[-1]
            try:
                text = raw.decode("utf-8")
                # Treat mostly printable files as assembly text.
                if any(word in text.upper() for word in ("CLS", "RECT", "JMP", "SET")):
                    self.vm.load_nx2hb_text(text, name)
                else:
                    self.vm.load_program(raw, name)
            except UnicodeDecodeError:
                self.vm.load_program(raw, name)
            self.running = False
            self.run_btn.config(text="Run")
            self.render_full()
            self.refresh_info()
            self.log_status(f"Loaded homebrew: {name}")
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            self.log_status(f"Load failed: {exc}")

    def load_demo(self) -> None:
        self.vm.reset(load_demo=True)
        self.running = False
        self.run_btn.config(text="Run")
        self.render_full()
        self.refresh_info()
        self.log_status("Loaded AC built-in demo. Press Run, then move with arrows/WASD.")

    def toggle_run(self) -> None:
        self.running = not self.running
        self.run_btn.config(text="Pause" if self.running else "Run")
        self.log_status("Running." if self.running else "Paused.")

    def step_once(self) -> None:
        self.running = False
        self.run_btn.config(text="Run")
        try:
            self.vm.step()
            if self.vm.draw_flag:
                self.render_full()
            self.refresh_info()
            self.log_status("Stepped one NX2HB instruction.")
        except Exception as exc:
            self.log_status(f"VM stopped: {exc}")
            messagebox.showerror("VM stopped", str(exc))

    def reset(self) -> None:
        self.vm.cpu = CpuState()
        self.vm.framebuffer[:] = [0] * len(self.vm.framebuffer)
        self.vm.keys.clear()
        self.vm.sound_timer = 0
        self.vm.draw_flag = True
        self.last_bell = False
        self.running = False
        self.run_btn.config(text="Run")
        self.render_full()
        self.refresh_info()
        self.log_status("Reset current program.")

    def on_key_down(self, event: tk.Event) -> None:
        key = self.key_map.get(str(event.keysym)) or self.key_map.get(str(event.keysym).lower())
        if key is not None:
            self.vm.set_key(key, True)

    def on_key_up(self, event: tk.Event) -> None:
        key = self.key_map.get(str(event.keysym)) or self.key_map.get(str(event.keysym).lower())
        if key is not None:
            self.vm.set_key(key, False)

    def _frame_loop(self) -> None:
        if self.running:
            try:
                for _ in range(self.cycles_per_frame.get()):
                    self.vm.step()
                    if self.vm.cpu.halted:
                        self.running = False
                        self.run_btn.config(text="Run")
                        self.log_status("Program halted.")
                        break
                if self.vm.draw_flag:
                    self.render_full()
                if self.vm.sound_timer > 0 and not self.last_bell:
                    self.root.bell()
                    self.last_bell = True
                if self.vm.sound_timer <= 0:
                    self.last_bell = False
                self.refresh_info()
            except Exception as exc:
                self.running = False
                self.run_btn.config(text="Run")
                self.log_status(f"VM stopped: {exc}")
        self.root.after(FRAME_MS, self._frame_loop)

    def _timer_loop(self) -> None:
        if self.running:
            self.vm.timer_tick()
        self.root.after(TIMER_MS, self._timer_loop)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    NX2TkApp().run()
