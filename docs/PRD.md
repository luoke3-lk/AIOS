# AIOS v0.1 产品需求文档（PRD）

| 项目项 | 内容 |
| --- | --- |
| 文档版本 | v0.1-draft |
| 作者 | 许清楚（软件产品经理） |
| 状态 | 待评审（主理人定夺后转交架构师） |
| 语言 | 中文 |
| 技术实现栈 | Python 工具链 + i386 freestanding C + x86 汇编（无第三方 OS / 无 libc / 无 QEMU） |
| 项目代号 | `aios`（建议仓库/工程名） |
| 交付物形态 | 单一可启动磁盘镜像 `aios.img` + 源码树 + Unicorn 回归测试集 |

---

## 0. 原始需求复述（发起人：罗轲）

> 「不做套壳。市面所有本地 AI 都是 Windows/Linux + 推理框架。我要的是没有任何上层操作系统的、**从 BIOS 上电第一条指令起就由自研代码接管硬件**的 AI 原生操作系统。
> 只有两层：512 字节 MBR 引导层 + 极简 AI 主内核层。不要文件系统、不要图形服务、不要网络栈、不要多任务调度。
> 开机：清屏 → 输出启动提示 → 固定 `>` 提示符 + 闪烁光标 + 实时键盘回显 + 回车换行刷新提示符，效果像 90 年代的 Apple 机 / DOS。
> 系统唯一使命：硬件初始化 + 终端交互 + 原生底层 AI 推理。**内存 100% 供给 AI**，无调度损耗。
> 出来一个大括号，一个光标，然后只需要说我要干什么，系统就可以自己开始工作那种。
> QWEN BOOK 也是这个思路但它基于安卓二次开发，我们要的是**去掉安卓，完全用 AIOS 控制硬件的所有调用**。」
>
> 补充说明（主理人确认）：硬件平台由最初设想的 H61 放开为**通用 x86 适配**（legacy BIOS + 现代 UEFI 的 CSM 兼容模式均可启动）。文档中的技术细节允许修正，但主线思路不变。

---

## 1. 产品目标（5 条）

| # | 目标 | 成功度量 |
| --- | --- | --- |
| G1 | **真裸机原生，零套壳**：自 BIOS 移交控制权之后，CPU、内存、显卡、键盘的全部访问路径均为自研代码，不存在任何上层 OS、libc、第三方内核或运行时 | 链接产物为 freestanding 裸二进制；`objdump` 结果中不含任何 libc 符号；整条启动链可被 Unicorn 从 `0xFFFFFFF0` 的全零/自造 BIOS 桩起步完整追踪到 `kernel_main` |
| G2 | **极简两层、可讲解**：仅「引导层 512B + 内核层」，无文件系统、无进程、无中断式抢占 | 源码树仅 `boot/ drivers/ mm/ nn/ shell/` 五个模块；内核裸镜像 ≤ 128 KB；新增一页讲稿即可把每一层用一张图讲清 |
| G3 | **DOS/90 年代观感的交互终端**：80×25 VGA 文本、固定提示符、硬件自动闪烁光标、即时回显 | 见 §6 交互规格；按键到屏幕字符延迟在 Unicorn 指令计数下 ≤ 2 万条指令 |
| G4 | **AI 直接驱动硬件**（核心卖点）：用户说一句自然语言 → 端侧 int8 量化 MLP 推理出意图 → 系统**立刻对该硬件执行动作**，而不是打印帮助文本 | ≥ 12 类意图全部映射到真实硬件动作；每条响应输出 Top-3 意图 + 置信度，肉眼可辨是模型在推理而非 if-else |
| G5 | **在受限 Windows 环境下端到端可复现**：无 WSL、无 nasm/gcc/qemu、无管理员权限也能 `python build.py` + `python test.py` 全绿 | 只依赖 PyPI 三种包：`ziglang`、`keystone-engine`、`unicorn-engine`；构建脚本在纯净虚拟环境内一次通过 |

### 1.1 分层结构（v0.1 冻结）

```
 ┌───────────────────────────────────────────────┐
 │  BIOS / UEFI-CSM        （不由我们实现）        │
 ├───────────────────────────────────────────────┤
 │  L1 引导层   boot.asm → 512B MBR  (0x7C00)     │
 │      A20 / E820 / INT13h 载核 / GDT / 进保护模式 │
 ├───────────────────────────────────────────────┤
 │  L2 内核层   i386 freestanding C  (@0x10000)    │
 │      drivers : VGA 0xB8000  |  PS/2 轮询        │
 │      mm      : 物理内存位图分配器                │
 │      nn      : int8 量化 MLP 推理引擎 + 权重 ROM │
 │      shell   : 行编辑器 + 意图路由 + 动作执行器   │
 └───────────────────────────────────────────────┘
```

---

## 2. 目标用户与使用场景

### 2.1 目标用户

| 人群 | 画像 | 核心诉求 |
| --- | --- | --- |
| P1 发起人本人（罗轲） | 有一定底层认知、追求"亲手做出来"的技术实践者 | 证明"从零写一个能跑 AI 的 OS"是可完成的；看到自己的名字出现在开机画面上 |
| P2 OS/内核教学者与学习者 | 需要能被逐个 gdb/反汇编讲解的最小范例 | 每层都能单独拿出来讲 15 分钟，不要一上来就是 10 万行 Linux |
| P3 端侧 / 嵌入式 AI 工程师 | 评估"AI 直接调度硬件"这一范式 | 看量化模型在没有 OS 调度损耗下的体积、指令数与延迟表现 |
| P4 技术演示/自媒体场景使用者 | 需要一个能在 3 分钟内抓住眼球的演示物 | 一台旧笔记本插上 U 盘 → 裸机黑屏白字 → 用自然语言让它跑硬件自检 |

### 2.2 使用场景

- **S1 学习与验证**：在自己的 Windows 笔记本上克隆代码，跑一条 `python build.py && python test.py`，Unicorn 里看到整条启动链与一次推理的断言全绿。耗时 < 5 分钟。
- **S2 真机演示**：把 `aios.img` 写进 U 盘/SD 卡，在支持 legacy BIOS 或 CSM 的机器上启动，输入 `run a hardware self test`，屏幕上出现 PCI 总线扫描结果与磁盘识别信息。
- **S3 二次开发与换模型**：工程师编辑 `tools/intent_corpus.json` 增加或修改说法，重跑训练脚本，新权重自动编译进镜像，无需改动任何内核代码。
- **S4 教学拆解**：在课堂上从 `boot.asm` 的 `cli / lgdt / mov cr0` 讲起，一路到 `nn/forward.c` 的定点乘加，全程可执行可调。

---

## 3. 用户故事（12 条）

| ID | 用户故事 | 验收锚点 |
| --- | --- | --- |
| US-01 | 作为**发起人**，我希望**只执行一条命令**就能在一个没有 WSL、没有 QEMU 的 Windows 上完成编译、链接、生成镜像与回归测试，以便**随时复现这条链路** | FR-B01, FR-B02 |
| US-02 | 作为**演示者**，我希望把镜像写进 U 盘后在 legacy BIOS / CSM 的机器上直接启动，以便**向别人证明这不是模拟器里的玩具** | FR-B03, FR-B04 |
| US-03 | 作为**使用者**，我希望开机后看到黑底浅字的 80×25 界面，一个固定提示符和一个自动闪烁的光标，以便**立刻确认系统已经把显卡交还给我** | FR-V01, FR-V03, FR-V04 |
| US-04 | 作为**使用者**，我希望用**日常英文短句**（而不是记命令）表达需求，例如 `i want a fresh empty screen`，以便**像对人说话一样驱动这台机器** | FR-N01~FR-N04 |
| US-05 | 作为**使用者**，我希望每条响应都先显示识别出的 Top-3 意图与置信度，以便**相信这是模型在推理而不是查表** | FR-N05 |
| US-06 | 作为**使用者**，我希望在我敲错的句子不被识别时，系统**给我一个诚实的兜底**（显示它猜的三个意图和建议说法），而不是沉默或崩溃 | FR-N06 |
| US-07 | 作为**工程师**，我希望输入 `what cpu is this` 就能拿到 CPUID 的厂商串、品牌串、家族/步进与特性位，以便**确认 CPU 真的被自研代码读到了** | FR-H02 |
| US-08 | 作为**工程师**，我希望输入 `run a hardware self test` 能触发 PCIe 配置空间扫描 + ATA identify + 内存走查，以便**一次拿到整机硬件画像** | FR-H03, FR-H04 |
| US-09 | 作为**工程师**，我希望在宿主机 Python 里改样例说法后重跑训练，权重自动变成 C 数组烘焙进镜像，以便**内核代码一行不改地换模型** | FR-N07, FR-B05 |
| US-10 | 作为**开发者**，我希望任何一处逻辑改动触发回归失败时测试名字就能指出坏在哪一层，以便**10 秒内定位是引导层还是推理层** | FR-B06 |
| US-11 | 作为**学习者**，我希望源码按 `boot / drivers / mm / nn / shell` 分层且每层 ≤ 3 个文件，以便**按层逐个读懂** | FR-B07 |
| US-12 | 作为**使用者**，我希望说 `reboot` / `shutdown` 时系统执行真实的 8042 复位 / APM 断电，以便**确认 AI 的输出确实连到了硬件引脚级动作** | FR-H05, FR-H06 |

---

## 4. 需求池（P0 / P1 / P2）

优先级定义：**P0 = v0.1 必须；P1 = 应当（有余力必做）；P2 = v0.1 明确不做，仅登记**。

### 4.1 P0 —— 引导层（L1）

| ID | 需求 | 验收标准（可测） |
| --- | --- | --- |
| FR-B01 | MBR 引导扇区：用 keystone 汇编，产物**恰好 512 字节**且末两字节 `0x55 0xAA` | `len(boot.bin) == 512` 且 `boot.bin[510:512] == b'\x55\xAA'`；超出即构建失败并报字节超限量 |
| FR-B02 | BIOS 以 `DL=<drive>` 加载至 `0x7C00` 后，`CS:IP` 修正、`DS/ES/SS` 设为 `0x0000`、栈置于 `0x7C00` 下方 | Unicorn 启动后读寄存器断言 `ds=es=ss=0x0000`、`sp <= 0x7C00` |
| FR-B03 | 开启 A20（优先 `INT 15h AX=2401`，失败回退 0x92 端口 Fast A20，再回退 8042） | Unicorn 桩返回失败时仍能落到下一种方式；`test_a20_fallback` 用例通过 |
| FR-B04 | E820 内存探测：结果表存于 `0x8000`，每条 24 字节，含有效条目数、总量统计 | 构造含 6 条 E820 记录的 Unicorn 桩，断言 `0x8000` 处条目数 == 6 且 Base+Length+Type 逐字节一致 |
| FR-B05 | INT13h AH=42 扩展读把内核从 **LBA 1** 起逐扇区载入物理地址 `0x10000` | 构造含 known-pattern 扇区的内存盘，断言 `0x10000` 处内容与镜像第 1..N 扇区逐字节相同 |
| FR-B05b | 若 BIOS 不支持 INT13h 扩展，回退 CHS (AH=02) 读盘 | 用例 `test_bios_no_lba_extension` 通过 |
| FR-B06 | 建立 GDT（null / code 0x00CF9A00'0000FFFF / data 0x00CF9200'0000FFFF），置 CR0.PE，**远跳转进入 32 位保护模式**（这一切在 MBR 内完成，无 stage 1.5） | Unicorn 在跳转后断言 `CR0.PE==1`、段寄存器指向 GDT 选择子、`EIP >= 0x10000` |
| FR-B07 | 内核入口：`linker.ld` 令 `.text` 起始 `0x10000`，入口符号 `kernel_main` 位于该地址 | `zig objcopy` 后二进制首字节等于 `_start` 机器码；`nm` 显示 `kernel_main @ 0x10000`（或带 header 时校验 header 魔数 `'AIOS'`） |

### 4.2 P0 —— 驱动层与终端

| ID | 需求 | 验收标准（可测） |
| --- | --- | --- |
| FR-V01 | VGA 文本模式驱动（0xB8000，80×25，属性字节方案见 §6.5）：`vga_clear / vga_putc / vga_puts / vga_set_attr / vga_move_cursor / vga_hide_cursor` | Unicorn 写 `0xB8000..0xB8F9F` 内存，断言字符面 = 期望串、属性面 = 期望色 |
| FR-V02 | 屏幕滚动：光标超出第 25 行时整体上移一行（memmove 上下共 3840 字节），末行填 `0x20`+当前属性，光标归第 25 行行首 | 打印 30 行后断言 `0xB8000` 处为第 6 行内容、`0xB8F00` 起 80 个字为空格 |
| FR-V03 | 硬件光标：通过 CRTC `0x3D4/0x3D5` 的 0x0A/0x0B（起止行）与 0x0E/0x0F（位置）驱动，**闪烁由 VGA 硬件自行完成，不占 CPU** | 用例断言端口 0x3D5 收到 index 序列 `0x0A,0x0B,0x0E,0x0F`；源码中不存在任何以软件定时器翻转光标的循环 |
| FR-V04 | PS/2 键盘驱动：**轮询方式**读 `0x64`（状态）/`0x60`（数据），Scancode Set 1 映射表，支持 Shift / CapsLock / Ctrl | 向 Unicorn 注入端口字节序列 `0x1E,0x9E`（A 按下抬起），断言屏幕上出现 `A`；注入 `0x2A,0x1E` 断言出现大写 `A` |
| FR-V05 | 终端行编辑器（§6.4）：可打印字符回显、Backspace 退格覆盖、Enter 提交、128 字节输入上限 | 用例：输入 140 字符，断言缓冲被截断在 128 且第 129 次击键不回显；退格到行首后再退格不越界（`0xB8000` 不被覆写） |
| FR-V06 | 行缓冲区不泄漏：提交后的行在处理完成后进入历史（P1 保留）或直接复用同一静态缓冲 | P0 版本断言：连续提交 200 次，堆/静态区无越界写入（在栈底与缓冲尾设 canary 常量，Unicorn 结束断言 canary 未变） |

### 4.3 P0 —— 内存管理

| ID | 需求 | 验收标准（可测） |
| --- | --- | --- |
| FR-M01 | 物理内存位图分配器：以 E820 的 `Type==1` 区间为基础，跳过 `0x00000000-0x00100000`（MBR/内核/VGA 占用区），提供 `pmm_alloc_frame / pmm_free_frame / pmm_total / pmm_used` | 调用 `pmm_alloc_frame` N 次后 `pmm_used == N`；全部释放后 `pmm_used == 0` |
| FR-M02 | 分配器自身内存占用 < 64 KB（对 32 MB 可管理内存，位图 4 KB） | 断言 `pmm_bitmap_bytes <= usable_KiB / 8 + 1024` |
| FR-M03 | **内存归属透明化**：`INTENT_MEMINFO` 输出中必须同时给出「总可用」「AI 引擎独占」两项，且 AI 引擎占比 ≥ 90% | 屏幕文案中两项均存在且 AI 占比 ≥ 90%；空闲态 `pmm_used` 仅由内核静态区与 VGA 缓冲构成（≤ 256 KB） |

### 4.4 P0 —— 端侧推理引擎（核心差异化）

| ID | 需求 | 验收标准（可测） |
| --- | --- | --- |
| FR-N01 | 输入管线：ASCII 归一化（大写转小写、非字母数字转空格、折叠空白）→ 按空格/标点分词 → 可选 bigram 拼接 → hashing trick（FNV-1a / Murmur）投影到 **64 维有符号计数特征** → 裁剪到 int8 | 对同一句话不同大小写/尾随标点，产生的 64 维向量**逐字节相同**（Python 侧与 C 侧各实现一份并交叉验证一致） |
| — | **注记（实施变更）**：本条保留的是**立项时的冻结值**，不作为当前实现依据。v0.1 实施时特征维度由 64 放大为 **`NLU_DIM` = 256**，且 n-gram 由"unigram + 可选 bigram"扩展为 **token unigram / bigram / trigram + 字符级 trigram** 四类（共享同一累加向量，字符级 trigram 是对拼写错误鲁棒的关键）。当前真值以 **`nn/config.h`** 与 **`docs/ARCH.md` §6** 为准。（"逐字节相同"这一不变性硬约束**未变**。） | — |
| FR-N02 | int8 量化 MLP：`64 → 32 (ReLU) → 12 (线性输出)`，权重 int8、偏置 int32、累加器 int32，**全整数/定点，不发射任何 x87/SSE/AVX 指令** | `objdump -d kernel.elf` 的助记符集合中不存在 `fld/fadd/fmul/cvtss/movss/psadbw/vpmaddubsw` 等；构建脚本自动做此静态检查，命中即失败并报错行号 |
| — | **注记（实施变更）**：本条保留的是**立项时的冻结值**，不作为当前实现依据。v0.1 实施时形状由 `64-32(ReLU)-12` 放大为 **`256-64(ReLU)-12`**，权重 ROM 由 ≈2608 B 变为 **17456 B**。当前真值以 **`nn/config.h`** 与 **`docs/ARCH.md` §3.7** 为准。（"全整数/定点、不发射 x87/SSE/AVX"这一硬约束**未变**，仍是构建期强制门禁。） | — |
| FR-N03 | 输出头：logits → 近似 softmax（int16 exp LUT + Q12 定点）→ Top-3 排序 → 百分比整数 | 与 Python 参考实现在同一输入上的 Top-3 排序结果与百分比误差 ≤ 2 个百分点（取 200 条测试语料求最大偏差） |
| FR-N04 | 无浮点依赖、无 libc：`memcpy/memset/strlen` 等自实现于 `core/string.c` | 链接命令含 `-nostdlib -ffreestanding -fno-builtin`（或等价的 `zig cc` 参数）；`nm` 未定义符号表中不出现 libc 符号 |
| FR-N05 | 置信度展示：每条响应首行固定为 `AI: <intent> (NN%)` + 第二三行 `.. <intent2> (NN%)` / `.. <intent3> (NN%)` | 屏幕断言存在该四行格式；三条百分比非严格必要和为 100（定点误差 ±3 以内） |
| FR-N06 | 兜底策略：Top-1 置信度 < 35% 时执行 `INTENT_FALLBACK` 动作（打印 Top-3 猜测 + 3 条建议说法 + 建议输入 `help`） | 构造 50 条 OOV 语料（"sing me a song"/"what's the weather"），≥ 45 条走兜底路径且不崩溃（canary 未失效） |
| FR-N07 | **权重 ROM**：宿主机训练脚本输出 `nn/model_weights.h`（W1[64×32]、b1[32]、W2[32×12]、b2[12] 的 int8/int32 常量数组），内核只读引用；换模型只需替换该文件并重编译 | 存在 `tools/train.py`；断言 `model_weights.h` 可被 `grep` 出四个符号且维度常量与 `nn/config.h` 一致（不一致则编译期 `static_assert` 失败） |
| — | **注记（实施变更）**：本条保留的是**立项时的冻结值**（含 `W1[64×32]` 等旧维度），不作为当前实现依据。v0.1 实施时形状由 `64-32-12` 放大为 **`256-64(ReLU)-12`**，实际导出 `W1q[256][64]`、`b1q[64]`、`W2q[64][12]`、`b2q[12]` + `exp_lut_q15[513]`，权重 ROM 由 ≈2608 B 变为 **17456 B**。当前真值以 **`nn/config.h`** 与 **`docs/ARCH.md` §3.7** 为准。（"宿主机训练、烘焙成 C 数组编译进内核、运行期不加载文件"这一机制**未变**。） | — |
| FR-N08 | 训练质量：合成语料 ≥ 每类 60 条（含拼写扰动/大小写混合/标点变体/同义改写），留出测试集 Top-1 准确率 ≥ 95%，扰动子集 ≥ 85% | `python tools/train.py --eval` 输出 JSON 报告；CI 断言 `top1 >= 0.95 and perturb_top1 >= 0.85` |
| FR-N09 | 推理开销可测量：单次 forward ≤ 200,000 条 x86 指令 | `python tools/test_nn.py` 用 Unicorn 计数（`UC_HOOK_CODE` 计数）断言上限 |
| FR-N10 | 模型信息可自查：`INTENT_MODELINFO` 必须输出五项字段——模型形状、量化位宽、权重字节数、权重 ROM 地址、AI 引擎独占内存 | 输出含 `64x32x12`、`int8`、`weights @ 0x` 等字段全部命中配准 |
| — | **注记（实施变更）**：本条保留的是**立项时的冻结值**，不作为当前实现依据。v0.1 实施时形状由 `64-32-12` 放大为 **`256-64(ReLU)-12`**，权重 ROM 由 ≈2608 B 变为 **17456 B**，故实际输出为 **`256x64x12`**。更重要的是实现方式已改：`hw/modelinfo.c` **不再写死形状字符串**，而是从 `nn/config.h` 的 `NLU_DIM` / `NN_HIDDEN` / `NN_CLASSES` 宏推导，换形状无需改代码——这正是 `test.py` 中 `modelinfo_fields` 用例在守的东西。当前真值以 **`nn/config.h`** 与 **`docs/ARCH.md` §3.7** 为准。 | — |

### 4.5 P0 —— 硬件动作执行器（§5 表 5-2）

| ID | 需求 | 验收标准（可测） |
| --- | --- | --- |
| FR-H01 | `INTENT_CLEAR`：全屏写空格+默认属性，光标归 (0,0) | `0xB8000..0xB8F9F` 全为 `[0x20, 0x07]` 交替；CRTC 位置寄存器归 0 |
| FR-H02 | `INTENT_CPUINFO`：CPUID leaf 0/1/0x80000002-4 输出厂商串、品牌串、family/model/stepping、特性位（FPU/APIC/MSR 等） | Unicorn 注入已知 CPUID（如 AuthenticAMD + K8 品牌串），断言屏幕完整出现该串且无截断 |
| FR-H03 | `INTENT_SELFTEST`：①PCI 配置空间扫描（bus 0..255 × dev 0..31 × func 0..7，读 0xCF8/0xCFC 的 Vendor/Device/Class）②内存 march 走查（至少 1 MB 抽样，Write-All-Zeros / Write-All-Ones / Read 校验）③CMOS/RTC 存在性 | Unicorn 注入 3 个伪造 PCI 设备，断言三者 Vendor:Device 均被打印；发现 0 个设备时打印 `no PCI devices found` 而非卡死 |
| FR-H04 | `INTENT_DISKINFO`：ATA identify（PIO，primary/secondary master/slave，端口 0x1F0/0x170），输出型号/序列号/容量扇区数 | 注入伪造 identify 512B 数据，断言型号串与 LBA28 容量解析正确；无盘时 30 秒超时退出并打印 `no ATA device`（超时由计数循环实现，不依赖中断） |
| FR-H05 | `INTENT_REBOOT`：写 8042 端口 `0x64 <- 0xFE` 触发复位；失败则故意 triple fault | Unicorn 断言捕获到 port 0x64 写入 0xFE |
| FR-H06 | `INTENT_SHUTDOWN`：依次尝试 APM `INT 15h AX=0x5307` → ACPI port `0x604 <- 0x2000` → 失败则打印 `It is now safe to turn off your computer.` 并 `hlt` 死循环 | 三个分支各有用例；`hlt` 分支下 Unicorn 在设定指令上限后正常退出而非跑飞 |
| FR-H07 | `INTENT_MEMINFO`：打印 E820 汇总（每个区间的 Base/Length/Type）与 PMM 的 total/used/free | E820 桩含 6 条时，屏幕出现 6 行区间，且最后一行 summary 的加法结果与逐项累加一致（±4 KB 页对齐误差） |
| FR-H08 | `INTENT_CALC`：解析并计算 32 位整数四则表达式（`+ - * /`，两操作数优先，后续扩展优先级），支持十进制与 `0x` 十六进制输入 | 用例表 ≥ 30 组（含 `45678+1234`、`0x100*0x10`、`100/7`、`-5+3`），全部与 Python 参考结果一致；除零时打印 `error: divide by zero` 且不崩溃 |
| FR-H09 | `INTENT_SCREENTEST`：至少 3 种模式——16 色 VGA 调色板色带、棋盘格、字符雾化渐变；任意键退出回到提示符 | 断言三种图案下 `0xB8000` 属性面各不相同且至少一个模式铺满 2000 个字符单元 |
| FR-H10 | `INTENT_HELP` / `INTENT_ABOUT`：按 §6.3 与 §6.2 的固定文案输出 | 整屏文案与 §6.2 / §6.3 字符级一致（作为 golden fixture 比对） |
| FR-H11 | 意图路由表与 VTable：所有意图动作通过一张 `{intent_id, desc, fn}` 静态表分派，禁止在推理输出后写 `if (strcmp(...))` 链 | 代码评审项；`nn→shell` 之间只有一处分派点（`dispatch(intent_id, argv)`） |

### 4.6 P0 —— 构建与测试工具链

| ID | 需求 | 验收标准（可测） |
| --- | --- | --- |
| FR-T01 | `build.py`：①keystone 汇编 `boot/boot.asm` → 512B ②`zig cc -target i386-freestanding -O2 -nostdlib ...` 编译全部 C ③`zig objcopy -O binary` 抽裸码 ④拼接 `boot.bin + pad_to_sector + kernel.bin + pad_to_1.44MB` → `aios.img` | 在只有 `pip install ziglang keystone-engine unicorn-engine` 的干净 venv 中，`python build.py` 退出码 0 且产物存在；每步失败给出中文错误行提示 |
| FR-T02 | `test.py`：Unicorn 驱动全链路测试，按层分组（boot / vga / kbd / pmm / nn / hwaction / dispatch） | 至少 30 个用例；任一层失败时输出 `[FAIL] layer=nn case=intent_fallback reason=...` |
| FR-T03 | 关键断言清单：保护模式进入成功、`0x10000` 处内核首指令执行、屏幕出现 `AIOS>`、注入按键后回显、注入一句话后出现 `AI: <intent> (`、Invalid op 零次 | 全部以 `assert_*` 明文列出；`test.py` 全绿定义为绿灯（覆盖率声明：≥ 12 类意图每类 ≥ 1 条端到端用例） |
| FR-T04 | 无浮点/无 libc 静态扫描集成进 `build.py`，产出 `build/report-instr.txt` | `report-instr.txt` 中 `fpu_ops=0 sse_ops=0 libc_symbols=0` |

### 4.7 P1 —— 应当（有余力即做）

| ID | 需求 | 验收标准 |
| --- | --- | --- |
| FR-P01 | 命令历史：上下方向键回溯最近 8 条输入，行内容原地重绘 | 输入 3 条后 Up 两次断言缓冲区等于第 1 条 |
| FR-P02 | Tab 补全：对已知命令关键字与意图热门说法做前缀补全，多候选时列出 | 输入 `mem` + Tab → 补全为 `show memory info` 或列出候选 |
| FR-P03 | 行内编辑：左右方向键 / Home / End / Delete / Insert 模式切换 | 每个键一个用例，光标寄存器位置随之偏移且不越界 |
| FR-P04 | Ctrl+L 清屏、Ctrl+C 放弃当前行、Ctrl+Alt+Del 热重启 | 三个组合键各一用例；Ctrl+C 后缓冲区长度归 0 |
| FR-P05 | 置信度路由：Top-1 ∈ [35%, 50%) 时执行主意图后附加一行 `did you mean ...?` 反问 | 构造边界语料 20 条，断言反问行出现率 ≥ 80% |
| FR-P06 | 兼容 medium：除 1.44 MB 软盘镜像外，额外产出 `aios-hdd.img`（CHS/LBA 可启动的 10 MB 磁盘镜像，含分区表） | 两种镜像均通过 `test_boot_*`；README 给出各自写入 U 盘的命令 |
| FR-P07 | `FR-H04` 的 ATA identify 结果缓存到静态结构，避免重复 30 秒探测 | 第二次调用耗时指令数 ≤ 首次的 1% |
| FR-P08 | 屏幕测试支持参数化（`make it blue` / `draw a grid`），由 AI 提取隐含颜色/图案槽位 | ≥ 6 种颜色 + 2 种图案可被正确抽取 |
| FR-P09 | `INTENT_CALC` 支持括号与多优先级运算符 | 20 组含括号表达式与 Python `eval` 结果一致 |
| FR-P10 | README 的 5 分钟快速上手 + 真机启动排错清单（黑屏/光标不动/键盘无响应的 6 个排查点） | 技术写作验收：新人在未咨询作者的情况下完成 S1 |

### 4.8 P2 —— v0.1 明确不做（仅登记）

| ID | 项 | 为什么砍 |
| --- | --- | --- |
| FR-X01 | 文件系统（FAT/ext/自研 FS） | 与"两层极简"冲突；引入读写/缓存/一致性，且 v0.1 无任何需要持久化的对象 |
| FR-X02 | 多任务 / 进程 / 抢占式调度 / 时钟中断驱动的 timer | 违背"内存 100% 供给 AI、无调度损耗"；轮询式终端无需并发 |
| FR-X03 | 网络栈与网卡驱动 | 体积与复杂度量级不相称，且违背离线原生的产品定位 |
| FR-X04 | 图形服务 / VESA 帧缓冲 / 窗口管理器 | 用户明确要 DOS/90 年代观感；文本模式是最短路径 |
| FR-X05 | **中文输入与中文显示** | **核心理由：VGA 80×25 文本模式只有 256 字形的代码页 ROM，没有中文字库，也没有输入法。** 支持中文必须自己绘制 16×16/12×12 点阵字库（≥ 6,763 字 × 32 字节 ≈ 216 KB，已超内核预算）+ 实现一套拼音输入法，工作量远超其余全部之和。故 v0.1 **输入侧只收 ASCII**（0x20–0x7E），并在启动提示与兜底文案中明示。方案留待 P2，届时推荐做法：模式切换到 VESA 图形帧缓冲后自绘点阵，同时引入拼音码表 ROM。 |
| FR-X06 | USB 烧录工具 / 一键写盘 GUI | 直接用 `dd`/Rufus/balenaEtcher 即可；自研 GUI 不是产品价值点 |
| FR-X07 | 更大模型（> 3 层、嵌入层、RNN/Transformer） | v0.1 的目标是证明"能跑"，不是模型性能；先跑通再放大 |
| FR-X08 | 模型量化/编译工具链自研（TFLM-on-metal 之类） | 权重在宿主机训好后以 C 数组烧入即可，零依赖是优势而非妥协 |
| FR-X09 | SIMD（SSE/AVX）加速、多核 SMP、APIC 中断路由 | 违背"不用浮点/不依赖特定 CPU"；可作为后续性能对比实验，但不在 v0.1 |
| FR-X10 | 磁盘持久化（把日志/权重写回硬盘扇区） | 依赖 FR-X01，且存在写坏用户磁盘的风险，需另行严谨设计 |
| FR-X11 | POSIX 兼容层 / ELF 加载器 / 用户态 | 与"系统唯一使命"冲突 |

---

## 5. 意图分类表

### 5.1 模型配置（冻结）

> **注记（实施变更，v0.1 落地时已放大）**：本表保留的是**立项时的冻结值**，不作为当前实现依据。
> v0.1 实施时网络形状由 `64-32(ReLU)-12` 放大为 **`256-64(ReLU)-12`**（输入 256 维、隐层 64、输出 12），
> 权重 ROM 由 ≈2608 B 变为 **17456 B**（= 16384 `W1` + 256 `b1` + 768 `W2` + 48 `b2`）。
> 当前真值一律以 **`nn/config.h`**（`NLU_DIM` / `NN_HIDDEN` / `NN_CLASSES` / `WEIGHTS_BYTES`）与
> **`docs/ARCH.md` §3.7** 为准。

| 项 | 取值 |
| --- | --- |
| 输入 | 原句 → 归一化 → 分词（+bigram）→ hashing → **64 维 int8 计数特征** |
| 网络 | `64 → 32 (ReLU) → 12 (线性)`，单层隐层，int8 权重 + int32 偏置 + int32 累加器 |
| 输出 | 12 类 logit → 定点 softmax → Top-3 + 百分比 |
| 参数量 | 64×32 + 32 + 32×12 + 12 = **2,476**；量化后权重 ROM ≈ 2.4 KB |
| 训练 | 宿主机 Python（纯 numpy 或手写 SGD，随机种子固定可复现），导出 `nn/model_weights.h` |
| 推理 | 裸机 C，前向约 2.4k 次 MAC | 

### 5.2 表 5-1：意图词表（每类 ≥ 5 条说法）

> 输入侧**仅接受 ASCII**（0x20–0x7E）；下表说法供参考与训练语料生成，中文用来说明语义。

| # | 意图 ID | 意图名 | 典型说法示例（训练语料方向） | 兜底/备注 |
| --- | --- | --- | --- | --- |
| 1 | `INTENT_CLEAR` | 清屏 | `clear the screen` / `wipe the display` / `clean up this terminal please` / `i want a fresh empty screen` / `get rid of all this text` / `cls` | 短词 `cls` 必须命中 |
| 2 | `INTENT_MEMINFO` | 查内存 | `how much memory do we have` / `show me the ram` / `what is the total memory installed` / `memory info` / `check available ram` / `is there enough memory left` | 与 M03 的「AI 占比」联动 |
| 3 | `INTENT_CPUINFO` | CPU/硬件信息 | `what cpu is this` / `show processor info` / `tell me the cpu vendor` / `which processor am i running on` / `cpu details please` / `what chip is inside` | CPUID |
| 4 | `INTENT_SELFTEST` | 硬件自检 | `run a hardware self test` / `check if everything works` / `scan the pci bus` / `diagnose my machine` / `test the hardware` / `probe all devices` | 含 PCI + 内存走查 |
| 5 | `INTENT_DISKINFO` | 磁盘探测 | `is there a disk installed` / `show disk info` / `detect the hard drive` / `what storage is attached` / `ata identify please` / `how big is the disk` | ATA identify |
| 6 | `INTENT_MODELINFO` | AI 模型信息 | `what model are you using` / `show me your neural network` / `describe the ai model` / `is a model loaded` / `how big is your model` / `model information` | 输出 ROM 地址等五项 |
| 7 | `INTENT_CALC` | 计算器 | `what is 12 times 7` / `calculate 1024 plus 512` / `compute 99 multiplied by 3` / `whats 45678 plus 1234` / `how much is 100 minus 58` / `divide 4096 by 16` | 需抽取数字槽位（在 SHELL 层做确定性抽取，不由模型承担算术） |
| 8 | `INTENT_SCREENTEST` | 屏幕色彩/图案测试 | `test the screen` / `show me some colors` / `run a display test` / `fill the screen with red` / `colour test please` / `draw a pattern` | P1 起支持颜色槽位 |
| 9 | `INTENT_HELP` | 帮助 | `help` / `what can you do` / `show me the commands` / `i dont know what to type` / `give me a list of options` / `how do i use this` | golden fixture 比对 |
| 10 | `INTENT_ABOUT` | 版本信息 | `who are you` / `what is this system` / `show version` / `about` / `tell me about this os` / `which version of aios is this` | 与 HELP 不同：静态元信息 |
| 11 | `INTENT_REBOOT` | 重启 | `reboot` / `restart the machine` / `reboot the system now` / `please restart` / `reset the computer` / `boot it again` | **危险动作，执行前不二次确认**（v0.1 无持久化，重启无损失；若 P2 引入文件系统则需加确认） |
| 12 | `INTENT_SHUTDOWN` | 关机 | `shutdown` / `turn off the computer` / `power down` / `halt the system` / `shut it down please` / `poweroff` | 同上 |
| — | `INTENT_FALLBACK` | **未知意图兜底**（第 13 位，或由置信度阈值触发，不占 softmax 输出位） | 训练语料来源：`sing me a song` / `what is the weather tomorrow` / `open a browser` / `book me a flight` / `translate this to chinese` / `play some music` | 处理方式见 FR-N06 |

### 5.3 表 5-2：意图 → 硬件动作 → 验收明细

| 意图 ID | 硬件动作（自研代码直连） | 验收明细 |
| --- | --- | --- |
| `INTENT_CLEAR` | 向 `0xB8000` 全写 `[0x20,0x07]`；CRTC 光标位置寄存器归 0 | FR-H01 |
| `INTENT_MEMINFO` | 遍历 MBR 存的 E820 表 + 查询 PMM 位图统计 | FR-H07 |
| `INTENT_CPUINFO` | `cpuid` 指令 leaf 0/1/0x80000002..4 | FR-H02 |
| `INTENT_SELFTEST` | PCI `0xCF8/0xCFC` 配置空间扫描 + 内存 march 走查 + RTC/CMOS 存在性 | FR-H03 |
| `INTENT_DISKINFO` | ATA PIO identify（0x1F0/0x170 端口族） | FR-H04 |
| `INTENT_MODELINFO` | 读取链接期常量（维度、权重起址、字节数、量化位宽）+ 报告 PMM 中为 AI 保留的区间 | FR-N10 |
| `INTENT_CALC` | 纯 CPU 整数 ALU 运算（无外设），结果经 VGA 输出 | FR-H08 |
| `INTENT_SCREENTEST` | 直接操作 VGA 属性字节面，绘制 16 色带/棋盘格/渐变 | FR-H09 |
| `INTENT_HELP` | VGA 输出（golden fixture） | FR-H10 |
| `INTENT_ABOUT` | VGA 输出静态版本常量 | FR-H10 |
| `INTENT_REBOOT` | `out 0x64, 0xFE` → 无效则 triple fault | FR-H05 |
| `INTENT_SHUTDOWN` | APM INT15h / ACPI `0x604` → 失败则 `hlt` + 提示 | FR-H06 |
| `INTENT_FALLBACK` | 无硬件动作；输出 Top-3 猜测 + 3 条建议说法 + 引导 `help` | FR-N06 |

---

## 6. 终端交互规格

### 6.1 启动画面文案（golden fixture，字符级不得篡改）

进入提示符之前输出以下 **11 行**（其中 2 行为空行）：

```
AIOS v0.1.0 - bare-metal native AI operating system
(c) 2026 Luo Ke. Every instruction below runs on bare metal.

[boot] mbr at 0x7C00, a20 enabled, e820 probed: <N> entries
[boot] kernel loaded to 0x00010000 (<M> sectors)
[boot] protected mode entered, handing over to ai kernel
[kern] vga text 80x25 ready
[kern] ps/2 keyboard online (polling)
[kern] int8 mlp 64-32-12 online, <W> bytes of weights in rom

Just tell me what you want to do.
```

- `<N>`：E820 有效条目数；`<M>`：载入扇区数；`<W>`：权重 ROM 字节数（**立项时**预期 ≈ 2476）。
- **注记（实施变更）**：上表与 `<W>` 保留的是**立项时的冻结值**，不作为当前实现依据。v0.1 实施时形状由 `64-32-12` 放大为 **`256-64(ReLU)-12`**，权重 ROM 由 ≈2608 B 变为 **17456 B**，故 golden fixture 中的实际行为是 `[kern] int8 mlp 256-64-12 online, 17456 bytes of weights in rom`。当前真值以 **`nn/config.h`** 与 **`docs/ARCH.md` §3.7** 为准（`test.py` 的 `golden_banner` 用例以实际构建产物比对）。
- 所有日志行使用对应调色板颜色（见 §6.5）。
- **在 0xB8000 写入之前必须先清屏**（黑屏 → 白字，无 BIOS 遗留画面），这是"接管感"的关键一帧。
- 末行 `Just tell me what you want to do.` 之后空一行，再输出提示符。

### 6.2 `INTENT_ABOUT` 输出（5 行）

```
AIOS v0.1.0  "bare metal, nothing underneath"
build      : <git-sha-short>@<YYYY-MM-DD>
boot chain : bios -> mbr(512B) -> protected mode -> kernel@0x10000
toolchain  : keystone-engine + ziglang(i386-freestanding) + unicorn
memory     : no os, no scheduler, all ram belongs to the ai engine
```

### 6.3 `INTENT_HELP` 输出（13 行，含 8 项清单）

```
i understand plain english, not commands. just say what you want.
things i can do right now:

  tell me about my memory        -> e820 map and allocator stats
  what cpu is this               -> cpuid vendor, brand, features
  run a hardware self test       -> pci scan, memory march, rtc check
  is there a disk installed      -> ata identify
  what model are you using       -> shape, bit width, rom address
  what is 12 times 7             -> integer calculator
  test the screen                -> color and pattern test
  reboot / shutdown              -> real hardware reset and power off

tip: i show my top 3 guesses with confidence before every answer.
```

### 6.4 提示符、光标与按键行为

| 项 | 规格 |
| --- | --- |
| **提示符** | 默认 `AIOS>`（P0）。发起人提到"出来一个大括号"，故**备选形态 `{AIOS} >`** 以编译期常量 `PROMPT_STYLE` 切换（P1，或直接在 v0.1 由 open question Q1 定夺后固定其一）。提示符占据行首 5 列，用户输入从第 6 列开始 |
| **提示符位置** | 每一次输出结束后于新行的行首重新输出提示符（不复用旧行） |
| **光标** | 8×16 硬件下划线光标；由 VGA 硬件以约 2 Hz 自动闪烁（写 CRTC 0x0A=0x0D, 0x0B=0x0E 保留默认闪烁率）。**不使用任何软件定时器**——这是"零 CPU 占用"的体现，也避免了时钟中断 |
| **可打印字符** | Scancode Set 1 表中落在 ASCII 0x20–0x7E 区间的字符：写入当前光标位置（字符 + 当前前景属性 0x0E），光标右移一列 |
| **Shift** | 双 scancode 表切换（数字行符号、字母大写） |
| **CapsLock** | 状态位翻转并更新键盘 LED（0x60 端口写 0xED）；仅影响字母 |
| **Backspace (0x0E)** | 光标左移一列，写 `[0x20, 0x07]` 覆盖，缓冲长度减 1；已到输入起始列时**不动**（不得越过提示符） |
| **Enter (0x1C)** | 提交当前缓冲 → 换行 → 执行/推理 → 输出响应 → 换行 → 重新打印提示符。空行提交：只换行+提示符，不调用推理 |
| **缓冲上限** | 128 字节。达到上限后再输入可打印字符：忽略不回显（P0）；蜂鸣（0x43 端口 speaker，`outb(0x61, inb(0x61)|3)`）列为 P1 |
| **Tab (0x0F)** | P0：忽略（不插入空格，避免给行编辑器引入歧义）；P1 起做补全（FR-P02） |
| **Ctrl+L / Ctrl+C / Ctrl+Alt+Del** | P1（FR-P04）；P0 版本全部忽略（无副作用） |
| **键盘无输入时** | 主循环 `hlt` + `in 0x64` 轮询组合：确认无数据后 `hlt` 省电，由键盘中断/下一个轮询点唤醒；Unicorn 环境下以端口桩保证可推进 |
| **屏幕滚动** | 见 FR-V02；滚动后旧历史丢弃（P2 才做 scrollback 缓冲） |
| **响应延迟** | 从 Enter 提交到屏幕出现 `AI: ` 首字符：Unicorn 计数 ≤ 200,000 条指令（含前向推理 + 意图动作执行），该断言作为性能回归门禁 |

### 6.5 VGA 调色板方案（属性字节）

| 用途 | 属性字节（hex） | 效果 |
| --- | --- | --- |
| 默认正文 / 输入回显前的底色 | `0x07` | 浅灰 on 黑 |
| `[boot]` 日志标签与行 | `0x09` | 亮蓝 |
| `[kern]` 日志标签与行 | `0x0D` | 亮品红 |
| 提示符 `AIOS>` | `0x0F` | 高亮白（视觉锚点） |
| 用户输入回显 | `0x0E` | 亮黄 |
| AI 响应正文 | `0x0A` | 亮绿（"这是 AI 在说话"） |
| `AI: <intent> (NN%)` 行与 Top-2/3 | `0x0B` | 亮青（"这是推理元数据"） |
| 硬件数据表头/标题 | `0x0E` | 亮黄 |
| 警告 / 错误 / 未命中 | `0x04` | 红 |
| 兜底建议说法 | `0x08` | 深灰（弱化） |

---

## 7. 明确的不做清单（v0.1）

以下范围一旦被触发即属越界，评审时应直接否决：

1. **不引入任何操作系统、LibOS、unikernel 框架、第三方 bootloader（GRUB 等）、third-party libc（含 newlib/musl 静态链接）** —— 唯一例外是编译期在本机跑的 `zig cc`、宿主机 Python 脚本。
2. **不实现文件系统、路径、目录、inode** —— 磁盘只作一次性 kernel 读取源和 ATA identify 对象。
3. **不实现多任务、进程、线程、抢占调度、timer tick 中断、IPC、锁** —— 全局单线程、轮询式。
4. **不实现网络协议栈与网卡驱动**。
5. **不实现图形模式、窗口管理、鼠标指针、位图字体渲染**。
6. **不支持中文输入与中文显示**（理由详见 FR-X05；所有面向用户的输出文案一律 ASCII 英文，这也与"DOS/90 年代观感"一致）。
7. **不实现/systemd 式后台服务、守护进程、shell 脚本解释器、管道、重定向**。
8. **不做 U 盘烧录 GUI、安装程序、自动分区、写盘工具** —— 交付 `img` 文件，用户自行 dd/Rufus。
9. **不做动态模型加载/权重热更新** —— 权重在构建期烘焙。
10. **不做浮点运算** —— 禁用 x87/SSE/AVX，由构建脚本静态扫描强制。
11. **不做多核 SMP、APIC 中断路由、64 位长模式** —— v0.1 只做 i386 32 位保护模式（兼容 x86-64 机器以 CSM/legacy 启动）。
12. **不做性能优化到极致（SIMD/缓存分块）** —— 只保证 int8+GEMV 的基本正确性。

---

## 8. 待确认问题（请主理人定夺）

| # | 问题 | 我的建议 |
| --- | --- | --- |
| **Q1** | 发起人提到"出来一个大括号，一个光标"。我判断他描述的是 `>` 提示符的样子，但不排除他真的想要 `{ }` 包裹。**提示符默认形态定为 `AIOS>` 还是 `{AIOS} >`？** | 建议 v0.1 采用 `{AIOS} >`（尊重原话的"大括号"意象，视觉上也更像 90 年代极客风），并在左侧留出 `(P1) PROMPT_STYLE` 常量以便一行切回 `AIOS>`。**请定一个，我写进 golden fixture。** |
| **Q2** | MBR 需在 512 字节内塞下：栈/数据区布局、实模式代码、A20 三路回退、E820 循环、INT13h 读盘循环、GDT(24B)、错误打印。keystone 汇编后预计 380–450 字节，**有溢出风险**。是否允许降级方案？ | 建议：**先按单体 MBR 实现**（维持"两层"的纯粹叙事）。若溢出，允许把"读盘 + 进保护模式"整体逻辑放到扇区 1（stage 1.5，kernel 顺延至 LBA 2）——但这会打破"两层"叙事，**需要你先确认这个降级是否被接受**，因为它实质上变成了三层。另一备选：砍掉 A20 的 8042 回退与详细错误打印，换取 60 字节。 |
| **Q3** | 关机/重启是否需要**二次确认**？ | v0.1 无持久化，**建议不确认**（凸显"说到做到"的演示张力）。但请在 §5.2 备注中保留：一旦引入文件系统（P2），必须加确认。 |
| **Q4** | 交付镜像介质：1.44 MB 软盘镜像 vs 10 MB 硬盘镜像（含分区表）？ | 建议 **P0 只做软盘镜像**（最简单、`test.py` 只需一个）、**P1 补硬盘镜像**。因为现代真机几乎都没有软驱，但 U 盘以" floppy 模拟模式"写 1.44 MB 镜像在多数 legacy BIOS 上仍能起来——需要真机验证。**若有不同意见请指出。** |
| **Q5** | 是否接受 v0.1 的**全部输出文案为 ASCII 英文**（包括帮助文案里"告诉我一句话的例子"这类提示）？ | 建议接受。中文显示的字库成本见 FR-X05，列为 P2。若发起人坚持开机画面要有中文，唯一低成本路径是手写 ≤ 30 个字的 8×16 点阵（8 行 × 16 字节 = 128 字节/字），但只能用于固定的开机标题，无法泛化。**这是否足够？** |
| **Q6** | CPU 最低目标：允许使用哪些指令？ | 建议：**i386 通用指令集 + CPUID + `cmov` 除外**；不使用 SSE/AVX/x87（`cmov` 属 i686，为避免 486 兼容性问题可禁用）。截断由 `zig cc -target i386-freestanding` 天然保证，但我方需显式禁用 MMX/SSE 编译选项。**是否需要支持 486（无 CPUID）？若需要，`INTENT_CPUINFO` 需增加一条 486 检测分支。** |
| **Q7** | 是否需要把 `test.py` 作为**提交门禁**（每次改动不放行则不算完成）？ | 建议是。这是唯一能在没有真机的 Win 环境下保证"启动链真的能跑"的手段。 |
| **Q8** | 训练语料由谁提供、规模多大？ | 建议：我（PM）已在 §5.2 给出每类 6 条种子说法；由架构师/开发用模板扰动（同义词替换、大小写混合、标点、词序、拼写错误）扩到 ≥ 60 条/类，共 ≥ 720 条 + 60 条 OOV。**这个规模是否够？若要 Demo 效果更稳，可提到 120 条/类。** |
| **Q9** | 是否需要 `INTENT_CALC` 支持负数/十六进制/括号？ | 建议 v0.1：两操作数 + `- + * /` + 十进制/十六进制输入（FR-H08）；括号与多优先级列 P1（FR-P09）。**是否接受？** |
| **Q10** | 演示视频/截图素材算不算 v0.1 交付物？ | 建议：只交付源码 + `img` + README + 测试；截图与视频另算。若需要真机演示素材，需有人在真实机器上跑一次——**这是否是本次要交付的？** |

---

## 附录 A：数据与非功能约束

| ID | 约束 | 度量方式 |
| --- | --- | --- |
| NFR-01 | 内核裸镜像 ≤ 128 KB，引导扇区恰好 512 B | `build.py` 输出尺寸，超出即告警 |
| NFR-02 | 单次 AI 前向 ≤ 200,000 条 x86 指令（Unicorn 计数） | `test.py` 断言 |
| NFR-03 | 零浮点指令、零 libc 符号 | `build/report-instr.txt`：`fpu_ops=0 sse_ops=0 libc_symbols=0` |
| NFR-04 | 空闲态（无输入）CPU 处于 `hlt`，无忙循环空转 | 静态 review + Unicorn 端口无数据时的指令数增长 ≤ 100 条/循环 |
| NFR-05 | 全构建环境依赖仅 3 个 PyPI 包，无需管理员权限/WSL/Linux 子系统 | 在 `python -m venv` 干净环境中复现已验证 |
| NFR-06 | 推理沙箱：任何输入（含 128 字节随机垃圾、超长词、纯符号）都不得越界写到 VGA 显存缓冲区以外的内核内存 | 模糊测试 1000 轮，canary 未被修改，且无不合法内存访问信号 |

---

## 附录 B：验收 checklist（v0.1 完工定义）

- [ ] `python build.py` 一次成功，产出 `aios.img` 与 `build/report-instr.txt`
- [ ] `python tools/train.py --eval`：Top-1 ≥ 95%，扰动子集 ≥ 85%
- [ ] `python test.py`：≥ 30 用例全绿，13 类意图（含兜底）每类 ≥ 1 条端到端用例
- [ ] 屏幕 golden fixture 三份（启动画面 / HELP / ABOUT）字符级匹配
- [ ] 引导层与五个内核模块（boot / vga / kbd / pmm / nn）各自都有 ≥ 1 个"故意改错即失败"的反向用例，失败时能被 `test.py` 明确归因到该层
- [ ] README 能支撑 S1（5 分钟跑通）+ S2（写明当前仅在 BIOS/CSM 场景验证）
- [ ] 所有对外文案与 README 中均不得出现「支持中文输入 / 中文显示」的表述（若出现，属需求 breach）
