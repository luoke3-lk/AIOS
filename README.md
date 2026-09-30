# AIOS v0.1

> **[中文版 README](README_CN.md)** ｜ [Architecture](docs/ARCH.md) ｜ [PRD](docs/PRD.md) ｜ [Contributing](CONTRIBUTING.md)

**AIOS is a bare-metal AI operating system: from the first instruction the BIOS
hands over, every access to the CPU, memory, VGA, keyboard and the power
controller is made by AIOS's own code. There is no operating system underneath
it.** You type one sentence in plain English, an on-device int8 neural network
classifies your intent, and AIOS immediately performs a real hardware action.

A legacy BIOS loads a 512-byte MBR, the boot layer probes memory and enters
32-bit protected mode, and the freestanding kernel talks directly to VGA, PS/2,
PCI, ATA, CMOS and the power-control ports. There is no host OS, no libc, no
filesystem, no scheduler, no network stack and no floating-point runtime
underneath it.

---

## Why AIOS

Today's large models all run *on top of* an operating system. Most of the
hardware's capability is handed to the OS scheduler, so the AI never really
gets 100% of the machine. Letting the AI control the hardware itself might be
a way out.

This is a demo prototype and it is not finished — it is not a production
system. Do not write `aios.img` or `aios-hdd.img` to any disk that holds data
you care about.

It was built by one person. Contributions are very welcome.

## What AIOS is *not*

Please read this before you file an issue:

- **It is not Linux, and not built on Linux.** No Linux kernel, no distro, no
  POSIX layer, no ELF loader, no user space.
- **It is not Android, and not an Android-based "AI phone OS".** The
  QWEN BOOK line of work puts an AI layer on top of Android. AIOS goes the
  other way: Android is removed entirely and AIOS drives the hardware itself.
- **There is no operating system underneath.** No host OS, no third-party
  bootloader (no GRUB), no unikernel/LibOS framework, no statically linked
  libc (no newlib, no musl). Two layers only: a 512-byte boot sector and a
  freestanding i386 kernel.
- **It is not a general-purpose OS.** No filesystem, no network, no
  multitasking, no shell scripting, no package manager, no 64-bit long mode.
- **It is not a chatbot.** The model has 12 intents and its entire job is to
  route your sentence to a hardware action. It does not generate text.

## Experimental — read before writing to any disk

> **This is a teaching/demo prototype, not a production system.**
>
> **Never write `aios.img` or `aios-hdd.img` to a disk that holds data you
> care about.** `dd`, Rufus and balenaEtcher overwrite the beginning of the
> target device; the HDD image also installs a partition table. Use a spare
> USB stick, a blank SD card, or an emulator such as QEMU.
>
> `reboot` and `shutdown` are executed immediately with **no confirmation
> prompt** — because there is nothing to lose (no filesystem, no persistent
> state).
>
> **The test gate has only ever run inside the Unicorn CPU emulator. AIOS has
> not yet been booted and measured on real hardware.** See
> [Known limitations](#known-limitations).

---

## Quick start

### 1. Build (about 1–2 minutes)

Prerequisites: **Python 3.11+** and nothing else system-wide — the compiler,
assembler, disassembler and CPU emulator are all installed from PyPI into a
virtual environment. No WSL, no nasm/gcc/binutils, no QEMU, no administrator
rights needed.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python build.py
python test.py
```

**Linux / macOS**

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 build.py
python3 test.py
```

(If you prefer not to activate the venv, call `.venv\Scripts\python.exe` /
`.venv/bin/python` directly — but never hard-code an absolute interpreter path
into a commit.)

### 2. Run in an emulator

```sh
qemu-system-i386 -fda aios.img
```

or, using the HDD/USB image:

```sh
qemu-system-i386 -drive format=raw,file=aios-hdd.img
```

### 3. Run on a real machine

Use `aios-hdd.img` and a **spare** USB stick. The floppy image is mainly for
emulators; most firmware will not offer a USB floppy boot option.

**Linux/macOS** (replace `/dev/sdX` with the *whole* device, not a partition):

```sh
sudo dd if=aios-hdd.img of=/dev/sdX bs=1M conv=fsync status=progress
```

**Windows**: select `aios-hdd.img` in Rufus or balenaEtcher, choose
BIOS/MBR when offered, safely eject, then enable **Legacy / CSM boot** in the
firmware setup and disable Secure Boot temporarily.

Type `help` (or just *"what can you do"*) at the `{AIOS}> ` prompt.

---

## The role of Python (please read — this is the most misunderstood part)

**Python is a build-time toolchain only. It is not part of the operating
system, and it does not run on the target machine.**

Everything under `tools/`, plus `build.py` and `test.py`, runs on your host.
The build uses Python purely to drive four PyPI packages:

| Package | Build-time job |
| --- | --- |
| `keystone-engine` | assembles `boot/boot.asm` into the 512-byte MBR |
| `ziglang` | `zig cc` compiles/links every `.c` into a freestanding i386 ELF; `zig objcopy` extracts the raw binary |
| `capstone` | disassembles `kernel.bin` and counts forbidden instructions |
| `unicorn` | emulates an x86 CPU so `test.py` can boot the image headlessly |

The **runtime artifact** is `aios.img` / `aios-hdd.img`: pure x86 machine code
that a BIOS loads and executes. Once the image exists, Python is not involved
again. At runtime there is **no Python, no libc, no floating point, no heap**.

### Hard evidence

The build refuses to emit an image unless the kernel binary is clean. After a
build, `build/report-instr.txt` contains:

```
fpu_ops=0          <-- zero x87 instructions
sse_ops=0          <-- zero SSE instructions
mmx_ops=0          <-- zero MMX instructions
libc_symbols=0     <-- zero undefined libc symbols
undefined_symbols=
total_insns=...           (varies per build)
kernel_bin_bytes=...      (varies per build)
boot_bin_bytes=512
```

The kernel is compiled with `-mno-80387 -mno-sse -mno-sse2 -mno-mmx
-nostdlib -ffreestanding -fno-builtin`, so any x87/SSE/MMX instruction or any
undefined libc symbol fails the build instead of silently shipping.

Corollary: **you cannot `pip install` anything onto AIOS**, and you cannot load
a model file at runtime — there is no filesystem. New weights are generated on
the host and compiled into the kernel image.

---

## Architecture at a glance

```
  BIOS / UEFI-CSM                (not written by us)
 ─────────────────────────────────────────────────────
  L1 boot sector    512 B MBR @ 0x7C00
      A20 → E820 → INT 13h load kernel → GDT → CR0.PE
 ─────────────────────────────────────────────────────
  L2 kernel         freestanding i386 C @ 0x10000
      drivers/  VGA 0xB8000 · PS/2 keyboard
      mm/       physical memory bitmap allocator
      nlu/ nn/  int8 MLP inference engine + weights ROM
      shell/    line editor · intent routing · actions
      hw/       the hardware actions themselves
```

1. BIOS loads the MBR at physical `0x7C00`.
2. The boot layer initializes segments and stack, enables A20, obtains the
   E820 memory map at `0x8000`, reads the kernel to `0x10000`, installs a flat
   GDT, and sets CR0.PE.
3. `_start` sets up the stack at `0x90000`, clears `.bss`, and calls
   `kernel_main`.
4. VGA, PMM, PS/2 and the model are initialized. The prompt is `{AIOS}> `.
5. Each line becomes a 256-dimensional int8 feature vector (hashing trick over
   token unigram/bigram/trigram + character trigrams), an integer MLP
   (256-64-ReLU-12, weights ROM = 17456 bytes) returns Top-3 intents, and one
   table-driven action touches the hardware.

The PMM bitmap lives outside the binary at physical `0x40000`; the AI arena is
`0x60000..0x7FFFF`. This keeps `.bss` from inflating the raw kernel image so
that it still fits on a floppy.

### Build outputs

| Artifact | Description |
| --- | --- |
| `aios.img` | exact 1,474,560-byte floppy image |
| `aios-hdd.img` | 10 MiB HDD/USB image with one active type-`0x7F` partition |
| `build/kernel.elf`, `build/kernel.bin` | linked ELF and raw binary |
| `build/report-instr.txt` | the zero-FPU/SIMD/libc gate |
| `build/manifest.json` | sources, sizes, feature switches, LBA layout |
| `build/train_report.json` | training + quantization + accuracy report |
| `build/screen.html` | VGA framebuffer dump (`--dump`) |

### Build options

| Flag | Effect |
| --- | --- |
| `--dump` | boot the image in Unicorn and render the 80x25 VGA buffer to `build/screen.html` |
| `--kbd-mode 1` | default; real-hardware keyboard (minimal IDT + IRQ1 + `sti;hlt`) |
| `--kbd-mode 0` | pure polling; use for focused Unicorn experiments |
| `--prompt-style 1` | default prompt `{AIOS}> `; `--prompt-style 0` gives `AIOS> ` |
| `--two-sector` | force the two-sector boot layout (see below) |
| `--slim` | trim optional boot features (e.g. the CHS read fallback) |
| `--retrain` / `--skip-train` | force / skip corpus+model regeneration |

The boot assembler first tries a partition-table-safe one-sector MBR. If its
code exceeds 446 bytes the build automatically switches to the `TWO_SECTOR`
layout: a 512-byte MBR loads a second boot-layer sector and the kernel starts
at LBA 2. The current tree builds as `TWO_SECTOR` with `kernel_lba = 2`.

---

## On-device NLU and the model

```
"what cpu is this"
   → normalize (lowercase, non-alnum → space, collapse spaces)
   → tokenize (≤ 32 tokens)
   → token unigram / bigram / trigram + character trigram
   → FNV-1a 32-bit hash per n-gram
   → signed count accumulation into 256 buckets
   → clamp to [-127, 127]  →  256-dim int8 feature vector
   → MLP 256 → 64 (ReLU) → 12 (linear), all int32 arithmetic
   → fixed-point softmax (Q15 exp LUT, 513 entries)
   → Top-3 intents + integer percentages
   → dispatch() → one hardware action
```

| Property | Value |
| --- | --- |
| Input | 256-dim int8 signed count features |
| Network | `256 → 64 (ReLU) → 12 (linear)`, single hidden layer |
| Weights | int8 (`W1`, `W2`), biases int32 (`b1`, `b2`), accumulators int32 |
| Weights ROM | **17456 bytes** = 16384 (`W1`) + 256 (`b1`) + 768 (`W2`) + 48 (`b2`) |
| Softmax | 513-entry Q15 `exp` lookup table, shift-only scaling |
| Fallback | Top-1 confidence < `CONF_THRESHOLD` (35%) → `INTENT_FALLBACK` |
| Arithmetic | integer only; no x87/SSE/MMX, no division for scaling |

Measured on the held-out synthetic corpus (`build/train_report.json`,
seed `20260101`, 120 utterances per intent):

| Metric | Value |
| --- | --- |
| Top-1 accuracy | **0.9965** (288 validation samples) |
| Perturbed Top-1 | **0.9961** (255 perturbed samples) |
| int8 vs float agreement | **1.0** |
| C vs Python feature vectors | **260/260 byte-identical** |
| Forward golden vectors | **40/40 byte-identical** |

> The corpus is machine-generated from templates, so these numbers measure
> *robustness of the pipeline* (case, punctuation, typos, word order), not
> real-world conversational accuracy.

### The 13 table entries

The model's softmax has **12** outputs; `INTENT_FALLBACK` is the 13th table
entry and is selected by the confidence threshold, not by the network. Order
matters — it must match `shell/intent.h`, `shell/dispatch.c` and `test.py`:

`CLEAR`, `MEMINFO`, `CPUINFO`, `SELFTEST`, `DISKINFO`, `MODELINFO`, `CALC`,
`SCREENTEST`, `HELP`, `ABOUT`, `REBOOT`, `SHUTDOWN`, `FALLBACK`

| Intent | Real hardware action |
| --- | --- |
| `CLEAR` | fill `0xB8000` with blanks, reset CRTC cursor |
| `MEMINFO` | E820 map + PMM allocator statistics + AI share |
| `CPUINFO` | `cpuid` leaves 0/1/0x80000002–4: vendor, brand, features |
| `SELFTEST` | PCI config-space scan + 1 MB memory march + CMOS/RTC |
| `DISKINFO` | ATA PIO identify on ports `0x1F0` / `0x170` |
| `MODELINFO` | reports the model running inside the kernel |
| `CALC` | two-operand integer `+ - * /`, decimal and `0x` hex |
| `SCREENTEST` | 16-colour bars, checkerboard, character gradient |
| `HELP` / `ABOUT` | fixed golden text |
| `REBOOT` | `out 0x64, 0xFE` (8042 reset) |
| `SHUTDOWN` | APM → ACPI `0x604 ← 0x2000` → `hlt` |
| `FALLBACK` | prints its Top-3 guesses and suggests what to say |

---

## Design constraints and why

Every odd-looking decision below follows from "there is nothing underneath us".

| Decision | Reason |
| --- | --- |
| **int8 fixed-point, no floating point** | The kernel is compiled with `-mno-80387 -mno-sse -mno-sse2 -mno-mmx`. Using x87 would mean initializing the FPU and pulling soft-float helpers into a binary that has no libc. All scaling is by powers of two, so a multiply is a shift. |
| **All shifts, no division for scaling** | Guarantees C and Python agree bit-for-bit: every value shifted is non-negative, so C's arithmetic right shift is exactly mathematical floor. |
| **Hashing trick instead of a vocabulary** | There is no filesystem, so no dictionary could ever be loaded at runtime. A hashed 256-bucket feature vector needs zero storage and O(1) lookup. |
| **256 buckets** | A power of two, so the bucket index is `hash & 255` — no division. All four n-gram types share one accumulator. |
| **12 intents** | One per hardware action that actually exists in `hw/`. Adding a *13th* action means retraining, not just adding a table row. |
| **`FALLBACK` is not a softmax output** | A 13th class would need its own training data for an infinitely large "everything else" set. A confidence threshold generalizes better. |
| **Weights compiled into the kernel** | No filesystem means no model file can be read at runtime. `nn/model_weights.h` *is* the model. |
| **No heap, no dynamic allocation** | There is no allocator to grow and no MMU to protect. Buffers are either static in `.bss` or placed at fixed physical addresses outside the binary. |
| **PMM bitmap at a fixed physical address** | If it lived in `.bss`, `objcopy -O binary` would pad the raw kernel with hundreds of KB of zeros and it would stop fitting on a floppy. |
| **Single-threaded polling** | No scheduler, no timer tick, no preemption. `hlt` between keystrokes is the entire power-management story. |
| **ASCII English only** | See below. |

---

## Known limitations

- **Legacy BIOS or UEFI CSM only.** Pure UEFI firmware without a CSM cannot
  execute a 512-byte MBR. There is no EFI application and no GPT support.
- **ASCII English input and output only.** VGA 80×25 text mode has a 256-glyph
  code-page ROM with no Chinese (or any other non-Latin) glyphs, and there is
  no input method. Supporting Chinese would mean hand-drawing a 16×16 dot-matrix
  font (≈216 KB for 6,763 glyphs — larger than the whole kernel budget) plus a
  pinyin IME. That is out of scope for v0.1.
- **The gate is emulator-only.** All 59 tests pass in the **Unicorn** CPU
  emulator with scripted BIOS and port stubs. **AIOS has not been booted or
  measured on real hardware yet.** Firmware behaviour (INT 13h extensions,
  A20 methods, PS/2 legacy emulation on USB keyboards) may differ.
- **No filesystem.** Nothing can be read or written at runtime. Disk access is
  limited to the boot-time kernel read and an ATA identify query.
- **No network stack, no scheduler, no multitasking, no user space, no 64-bit
  long mode.** One thread, i386 32-bit protected mode, polled I/O.
- **No persistent state.** Every boot reconstructs everything from the image.
- **`reboot` / `shutdown` fire immediately with no confirmation.**
- **The intent corpus is synthetic.** It is generated from templates with
  controlled perturbations; natural human phrasing outside those templates may
  fall through to `FALLBACK`.
- **No interrupt-driven timer.** The cursor blink is done by the VGA CRTC in
  hardware; the kernel never runs a software blink loop.

---

## Test gate

`python test.py` prints one line per case,
`[PASS|FAIL] layer=<layer> case=<name>`. The gate covers boot, VGA, keyboard,
PMM, dispatch, every hardware action, golden text, and fuzz boundaries. AI NLU
and MLP golden-vector tests extend the same registration table. A nonzero
forbidden-instruction count or any failed case makes the command exit nonzero.

Current status: **59 / 59 passing**

```
boot=12 dispatch=5 fuzz=5 golden=4 hwaction=14 kbd=7 pmm=5 vga=7
```

**All 59 must pass before a pull request will be reviewed.** See
[CONTRIBUTING.md](CONTRIBUTING.md).

---

## Troubleshooting checklist

1. **Black screen:** enable Legacy Boot/CSM; pure UEFI cannot execute this MBR.
2. **`Missing operating system`:** write the whole image to the whole device,
   not to an existing filesystem or partition.
3. **USB not listed:** use `aios-hdd.img`, select USB-HDD mode, and disable
   Secure Boot temporarily; the floppy image is mainly for emulators.
4. **Cursor visible but keyboard silent:** rebuild with `--kbd-mode 0` to check
   whether firmware/PIC IRQ routing is the cause; also try a built-in PS/2
   keyboard rather than a USB keyboard without legacy emulation.
5. **Immediate `disk error` or hang before banner:** enable BIOS INT 13h
   extensions or retry the floppy image so CHS geometry is 18 sectors/2 heads.
6. **Build reports forbidden instructions/symbols:** inspect
   `build/report-instr.txt`; keep all kernel arithmetic integer-only and do not
   include hosted C library headers.

---

## Roadmap

Ordered by what unblocks the most learning per unit of risk.

- **v0.1.x** — real-hardware boot report (a small matrix of machines + firmware
  settings), screenshots/screen recordings of a live session.
- **v0.2** — shell ergonomics: command history (↑/↓), Tab completion, Home/End/
  Delete line editing, Ctrl+L / Ctrl+C.
- **v0.2** — slot filling: `INTENT_CALC` with parentheses and operator
  precedence, `INTENT_SCREENTEST` with colour/pattern arguments.
- **v0.3** — more intents and a larger model, still int8 and still ROM-resident;
  the intent-adding pipeline is already documented in CONTRIBUTING.md.
- **v0.4** — a minimal read-only storage region on reserved disk sectors (the
  first step toward a filesystem; write support needs careful design).
- **Later** — VESA framebuffer plus a hand-drawn bitmap font, which is the only
  honest path to CJK display; SMP/APIC experiments as a separate performance
  study.

Explicitly out of scope for the foreseeable future: POSIX compatibility, ELF
loading, user space, a network stack, a GUI/window manager, SIMD acceleration.

---

## Repository layout

```
boot/      boot.asm           512-byte MBR (keystone, Intel syntax)
core/      types io string div start idt pic globals banner
drivers/   vga  kbd           0xB8000 text + CRTC cursor, PS/2 Set 1
mm/        e820.h pmm         E820 ABI + 4 KB-frame bitmap allocator
nlu/       nlu                line → 256-dim int8 features
nn/        config.h model_weights.h nn.c   int8 MLP, generated weights
shell/     intent.h shell dispatch        line editor + 13-entry VTable
hw/        calc cpuinfo diskinfo help_about meminfo modelinfo
           power screentest selftest      the hardware actions
tools/     build-time Python: corpus, training, ELF/instruction scan,
           Unicorn bridge, VGA dump
build.py   build pipeline          test.py   test gate
docs/      ARCH.md (architecture)  PRD.md (product requirements)
```

---

## Documentation

- [README_CN.md](README_CN.md) — this document in Chinese
- [docs/ARCH.md](docs/ARCH.md) — architecture, memory map, ABI, quantization
  scheme, task breakdown
- [docs/PRD.md](docs/PRD.md) — product requirements, intent catalogue,
  non-goals
- [CONTRIBUTING.md](CONTRIBUTING.md) — environment, build, gate, code style,
  and how to add a new intent

---

## License

MIT. See [LICENSE](LICENSE).

Copyright (c) 2026 Luo Ke.
