# AIOS v0.1

> **[English README](README.md)** ｜ [系统架构文档](docs/ARCH.md) ｜ [产品需求文档](docs/PRD.md) ｜ [贡献指南](CONTRIBUTING.md)

**AIOS 是一个裸机（bare-metal）AI 操作系统：从 BIOS 交出控制权的第一条指令开始，对 CPU、内存、显卡、键盘、电源控制器的每一次访问，都由 AIOS 自己的代码完成。它下面没有任何操作系统。** 你用一句日常英文说出想做的事，端侧 int8 神经网络识别出意图，AIOS 立刻对真实硬件执行动作。

Legacy BIOS 加载 512 字节的 MBR，引导层探测内存、进入 32 位保护模式，然后 freestanding 内核直接操作 VGA、PS/2、PCI、ATA、CMOS 与电源控制端口。底下没有宿主操作系统、没有 libc、没有文件系统、没有调度器、没有网络协议栈、没有浮点运行时。

---

## 为什么要做 AIOS

> 构建 AIOS 的初衷是因为：目前的大模型都是加载在操作系统之上，硬件大部分的能力其实交给了操作系统调度，AI 并不能真正发挥硬件 100% 的能力。所以让 AI 自己控制硬件，或许是个办法。
>
> AIOS 是一个裸机 AI 操作系统。从 BIOS 交出控制权的第一条指令开始，对 CPU、内存、显卡、键盘、电源控制器的每一次访问，都由 AIOS 自己的代码完成，它下面没有任何操作系统。你用一句日常英文说出想做的事，端侧的 int8 神经网络识别出意图，AIOS 立刻对真实硬件执行操作。
>
> 这是一个展示原型，目前还不完善，不是生产系统。不要把 `aios.img` 或 `aios-hdd.img` 写到存有你在意的数据的盘上。
>
> 个人能力有限，愿有志之士共建。

## 它不是什么

提 issue 之前请先读完这一节：

- **它不是 Linux，也不基于 Linux。** 没有 Linux 内核、没有发行版、没有 POSIX 层、没有 ELF 加载器、没有用户态。
- **它不是安卓，也不是"安卓套壳 AI 手机系统"。** 阿里 QWEN BOOK 那类思路是把 AI 层架在安卓之上；AIOS 正相反——**把安卓整个去掉**，由 AIOS 自己接管硬件的所有调用。
- **它下面没有任何操作系统。** 没有宿主 OS、没有第三方 bootloader（没有 GRUB）、没有 unikernel/LibOS 框架、没有静态链接的 libc（没有 newlib、没有 musl）。只有两层：512 字节引导扇区 + freestanding i386 内核。
- **它不是通用操作系统。** 没有文件系统、没有网络、没有多任务、没有 shell 脚本、没有包管理器、不做 64 位长模式。
- **它不是聊天机器人。** 模型只有 12 个意图，唯一职责是把你这句话路由到一个硬件动作上，它不生成文本。

## 实验性声明 —— 写盘之前必读

> **这是一个教学 / 演示原型，不是生产系统。**
>
> **绝对不要把 `aios.img` 或 `aios-hdd.img` 写到存有你在意的数据的盘上。** `dd`、Rufus、balenaEtcher 会覆盖目标设备的开头，硬盘镜像还会写入分区表。请用闲置 U 盘、空白 SD 卡，或者 QEMU 这类模拟器。
>
> `reboot` 与 `shutdown` 会**立即执行、不二次确认**——因为也没有什么可丢失的（无文件系统、无持久化状态）。
>
> **目前 59/59 的测试门禁只在 Unicorn CPU 模拟器中验证过，AIOS 尚未在真机上实测。** 详见[已知限制](#已知限制)。

---

## 快速开始

### 1. 构建（约 1–2 分钟）

前置条件只有 **Python 3.11+**：编译器、汇编器、反汇编器和 CPU 模拟器都从 PyPI 装进虚拟环境。不需要 WSL、不需要 nasm/gcc/binutils、不需要 QEMU、不需要管理员权限。

**Windows（PowerShell）**

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

（不想激活虚拟环境的话，直接调用 `.venv\Scripts\python.exe` 或 `.venv/bin/python` 也可以——但**不要把解释器的绝对路径硬编码进提交**。）

### 2. 在模拟器里跑

```sh
qemu-system-i386 -fda aios.img
```

或者用硬盘 / U 盘镜像：

```sh
qemu-system-i386 -drive format=raw,file=aios-hdd.img
```

### 3. 在真机上跑

请用 `aios-hdd.img` 和一支**闲置** U 盘。软盘镜像主要给模拟器用，多数固件不会提供 USB 软驱启动项。

**Linux / macOS**（把 `/dev/sdX` 换成**整块设备**，不是某个分区）：

```sh
sudo dd if=aios-hdd.img of=/dev/sdX bs=1M conv=fsync status=progress
```

**Windows**：在 Rufus 或 balenaEtcher 中选择 `aios-hdd.img`，如有提示就选 BIOS/MBR，安全弹出后在固件设置里打开 **Legacy / CSM 启动**，并暂时关闭 Secure Boot。

在 `{AIOS}> ` 提示符下输入 `help`，或者直接说一句 *"what can you do"*。

---

## Python 的角色（请务必读完，这是最容易误解的一点）

**Python 只是构建期工具链。它不是操作系统的一部分，也不会在目标机器上运行。**

`tools/` 下的所有文件，以及 `build.py`、`test.py`，都只在你的宿主机上跑。构建过程用 Python 驱动四个 PyPI 包：

| 包 | 构建期职责 |
| --- | --- |
| `keystone-engine` | 把 `boot/boot.asm` 汇编成 512 字节 MBR |
| `ziglang` | `zig cc` 把所有 `.c` 编译链接成 freestanding i386 ELF；`zig objcopy` 抽出裸二进制 |
| `capstone` | 反汇编 `kernel.bin`，统计禁用指令 |
| `unicorn` | 模拟一颗 x86 CPU，让 `test.py` 能无头启动镜像 |

**运行期产物**是 `aios.img` / `aios-hdd.img`：纯 x86 机器码，由 BIOS 直接加载执行。镜像一旦生成，Python 就不再参与。运行期**零 Python、零 libc、零浮点、零堆**。

### 硬证据

构建流程会在内核二进制不干净时直接拒绝出镜像。构建后的 `build/report-instr.txt` 内容如下：

```
fpu_ops=0          <-- x87 指令数为 0
sse_ops=0          <-- SSE 指令数为 0
mmx_ops=0          <-- MMX 指令数为 0
libc_symbols=0     <-- 未定义 libc 符号数为 0
undefined_symbols=
total_insns=...           （每次构建会变）
kernel_bin_bytes=...      （每次构建会变）
boot_bin_bytes=512
```

内核编译选项含 `-mno-80387 -mno-sse -mno-sse2 -mno-mmx -nostdlib -ffreestanding -fno-builtin`，因此任何 x87/SSE/MMX 指令、任何未定义的 libc 符号都会让构建失败，而不是被悄悄打进镜像。

由此推论两点：**你没法往 AIOS 上 `pip install` 任何东西**，也**没法在运行期加载模型文件**——因为没有文件系统。新权重只能在宿主机上生成、再编译进内核。

---

## 架构一览

```
  BIOS / UEFI-CSM                （不由我们实现）
 ─────────────────────────────────────────────────────
  L1 引导层     512 B MBR @ 0x7C00
      A20 → E820 → INT 13h 载核 → GDT → CR0.PE
 ─────────────────────────────────────────────────────
  L2 内核层     freestanding i386 C @ 0x10000
      drivers/  VGA 0xB8000 · PS/2 键盘
      mm/       物理内存位图分配器
      nlu/ nn/  int8 MLP 推理引擎 + 权重 ROM
      shell/    行编辑器 · 意图路由 · 动作执行
      hw/       硬件动作本体
```

1. BIOS 把 MBR 加载到物理地址 `0x7C00`。
2. 引导层初始化段寄存器与栈、开启 A20、在 `0x8000` 取 E820 内存表、把内核读到 `0x10000`、安装平坦 GDT、置 CR0.PE。
3. `_start` 把栈设到 `0x90000`、清 `.bss`、调用 `kernel_main`。
4. 初始化 VGA、PMM、PS/2 与模型，出现提示符 `{AIOS}> `。
5. 每一行输入变成 256 维 int8 特征向量（token unigram/bigram/trigram + 字符级 trigram 的哈希技巧），整数 MLP（256-64-ReLU-12，权重 ROM 17456 字节）给出 Top-3 意图，再由一张表分派到一个硬件动作。

PMM 位图放在二进制之外的物理地址 `0x40000`，AI 专属竞技场是 `0x60000..0x7FFFF`。这样 `.bss` 不会把裸内核撑大，镜像才装得进软盘。

### 构建产物

| 产物 | 说明 |
| --- | --- |
| `aios.img` | 精确到 1,474,560 字节的软盘镜像 |
| `aios-hdd.img` | 10 MiB 硬盘 / U 盘镜像，含一个激活的 `0x7F` 类型分区 |
| `build/kernel.elf`、`build/kernel.bin` | 链接产物与裸二进制 |
| `build/report-instr.txt` | 零 FPU / SIMD / libc 门禁 |
| `build/manifest.json` | 源文件、尺寸、编译开关、LBA 布局 |
| `build/train_report.json` | 训练 + 量化标定 + 精度报告 |
| `build/screen.html` | 显存 dump（`--dump`） |

### 构建选项

| 参数 | 作用 |
| --- | --- |
| `--dump` | 在 Unicorn 中启动镜像，把 80×25 显存渲染到 `build/screen.html` |
| `--kbd-mode 1` | 默认；真机键盘模式（最小 IDT + IRQ1 + `sti;hlt`） |
| `--kbd-mode 0` | 纯轮询；做 Unicorn 专项实验时用 |
| `--prompt-style 1` | 默认提示符 `{AIOS}> `；`0` 则为 `AIOS> ` |
| `--two-sector` | 强制双扇区引导布局（见下） |
| `--slim` | 裁剪可选引导功能（例如 CHS 读盘回退） |
| `--retrain` / `--skip-train` | 强制 / 跳过语料与模型重新生成 |

引导汇编器先尝试分区表安全的单扇区 MBR。若代码超过 446 字节，构建会自动改用 `TWO_SECTOR` 布局：512 字节 MBR 再加载第二个引导扇区，内核顺延到 LBA 2。当前代码树就是以 `TWO_SECTOR`、`kernel_lba = 2` 构建的。

---

## 端侧 NLU 与模型

```
"what cpu is this"
   → 归一化（转小写、非字母数字转空格、折叠连续空格）
   → 分词（≤ 32 个 token）
   → token unigram / bigram / trigram + 字符级 trigram
   → 每个 n-gram 做 FNV-1a 32 位哈希
   → 有符号计数累加进 256 个桶
   → 统一 clamp 到 [-127, 127]  →  256 维 int8 特征
   → MLP 256 → 64 (ReLU) → 12 (线性)，全程 int32 运算
   → 定点 softmax（Q15 exp 查找表，513 项）
   → Top-3 意图 + 整数百分比
   → dispatch() → 一个硬件动作
```

| 属性 | 取值 |
| --- | --- |
| 输入 | 256 维 int8 有符号计数特征 |
| 网络 | `256 → 64 (ReLU) → 12 (线性)`，单层隐层 |
| 权重 | `W1`/`W2` 为 int8，`b1`/`b2` 为 int32，累加器 int32 |
| 权重 ROM | **17456 字节** = 16384 (`W1`) + 256 (`b1`) + 768 (`W2`) + 48 (`b2`) |
| Softmax | 513 项 Q15 `exp` 查找表，缩放只用移位 |
| 兜底 | Top-1 置信度 < `CONF_THRESHOLD`（35%）→ `INTENT_FALLBACK` |
| 运算 | 纯整数；无 x87/SSE/MMX；缩放不用除法 |

在留出集上的实测结果（`build/train_report.json`，种子 `20260101`，每类 120 条）：

| 指标 | 数值 |
| --- | --- |
| Top-1 准确率 | **0.9965**（288 条验证样本） |
| 扰动集 Top-1 | **0.9961**（255 条扰动样本） |
| int8 与 float 一致率 | **1.0** |
| C 与 Python 特征向量 | **260/260 逐字节一致** |
| 前向 golden 向量 | **40/40 逐字节一致** |

> 语料由模板机器生成，因此这些数字衡量的是**整条流水线的鲁棒性**（大小写、标点、拼写错误、词序），而不是真实场景下的对话准确率。

### 13 项分派表

模型 softmax 只有 **12** 个输出；`INTENT_FALLBACK` 是第 13 项表项，由置信度阈值触发，不由网络输出。顺序必须与 `shell/intent.h`、`shell/dispatch.c`、`test.py` 三处一致：

`CLEAR`、`MEMINFO`、`CPUINFO`、`SELFTEST`、`DISKINFO`、`MODELINFO`、`CALC`、`SCREENTEST`、`HELP`、`ABOUT`、`REBOOT`、`SHUTDOWN`、`FALLBACK`

| 意图 | 真实硬件动作 |
| --- | --- |
| `CLEAR` | 向 `0xB8000` 全写空格，CRTC 光标归零 |
| `MEMINFO` | E820 内存表 + PMM 分配器统计 + AI 占比 |
| `CPUINFO` | `cpuid` leaf 0/1/0x80000002–4：厂商串、品牌串、特性位 |
| `SELFTEST` | PCI 配置空间扫描 + 1 MB 内存走查 + CMOS/RTC |
| `DISKINFO` | ATA PIO identify（端口 `0x1F0` / `0x170`） |
| `MODELINFO` | 报告正在跑的模型本身 |
| `CALC` | 两操作数整数 `+ - * /`，支持十进制与 `0x` 十六进制 |
| `SCREENTEST` | 16 色色带、棋盘格、字符雾化渐变 |
| `HELP` / `ABOUT` | 固定 golden 文案 |
| `REBOOT` | `out 0x64, 0xFE`（8042 复位） |
| `SHUTDOWN` | APM → ACPI `0x604 ← 0x2000` → `hlt` |
| `FALLBACK` | 打印它猜的 Top-3，并给出建议说法 |

---

## 设计约束与原因

下面每个看起来奇怪的决定，都源自"底下什么都没有"这一前提。

| 决定 | 原因 |
| --- | --- |
| **int8 定点、不用浮点** | 内核用 `-mno-80387 -mno-sse -mno-sse2 -mno-mmx` 编译。要用 x87 就得初始化 FPU，还得往一个没有 libc 的二进制里塞软浮点辅助函数。所有缩放取 2 的幂，乘法就是移位。 |
| **缩放只用移位、不用除法** | 保证 C 与 Python 逐位一致：所有被移位的值在移位前非负，于是 C 的算术右移恰好等于数学上的 floor。 |
| **用哈希技巧而不是词表** | 没有文件系统，运行期根本读不到词典。哈希到 256 个桶的特征向量零存储、O(1) 查找。 |
| **桶数取 256** | 2 的幂，桶下标就是 `hash & 255`，不需要除法。四类 n-gram 共用一个累加向量。 |
| **12 个意图** | 一一对应 `hw/` 里真实存在的硬件动作。想加第 13 个动作意味着要重新训练，不只是加一行表。 |
| **`FALLBACK` 不是 softmax 输出** | 第 13 类需要为"其他一切"这个无穷集合准备训练数据，不如置信度阈值泛化得好。 |
| **权重编译进内核** | 没有文件系统，运行期无法读模型文件。`nn/model_weights.h` **就是**那个模型。 |
| **无堆、无动态分配** | 没有可增长的分配器，也没有 MMU 做保护。缓冲要么静态放 `.bss`，要么放在二进制之外的固定物理地址。 |
| **PMM 位图放固定物理地址** | 若放进 `.bss`，`objcopy -O binary` 会给裸内核补上几百 KB 的零，软盘就装不下了。 |
| **单线程轮询** | 没有调度器、没有时钟中断、没有抢占。两次击键之间 `hlt` 就是全部的电源管理。 |
| **只支持 ASCII 英文** | 见下节。 |

---

## 已知限制

- **只支持 Legacy BIOS 或 UEFI CSM。** 没有 CSM 的纯 UEFI 固件无法执行 512 字节 MBR。本系统没有 EFI 应用，也不支持 GPT。
- **只能输入输出 ASCII 英文。** VGA 80×25 文本模式只有 256 个字形的码页 ROM，没有汉字（也没有任何其他非拉丁文字）字形，也没有输入法。要支持中文必须自绘 16×16 点阵字库（6,763 字约 216 KB，已超过整个内核预算）并实现一套拼音输入法，v0.1 不做。
- **门禁只在模拟器中验证。** 59 个用例全部在 **Unicorn** CPU 模拟器中、配合脚本化的 BIOS 桩与端口桩跑通。**AIOS 尚未在真机上启动和实测。** 固件行为（INT 13h 扩展、A20 各种开启方式、USB 键盘的 PS/2 legacy 模拟）可能与模拟器不同。
- **没有文件系统。** 运行期不能读写任何东西。磁盘访问仅限于启动时的内核读取和一次 ATA identify 查询。
- **没有网络协议栈、没有调度器、没有多任务、没有用户态、不做 64 位长模式。** 单线程、i386 32 位保护模式、轮询式 I/O。
- **没有持久化状态。** 每次上电都从镜像重新构建一切。
- **`reboot` / `shutdown` 立即执行，不二次确认。**
- **意图语料是合成的。** 由模板加可控扰动生成；超出这些模板的自然说法可能落到 `FALLBACK`。
- **没有时钟中断驱动。** 光标闪烁由 VGA CRTC 硬件完成，内核里没有任何软件翻光标循环。

---

## 测试门禁

`python test.py` 为每个用例打印一行 `[PASS|FAIL] layer=<layer> case=<name>`。门禁覆盖引导层、VGA、键盘、PMM、分派、每个硬件动作、golden 文案与模糊测试边界。AI NLU 与 MLP 的 golden 向量测试挂在同一张注册表上。只要有一条失败，或禁用指令计数非零，命令就以非零码退出。

当前状态：**59 / 59 全通过**

```
boot=12 dispatch=5 fuzz=5 golden=4 hwaction=14 kbd=7 pmm=5 vga=7
```

**提 PR 之前必须 59 条全绿**，详见[贡献指南](CONTRIBUTING.md)。

---

## 排错清单

1. **黑屏：** 打开 Legacy Boot/CSM；纯 UEFI 无法执行这个 MBR。
2. **报 `Missing operating system`：** 把整个镜像写到整块设备，而不是写进已有文件系统或某个分区。
3. **U 盘不在启动项里：** 用 `aios-hdd.img`，选 USB-HDD 模式，暂时关闭 Secure Boot；软盘镜像主要给模拟器用。
4. **光标有但键盘没反应：** 用 `--kbd-mode 0` 重新构建，判断是否是固件 / PIC 的 IRQ 路由问题；换一个自带 PS/2 键盘，而不是没有 legacy 模拟的 USB 键盘。
5. **启动画面之前就报 `disk error` 或卡死：** 打开 BIOS 的 INT 13h 扩展，或改用软盘镜像让 CHS 几何为 18 扇区 / 2 磁头。
6. **构建报禁用指令 / 符号：** 查看 `build/report-instr.txt`；内核运算保持纯整数，不要引入托管 C 库头文件。

---

## 路线图

按"单位风险换来的认知收益"排序。

- **v0.1.x** —— 真机启动报告（一小张机型 + 固件设置矩阵），真机会话截图 / 录屏。
- **v0.2** —— 终端易用性：命令历史（↑/↓）、Tab 补全、Home/End/Delete 行内编辑、Ctrl+L / Ctrl+C。
- **v0.2** —— 槽位抽取：`INTENT_CALC` 支持括号与优先级，`INTENT_SCREENTEST` 支持颜色 / 图案参数。
- **v0.3** —— 更多意图与更大的模型，仍是 int8、仍驻留 ROM；新增意图的完整流程已写在贡献指南里。
- **v0.4** —— 在保留扇区上做一个只读存储区（迈向文件系统的第一步；可写需要另行严谨设计）。
- **更远** —— 切到 VESA 帧缓冲并自绘点阵字库，这是通向中文显示的唯一诚实路径；SMP/APIC 作为独立的性能对比实验。

可预见的将来明确不做：POSIX 兼容、ELF 加载、用户态、网络协议栈、图形界面 / 窗口管理器、SIMD 加速。

---

## 仓库结构

```
boot/      boot.asm           512 字节 MBR（keystone，Intel 语法）
core/      types io string div start idt pic globals banner
drivers/   vga  kbd           0xB8000 文本 + CRTC 光标，PS/2 Set 1
mm/        e820.h pmm         E820 ABI + 4KB 帧位图分配器
nlu/       nlu                一行文本 → 256 维 int8 特征
nn/        config.h model_weights.h nn.c   int8 MLP 与生成的权重
shell/     intent.h shell dispatch        行编辑器 + 13 项 VTable
hw/        calc cpuinfo diskinfo help_about meminfo modelinfo
           power screentest selftest      硬件动作
tools/     构建期 Python：语料、训练、ELF/指令扫描、Unicorn 桥、显存 dump
build.py   构建流水线          test.py   测试门禁
docs/      ARCH.md（架构）      PRD.md（产品需求）
```

---

## 相关文档

- [README.md](README.md) —— 英文版说明
- [docs/ARCH.md](docs/ARCH.md) —— 架构、内存布局、ABI、量化方案、任务分解
- [docs/PRD.md](docs/PRD.md) —— 产品需求、意图清单、明确不做清单
- [CONTRIBUTING.md](CONTRIBUTING.md) —— 环境、构建、门禁、代码风格，以及如何新增一个意图

---

## 许可证

MIT，见 [LICENSE](LICENSE)。

Copyright (c) 2026 Luo Ke.
