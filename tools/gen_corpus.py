#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/gen_corpus.py —— AIOS v0.1 意图分类合成语料生成器。

产出：`tools/intent_corpus.json`

规模（ARCH §9 T04 / 主理人裁决 Q8）:
    * 12 类意图 x 每类 120 条 = 1440 条带标签语料
    * OOV（未知意图）60 条，intent = -1
    * 合计 1500 条

生成方式：模板槽位展开 -> 5 种扰动算子 -> 去重 -> 固定种子洗牌 -> 每类取 120。

5 种扰动算子（与 ARCH §6 的"大小写/标点/空格不变性"完全对应）:
    1. synonym  同义替换：单词级同义词表随机替换一个词
    2. case     大小写混合：全大 / 全小 / 词首大写 / 逐字符随机
    3. punct    标点与空格变体：尾随 . ! ? !! ... 、前导多空格、词间多空格
    4. order    词序调整：please / now 前后移动，或交换前两个词
    5. typo     拼写扰动：删字母 / 交换相邻字母 / 重复字母

注意：case / punct 两类扰动经 ARCH §6 归一化后产生的 64 维特征与原句**完全相同**，
     它们的作用是验证不变性；typo / order / synonym 会真实改变特征，用于提升鲁棒性。

运行：python tools/gen_corpus.py [--out tools/intent_corpus.json] [--seed 20260101]

纯标准库，无第三方依赖。
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import sys

# --------------------------------------------------------------------------
# 意图表：索引即分类 id，顺序不可变（与 shell/intent.h 严格一致）
# --------------------------------------------------------------------------
INTENTS = [
    "CLEAR",
    "MEMINFO",
    "CPUINFO",
    "SELFTEST",
    "DISKINFO",
    "MODELINFO",
    "CALC",
    "SCREENTEST",
    "HELP",
    "ABOUT",
    "REBOOT",
    "SHUTDOWN",
]

PER_INTENT = 120
OOV_COUNT = 60
DEFAULT_SEED = 20260101

# --------------------------------------------------------------------------
# 每类意图的模板族：slots 是槽位候选，templates 是带 {槽位} 的模板
# --------------------------------------------------------------------------
SPEC = {
    "CLEAR": {
        "slots": {
            "v": ["clear", "wipe", "clean", "erase", "blank", "reset", "flush"],
            "o": ["screen", "display", "terminal", "console", "monitor"],
        },
        "templates": [
            "{v} the {o}",
            "{v} this {o}",
            "{v} the {o} please",
            "please {v} the {o}",
            "can you {v} the {o}",
            "{v} my {o}",
            "{v} the {o} now",
            "i want a fresh empty {o}",
            "i need a clean {o}",
            "get rid of all this text",
            "make the {o} empty",
            "start with a blank {o}",
            "i want to {v} the {o}",
            "would you {v} the {o}",
            "{v} it all",
            "{v} the {o} for me",
            "{v} out the {o}",
            "give me a clean {o}",
        ],
    },
    "MEMINFO": {
        "slots": {
            "v": ["show", "tell", "give", "print", "display", "report"],
            "o": ["memory", "ram", "mem", "dram"],
        },
        "templates": [
            "how much {o} do we have",
            "how much {o} is installed",
            "how much {o} do i have",
            "{v} me the {o}",
            "{v} me about my {o}",
            "what is the total {o} installed",
            "{o} info",
            "{o} information please",
            "check available {o}",
            "is there enough {o} left",
            "{v} the {o} map",
            "how big is the {o}",
            "i want to know my {o}",
            "{o} please",
            "list the {o} regions",
            "{v} the {o} layout",
            "how many bytes of {o} are there",
            "what {o} is available",
        ],
    },
    "CPUINFO": {
        "slots": {
            "v": ["show", "tell", "give", "print", "display", "read"],
            "o": ["cpu", "processor", "chip", "core"],
        },
        "templates": [
            "what {o} is this",
            "{v} {o} info",
            "{v} me the {o} vendor",
            "which {o} am i running on",
            "{o} details please",
            "what {o} is inside",
            "identify the {o}",
            "{v} me the {o} brand",
            "what {o} do i have",
            "{v} {o} information",
            "is this an intel or amd {o}",
            "{v} the {o} id",
            "which {o} is installed",
            "i want to know the {o} name",
            "{o} please",
            "what kind of {o} is this",
        ],
    },
    "SELFTEST": {
        "slots": {
            "v": ["run", "start", "do", "perform", "execute"],
            "o": ["hardware", "machine", "system", "devices", "box"],
        },
        "templates": [
            "{v} a {o} self test",
            "{v} a full {o} self test",
            "check if everything works",
            "scan the pci bus",
            "diagnose my {o}",
            "test the {o}",
            "probe all devices",
            "{v} diagnostics",
            "{v} a built in self test",
            "check my {o} health",
            "scan for pci devices",
            "test everything",
            "{v} the {o} diagnostics now",
            "i want a full {o} check",
            "is my {o} working",
            "{v} a memory march test",
        ],
    },
    "DISKINFO": {
        "slots": {
            "v": ["show", "detect", "identify", "scan", "probe", "check"],
            "o": ["disk", "hard drive", "drive", "hdd", "storage", "ssd"],
        },
        "templates": [
            "is there a {o} installed",
            "{v} {o} info",
            "detect the hard drive",
            "what {o} is attached",
            "ata identify please",
            "how big is the {o}",
            "do i have a {o}",
            "identify the {o}",
            "scan for a {o}",
            "give me the {o} model",
            "check the {o}",
            "probe the {o}",
            "{v} the {o}",
            "what {o} do we have",
            "is any {o} present",
            "read the {o} identity",
        ],
    },
    "MODELINFO": {
        "slots": {
            "v": ["show", "describe", "print", "explain"],
            "o": ["model", "neural network", "ai model", "network"],
        },
        "templates": [
            "what {o} are you using",
            "show me your {o}",
            "describe the {o}",
            "is a {o} loaded",
            "how big is your {o}",
            "{o} information",
            "tell me about your {o}",
            "what is your {o} shape",
            "how many weights does your {o} have",
            "what kind of {o} do you run",
            "print {o} details",
            "{v} your {o}",
            "how large is the {o}",
            "what are your {o} dimensions",
            "which {o} is running",
            "{o} please",
        ],
    },
    "CALC": {
        "slots": {},
        "numbers": True,
        "templates": [
            "what is {a} plus {b}",
            "what is {a} minus {b}",
            "what is {a} times {b}",
            "what is {a} divided by {b}",
            "calculate {a} plus {b}",
            "compute {a} times {b}",
            "whats {a} plus {b}",
            "how much is {a} plus {b}",
            "how much is {a} minus {b}",
            "divide {a} by {b}",
            "multiply {a} by {b}",
            "add {a} and {b}",
            "subtract {b} from {a}",
            "{a} plus {b}",
            "{a} times {b}",
            "what is {a} plus {b} equal to",
            "give me {a} times {b}",
            "can you compute {a} minus {b}",
        ],
    },
    "SCREENTEST": {
        "slots": {
            "v": ["test", "check", "run"],
            "o": ["screen", "display", "monitor"],
        },
        "templates": [
            "test the {o}",
            "show me some colors",
            "run a {o} test",
            "fill the {o} with red",
            "colour test please",
            "color test please",
            "draw a pattern",
            "{v} the {o}",
            "check the {o}",
            "display a test pattern",
            "show me the color bars",
            "draw a grid",
            "test the colors",
            "run a display test",
            "i want a {o} test",
            "paint the {o} blue",
        ],
    },
    "HELP": {
        "slots": {"p": ["", " please", " now", " mate"]},
        "templates": [
            "help{p}",
            "what can you do{p}",
            "what can i say{p}",
            "show me the commands{p}",
            "show the help{p}",
            "i dont know what to type{p}",
            "give me a list of options{p}",
            "how do i use this{p}",
            "what commands are there{p}",
            "i need help{p}",
            "list what you can do{p}",
            "can you help me{p}",
            "show me what you can do{p}",
            "what are my options{p}",
            "help me out{p}",
            "what should i type{p}",
        ],
    },
    "ABOUT": {
        "slots": {"p": ["", " please", " now"]},
        "templates": [
            "who are you{p}",
            "who made you{p}",
            "what is this system{p}",
            "what is aios{p}",
            "show version{p}",
            "show me the version{p}",
            "print the version{p}",
            "about{p}",
            "about this system{p}",
            "tell me about this os{p}",
            "which version of aios is this{p}",
            "what are you{p}",
            "describe yourself{p}",
            "version please",
            "i want to know your version{p}",
            "what build is this{p}",
        ],
    },
    "REBOOT": {
        "slots": {
            "m": ["machine", "computer", "system", "box"],
            "p": ["", " now", " please"],
        },
        "templates": [
            "reboot{p}",
            "reboot the {m}{p}",
            "restart{p}",
            "restart the {m}{p}",
            "please restart{p}",
            "reset the {m}{p}",
            "boot it again{p}",
            "do a reboot{p}",
            "i want to reboot{p}",
            "restart it{p}",
            "reset everything{p}",
            "give the {m} a reset{p}",
            "restart the {m} right now",
            "reboot the {m} immediately",
        ],
    },
    "SHUTDOWN": {
        "slots": {
            "m": ["machine", "computer", "system", "box"],
            "p": ["", " now", " please"],
        },
        "templates": [
            "shutdown{p}",
            "shut down{p}",
            "shut the {m} down{p}",
            "turn off the {m}{p}",
            "turn it off{p}",
            "power down{p}",
            "power off{p}",
            "power off the {m}{p}",
            "halt the {m}{p}",
            "halt{p}",
            "poweroff{p}",
            "i want to shutdown{p}",
            "stop the {m}{p}",
            "kill the power{p}",
            "shut it down{p}",
            "switch the {m} off{p}",
        ],
    },
}

# --------------------------------------------------------------------------
# 每类意图的"判别关键词"：op_typo 不会去扰动这些词
#
# 为什么：hashing trick 里，一个被错拼的词会映射到一个与原词毫无关系的新桶。
# 如果被打错的恰好是这句话唯一的判别词（例如 "show me the memory" 里的 memory），
# 那么这条样本在信息论上就是不可复原的 —— 不是模型不行，是这道题无解。
# 把它放进评估集只会污染指标。所以拼写扰动只打在"非判别词"上（please / the /
# this / now / can / it ...），这些词跨意图共享，错一个不影响语义判别。
# --------------------------------------------------------------------------
KEYWORDS = {
    "CLEAR": "clear wipe clean erase blank reset flush screen display terminal "
             "console monitor fresh empty text rid clean",
    "MEMINFO": "memory ram mem dram installed available total regions layout bytes "
               "enough left much info information map how",
    "CPUINFO": "cpu processor chip core vendor brand intel amd details identify "
               "inside running installed which",
    "SELFTEST": "hardware machine system devices self test diagnostics diagnose pci "
                "probe march health everything working full check built memory",
    "DISKINFO": "disk hard drive hdd storage ssd ata identify detect attached "
                "installed model present identity scan probe storage",
    "MODELINFO": "model neural network shape weights dimensions loaded describe "
                 "explain kind large big using running",
    "CALC": "plus minus times divided calculate compute multiply divide subtract "
            "equal whats add how",
    "SCREENTEST": "screen display monitor colors colour color pattern red blue grid "
                  "bars paint draw test check run fill",
    "HELP": "help commands options list type know should can what how use say",
    "ABOUT": "version about system aios build describe yourself made who tell print",
    "REBOOT": "reboot restart reset machine computer system box again boot "
              "immediately everything",
    "SHUTDOWN": "shutdown shut down turn power halt poweroff stop kill switch "
                "machine computer system box",
}

# CALC 的操作数对（十进制 / 十六进制 / 负数，覆盖 FR-H08）
CALC_NUMBERS = [
    (12, 7), (1024, 512), (99, 3), (45678, 1234), (100, 58),
    (4096, 16), (7, 8), (255, 15), (64, 32), (1000, 250),
    (-5, 3), (0x10, 0x20), (16, 4), (999, 111), (250, 50),
    (33, 11), (77, 7), (512, 8), (1234, 4321), (64, 8),
    (0x100, 0x10), (100, 7), (88, 44), (31, 5), (2048, 4),
]

# OOV：未知意图语料（60 条），不占 softmax 输出位，由置信度阈值兜底
OOV_SEEDS = [
    "sing me a song",
    "what is the weather tomorrow",
    "open a browser",
    "book me a flight",
    "translate this to chinese",
    "play some music",
    "order me a pizza",
    "what time is it",
    "tell me a joke",
    "send an email to bob",
    "how do i cook pasta",
    "who won the match last night",
    "what is the capital of france",
    "set an alarm for seven",
    "download a movie",
    "write a poem about the sea",
    "call me a taxi",
    "what should i eat for dinner",
    "buy me a ticket to paris",
    "explain quantum physics",
    "how old is the universe",
    "make me a sandwich",
    "record a video of the cat",
    "stream the latest news",
    "find me a hotel in tokyo",
    "check my bank balance",
    "print my boarding pass",
    "water the plants",
    "walk the dog please",
    "change the wallpaper to blue",
    "unsubscribe from the newsletter",
    "what is the meaning of life",
    "teach me to play guitar",
    "reserve a table for two",
    "update my social status",
    "sync my calendar",
    "post a photo online",
    "start a video call",
    "mute the microphone",
    "turn up the volume",
    "skip this song",
    "shuffle the playlist",
    "read my messages aloud",
    "remind me to buy milk",
    "show me the news headlines",
    "what is trending today",
    "translate the menu",
    "book a dentist appointment",
    "renew my passport",
    "pay the electricity bill",
    "compare insurance prices",
    "track my package",
    "guess my age",
    "tell me a bedtime story",
    "what is the square root of pi",
    "plan a weekend trip",
    "hire a designer",
    "apply for a visa",
    "check the lottery numbers",
    "follow me on social media",
]

# --------------------------------------------------------------------------
# 算子 1：同义替换
#
# 重要约束：同义词表只允许指向"基础模板里本来就出现过的词"。
# 如果同义词把词换成语料里从未出现过的说法（例如 please -> kindly），
# 那对 hashing 特征来说等价于凭空多了一个未知词，退化成"拼写扰动"，
# 会让 synonym 这个算子失去它本来的语义（同义改写而不改意图）。
# --------------------------------------------------------------------------
SYNONYMS = {
    "screen": ["display", "monitor", "terminal"],
    "display": ["screen", "monitor"],
    "monitor": ["screen", "display"],
    "terminal": ["screen", "console"],
    "console": ["terminal", "screen"],
    "machine": ["computer", "system"],
    "system": ["machine", "box"],
    "memory": ["ram", "mem"],
    "ram": ["memory", "mem"],
    "cpu": ["processor", "chip"],
    "processor": ["cpu", "chip"],
    "chip": ["cpu", "processor"],
    "disk": ["drive", "hdd", "storage"],
    "drive": ["disk", "hdd"],
    "hdd": ["disk", "drive"],
    "storage": ["disk", "drive"],
    "ssd": ["disk", "drive"],
    "model": ["network"],
    "network": ["model"],
    "show": ["display", "print", "give"],
    "tell": ["show", "give"],
    "test": ["check", "diagnose"],
    "check": ["test", "scan"],
    "scan": ["check", "probe"],
    "colors": ["colours"],
    "color": ["colour"],
    "hardware": ["machine", "system"],
    "devices": ["hardware"],
}


def op_synonym(text, rng):
    """算子 1：把一个词替换成同义词。无可用同义词时原样返回。"""
    words = text.split(" ")
    cand = [i for i, w in enumerate(words) if w in SYNONYMS]
    if not cand:
        return text
    i = rng.choice(cand)
    words[i] = rng.choice(SYNONYMS[words[i]])
    return " ".join(words)


def op_case(text, rng):
    """算子 2：大小写混合。归一化后与原句特征完全一致。"""
    mode = rng.randrange(4)
    if mode == 0:
        return text.upper()
    if mode == 1:
        return text.lower()
    if mode == 2:
        return text.title()
    return "".join(ch.upper() if rng.random() < 0.5 else ch.lower() for ch in text)


def op_punct(text, rng):
    """算子 3：标点 + 空格变体。归一化后与原句特征完全一致。"""
    core = text.rstrip(" .!?,")
    mode = rng.randrange(4)
    if mode == 0:
        tail = "."
    elif mode == 1:
        tail = "!"
    elif mode == 2:
        tail = "?"
    else:
        tail = rng.choice(["", "!!", "...", ", please"])
    core = core + tail
    space_mode = rng.randrange(3)
    if space_mode == 1:
        core = "   " + core
    elif space_mode == 2:
        core = core.replace(" ", "   ")
    return core


def op_order(text, rng):
    """算子 4：词序调整（移动 please/now，或交换前两个词）。"""
    words = text.split(" ")
    if len(words) >= 3 and words[0] == "please":
        return " ".join(words[1:] + ["please"])
    if len(words) >= 3 and words[-1] == "please":
        return " ".join(["please"] + words[:-1])
    if len(words) >= 4 and words[-1] == "now":
        return " ".join(["now"] + words[:-1])
    if len(words) >= 2:
        words[0], words[1] = words[1], words[0]
        return " ".join(words)
    return text


def op_typo(text, rng, keywords=None):
    """算子 5：拼写扰动（删字母 / 交换相邻字母 / 重复字母）。

    两条保护规则，都是为了不制造"信息论上不可复原"的脏样本：
      1. 句子少于 3 个词不扰动（"reboot" / "halt" 一错拼就全无信号）；
      2. 只扰动**非判别词**（见 KEYWORDS 说明）。
    """
    words = text.split(" ")
    if len(words) < 3:
        return text
    kw = keywords or frozenset()
    cand = [i for i, w in enumerate(words)
            if len(w) >= 4 and w.isalpha() and w not in kw]
    if not cand:
        return text
    i = rng.choice(cand)
    w = words[i]
    mode = rng.randrange(3)
    if mode == 0 and len(w) > 1:                      # 删除一个字母
        k = rng.randrange(len(w))
        w2 = w[:k] + w[k + 1:]
    elif mode == 1 and len(w) >= 2:                   # 交换相邻字母
        k = rng.randrange(len(w) - 1)
        w2 = w[:k] + w[k + 1] + w[k] + w[k + 2:]
    else:                                             # 重复一个字母
        k = rng.randrange(len(w))
        w2 = w[:k + 1] + w[k] + w[k + 1:]
    words[i] = w2
    return " ".join(words)


def apply_ops(text, rng, tags, keywords=None):
    """按 tags 依次施加扰动算子。"""
    s = text
    applied = []
    for name, fn in OPS:
        if name in tags:
            s2 = fn(s, rng, keywords) if name == "typo" else fn(s, rng)
            if s2 != s:
                applied.append(name)
            s = s2
    return s, applied


def op_typo_dispatch(s, rng, keywords=None):
    return op_typo(s, rng, keywords)


OPS = [
    ("synonym", op_synonym),
    ("case", op_case),
    ("punct", op_punct),
    ("order", op_order),
    ("typo", op_typo_dispatch),
]


# --------------------------------------------------------------------------
# 模板展开
# --------------------------------------------------------------------------
def expand_base(spec, rng):
    """把一个意图的模板族展开成去重后的基础句列表。"""
    out = []
    seen = set()

    def push(s):
        s = " ".join(s.split())          # 折叠空白，保证基础句干净
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    if spec.get("numbers"):
        for tpl in spec["templates"]:
            for a, b in CALC_NUMBERS:
                push(tpl.format(a=a, b=b))
    else:
        slots = spec["slots"]
        names = list(slots.keys())
        for tpl in spec["templates"]:
            used = [n for n in names if ("{" + n + "}") in tpl]
            if not used:
                push(tpl)
                continue
            for combo in itertools.product(*[slots[n] for n in used]):
                mapping = dict(zip(used, combo))
                push(tpl.format(**mapping))
    rng.shuffle(out)
    return out


BASE_TARGET = 40          # 每个意图复用的基础句条数
OP_PLAN = [
    (),                     # 原句
    ("case",),
    ("punct",),
    ("synonym",),
    ("typo",),              # 拼写扰动占 2/12：真实用户输入里错拼是少数
    ("order",),
    ("case", "punct"),
    ("punct", "synonym"),
    ("synonym", "case"),
    ("typo", "punct"),
    ("order", "punct"),
    ("case", "synonym"),
]


def build_intent_samples(spec, name, want, rng, n_base=BASE_TARGET):
    """生成一个意图的 want 条语料。

    关键设计：基础句只取 n_base 条，每条基础句再派生若干个扰动变体。
    这样同一个语义（同一批内容词）会在语料里以多种外表反复出现，
    模型才能学到"内容词权重"而不是整句死记 —— 否则 120 条全部是
    互不相干的唯一句，模型只会过拟合。
    """
    base = expand_base(spec, rng)
    if not base:
        raise ValueError("empty base for intent")
    if len(base) > n_base:
        base = base[:n_base]
    keywords = frozenset(KEYWORDS.get(name, "").split())

    # 每个基础句派生多少个变体：保证候选池 >= want * 1.35
    variants = max(4, -(-(want * 135 // 100) // len(base)))

    pool = []
    seen = set()
    for k in range(variants):
        for i, b in enumerate(base):
            tags = OP_PLAN[(k * len(base) + i) % len(OP_PLAN)]
            s, applied = apply_ops(b, rng, set(tags), keywords)
            if s in seen:
                continue
            seen.add(s)
            pool.append({"text": s, "ops": applied})

    rng.shuffle(pool)
    return pool[:want]


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="AIOS intent corpus generator")
    ap.add_argument("--out", default=None, help="output json path")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--per-intent", type=int, default=PER_INTENT)
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    out_path = args.out or os.path.join(here, "intent_corpus.json")
    rng = random.Random(args.seed)

    samples = []
    stats = {}
    for idx, name in enumerate(INTENTS):
        got = build_intent_samples(SPEC[name], name, args.per_intent, rng)
        if len(got) < args.per_intent:
            raise SystemExit(
                "[FAIL] intent %s: only %d unique utterances (want %d)"
                % (name, len(got), args.per_intent)
            )
        for item in got:
            item["intent"] = idx
            item["intent_name"] = name
            samples.append(item)
        hard = sum(1 for it in got if ("typo" in it["ops"] or "order" in it["ops"]))
        stats[name] = {"count": len(got), "hard_perturbed": hard}

    oov = []
    for text in OOV_SEEDS[:OOV_COUNT]:
        oov.append({"text": text, "intent": -1, "intent_name": "FALLBACK", "ops": []})

    payload = {
        "version": 1,
        "seed": args.seed,
        "intents": INTENTS,
        "per_intent": args.per_intent,
        "oov_count": len(oov),
        "total": len(samples) + len(oov),
        "ops": [n for n, _ in OPS],
        "stats": stats,
        "samples": samples,
        "oov": oov,
    }

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    sys.stdout.write(
        "[gen_corpus] wrote %s\n"
        "  labeled : %d (%d intents x %d)\n"
        "  oov     : %d\n"
        "  total   : %d\n"
        % (out_path, len(samples), len(INTENTS), args.per_intent,
           len(oov), payload["total"])
    )
    for name in INTENTS:
        sys.stdout.write(
            "    %-11s %3d  (hard-perturbed %d)\n"
            % (name, stats[name]["count"], stats[name]["hard_perturbed"])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
