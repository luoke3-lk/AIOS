# Contributing to AIOS

> 中文读者请先看 [README_CN.md](README_CN.md)；本文档是贡献者操作手册。

Thanks for your interest in AIOS. This is a **teaching-oriented bare-metal
prototype**, so the review bar is deliberately strict about one thing: the
kernel must stay *freestanding*. Everything else is negotiable.

Before you start, read:

- [README.md](README.md) — what this project is and is not
- [docs/ARCH.md](docs/ARCH.md) — memory map, ABIs, quantization scheme
- [docs/PRD.md](docs/PRD.md) — intent catalogue and the explicit non-goals

---

## 1. Setting up the environment

Requirements: **Python 3.11+**. That is the only system-level dependency — the
compiler, assembler, disassembler and CPU emulator are installed from PyPI into
a virtual environment. No WSL, no nasm/gcc/binutils, no QEMU, no administrator
rights.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux / macOS**

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The four pinned packages:

| Package | Job |
| --- | --- |
| `ziglang` | `zig cc` / `zig objcopy` — the freestanding i386 toolchain |
| `keystone-engine` | assembles `boot/boot.asm` |
| `capstone` | disassembles `kernel.bin` for the forbidden-instruction scan |
| `unicorn` | x86 CPU emulator that runs the test gate headlessly |

> **Never commit an absolute interpreter or home-directory path.** Use
> `python` / `python3`, or a relative `.venv/...` path.

## 2. Building

```sh
python build.py            # 8-step pipeline -> aios.img, aios-hdd.img
python build.py --dump     # also boot in Unicorn and dump the VGA buffer
python build.py --retrain  # force corpus + model regeneration
python build.py --help     # --slim --two-sector --kbd-mode --prompt-style
```

The build fails loudly if the kernel contains any x87/SSE/MMX instruction or any
undefined libc symbol. That is intentional — see `build/report-instr.txt`.

## 3. Running

```sh
qemu-system-i386 -fda aios.img
qemu-system-i386 -drive format=raw,file=aios-hdd.img
```

Real hardware: use `aios-hdd.img`, a **spare** USB stick, and Legacy/CSM boot.
See the "Experimental" warning in the README first.

## 4. The test gate — must be green before a PR

```sh
python test.py
```

Every case prints as `[PASS|FAIL] layer=<layer> case=<name>` and the command
exits nonzero on any failure. Current baseline: **59 / 59 passing**
(`boot=12 dispatch=5 fuzz=5 golden=4 hwaction=14 kbd=7 pmm=5 vga=7`).

**A pull request with a red gate will not be reviewed.** If you change
behaviour, change the test in the same commit and say why in the PR body.

Useful single-purpose commands:

```sh
python tools/train.py --eval     # JSON accuracy report only
python tools/train.py --diag     # confusion matrix / conflicting utterances
python build.py --kbd-mode 0     # polling keyboard, for Unicorn experiments
```

---

## 5. Code style — hard constraints

These are not preferences. Violating them either breaks the build or silently
breaks the "no OS underneath" guarantee.

### 5.1 Freestanding C only

**Banned headers** anywhere under `core/ drivers/ mm/ nlu/ nn/ shell/ hw/`:

```c
#include <stdint.h>   <stddef.h>   <string.h>   <stdio.h>
#include <stdlib.h>   <math.h>     <stdbool.h>  <limits.h>
/* ...and any other hosted header */
```

Use instead:

- `core/types.h` — `u8 u16 u32 u64 s8 s16 s32 s64 size_t NULL PACKED STATIC_ASSERT`
- `core/string.h` — `memcpy memset memmove memcmp strlen strcmp strncmp strcpy
  strncpy strchr u32_to_dec s32_to_dec u32_to_hex u64_to_hex to_lower ...`
- `core/io.h` — `inb outb inw outw io_wait`
- `core/div.c` — hand-written `__udivsi3` / `__umodsi3`

There is a test case (`no_hosted_headers`) that greps for these. Do not
"temporarily" disable it.

### 5.2 No floating point

- No `float`, no `double`, no floating literals in kernel sources.
- No x87 / SSE / AVX / MMX instructions. The kernel is compiled with
  `-mno-80387 -mno-sse -mno-sse2 -mno-mmx` and scanned after linking.
- All scaling uses powers of two, so **a multiply is a shift**. Never divide to
  rescale.
- Softmax uses the Q15 `exp` lookup table in `nn/model_weights.h`.

Why: on bare metal there is no libc to provide soft-float helpers, and a shift
is exactly reproducible in the Python reference (`>>` on a non-negative value
is floor division in both languages).

### 5.3 No dynamic allocation

- No `malloc`, `free`, `calloc`, `realloc`. There is no heap.
- Small buffers go in `core/globals.c` (static `.bss`, bracketed by the
  `0xCAFEBABE` / `0xDEADBEEF` canaries the fuzz tests check).
- Large structures (the PMM bitmap at `0x40000`, the AI arena at
  `0x60000..0x7FFFF`) live at **fixed physical addresses outside the binary**.
  Putting them in `.bss` would make `objcopy -O binary` pad the raw kernel with
  hundreds of KB of zeros and it would stop fitting on a floppy.

### 5.4 Integer discipline

- Use the `core/types.h` typedefs; never bare `int`/`long` for anything whose
  width matters.
- Accumulators are `s32`. Never `int16` for an intermediate value.
- **No u64 division and no u64 variable shifts** — they drag in `__udivdi3` /
  `__ashldi3` from a runtime we do not have. Split into 32-bit slices.

### 5.5 Determinism

C and Python must agree **byte for byte**. If you touch `nlu/nlu.c` or
`nn/nn.c`, you must also update the reference implementation in
`tools/train.py` and regenerate the goldens. The gate checks
`260/260` feature vectors and `40/40` forward vectors.

### 5.6 Layout and naming

| Rule | Detail |
| --- | --- |
| Function prefixes | `vga_` `kbd_` `pmm_` `nlu_` `nn_` `shell_` `hw_` |
| Types | `*_t` |
| Macros | `UPPER_SNAKE` |
| File-static globals | `g_*` |
| Indentation | 4 spaces, no tabs |
| Braces | K&R |
| Line length | ≤ 100 columns |
| Per-file header | first ~10 lines state responsibility, dependencies, memory cost |

### 5.7 Output text

- Anything printed to the screen must be **ASCII** (`0x20`–`0x7E`). VGA text
  mode has no glyphs for anything else.
- Comments in the source may be Chinese or English.

### 5.8 Adding a dependency

There are four PyPI packages, all build-time only. Adding a fifth requires a
reason in the PR. Adding anything that runs *on the target machine* is out of
scope by definition.

---

## 6. Adding a new intent — the full flow

The model's softmax has 12 outputs; `INTENT_FALLBACK` is the 13th table entry
and is selected by the confidence threshold, not by the network. **Adding a new
intent therefore changes the network shape and invalidates every golden
vector.** Do all of the following in one PR.

Reference order (must match in `shell/intent.h`, `shell/dispatch.c` and
`test.py`):

```
CLEAR, MEMINFO, CPUINFO, SELFTEST, DISKINFO, MODELINFO, CALC,
SCREENTEST, HELP, ABOUT, REBOOT, SHUTDOWN, FALLBACK
```

`FALLBACK` is always last.

### Step 1 — corpus

Edit `tools/gen_corpus.py`:

1. Add the intent name to the `INTENTS` list, **inserted before `FALLBACK`**.
2. Add seed utterances and the perturbation templates for the new class
   (existing classes have 120 generated utterances each — match that).
3. Regenerate:

```sh
python tools/gen_corpus.py        # -> tools/intent_corpus.json
```

### Step 2 — retrain and re-export

```sh
python tools/train.py             # or: python build.py --retrain
```

This rewrites, do **not** hand-edit any of them:

- `nn/config.h` — `NN_CLASSES` becomes 13, `WEIGHTS_BYTES` changes, the
  fixed-point shifts (`W1_SHIFT`, `ACT1_SHIFT`, `W2_SHIFT`, `OUT_SHIFT`) are
  re-calibrated
- `nn/model_weights.h` — `W1q`, `b1q`, `W2q`, `b2q`, `exp_lut_q15`
- `tools/golden_features.json`, `tools/golden_vectors.json`
- `build/train_report.json`

Check the report: `top1` must stay ≥ 0.95 and `perturb_top1` ≥ 0.85, otherwise
the build stops. If accuracy drops, add corpus data — do **not** hand-tune the
quantization constants.

### Step 3 — enum

`shell/intent.h`: add the enum member at the matching index, add the
`STATIC_ASSERT`, and bump `INTENT_COUNT`.

```c
typedef enum {
    ...
    INTENT_SHUTDOWN = 11,
    INTENT_NEWTHING = 12,   /* <- your new intent */
    INTENT_FALLBACK = 13
} intent_id_t;
```

### Step 4 — the hardware action

1. Implement `act_newthing` in a new file under `hw/` (or extend an existing
   one). Signature: `void act_newthing(const char *line, const nn_result_t *r);`
2. It must touch real hardware (ports, CPUID, VGA attribute plane, ...). If it
   only prints text, reconsider whether it deserves an intent.

### Step 5 — the dispatch table

`shell/dispatch.c`: add the row to `INTENT_TABLE` at the **same index** as the
enum. Order is load-bearing — `dispatch()` indexes the array directly and
`test.py` asserts `INTENT_TABLE[i].id == i`.

```c
{INTENT_NEWTHING, "INTENT_NEWTHING", "short desc", "example sentence", act_newthing},
```

Do **not** add an `if`/`strcmp` chain. `dispatch()` is the single dispatch
point; a test greps for `strcmp` outside `hw/`.

### Step 6 — tests

1. Update the expected intent list in `test.py` so it matches the new order.
2. Add at least one end-to-end case: type a sentence, assert the screen shows
   `AI: <INTENT> (`.
3. Add a fallback case if your intent changes the confidence distribution.

### Step 7 — full gate

```sh
python build.py && python test.py
```

Everything green, including `report_zero_forbidden`, `no_hosted_headers`,
`dispatch_table_size_13` (now 14), and `dispatch_id_order_match`.

---

## 7. Pull request checklist

- [ ] `python build.py` succeeds from a clean venv
- [ ] `python test.py` is **fully green** (no skipped, no ignored failures)
- [ ] `build/report-instr.txt` still reads `fpu_ops=0 sse_ops=0 mmx_ops=0 libc_symbols=0`
- [ ] No hosted C headers, no `float`/`double`, no `malloc`
- [ ] No absolute local paths, no personal directories, no secrets
- [ ] Screen-facing strings are ASCII
- [ ] New behaviour has a new test in the matching `layer=`
- [ ] PR body says which layer (`boot` / `vga` / `kbd` / `pmm` / `nlu` / `nn` /
      `dispatch` / `hwaction`) is affected

---

## 8. Reporting issues

Please include:

1. Host OS and Python version
2. The exact command you ran
3. `build/report-instr.txt` and the failing lines of `python test.py`
4. If real hardware: machine model, firmware vendor, and whether Legacy/CSM was
   enabled

Known-and-accepted, please do not report as bugs: no Chinese input/output, no
filesystem, no network, no multitasking, no pure-UEFI boot, and `reboot` /
`shutdown` having no confirmation prompt. See
[Known limitations](README.md#known-limitations).
