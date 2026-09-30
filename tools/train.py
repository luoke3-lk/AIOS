#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/train.py —— AIOS v0.1 端侧 int8 MLP 的训练 / 量化标定 / 导出 / 对齐验证。

纯 Python 标准库实现：严禁 numpy / torch / 任何第三方包（ARCH Q8 裁决）。

流水线（ARCH §5.4 十步）:
     1. 纯 Python float SGD 训练 MLP(256-64-ReLU-12)，固定种子，交叉熵 + L2
     2. k1 = floor(log2(127 / max|W1|))                    -> W1q, b1q
     3. 全训练集算 acc1 -> max_a1 = max(max(0, acc1))
        r1 = max(0, ceil(log2(max_a1 / 127)))
     4. k2 = floor(log2(127 / max|W2|))                    -> W2q
     5. OUT_SHIFT = k1 + k2 - r1（<8 减 r1，>14 增 r1）
     6. b2q = round_half_up(b2 * 2^OUT_SHIFT)
     7. 整数参考实现 ref_forward(feat) 跑验证集 -> Top-1 / Top-3
     8. 与 float 版对账：Top-1 一致率 >= 99%
     9. 断言 top1 >= 0.95 且 perturb_top1 >= 0.85（FR-N08）
    10. 导出 nn/config.h + nn/model_weights.h + tools/golden_features.json
        + tools/golden_vectors.json + build/train_report.json

跨语言逐位一致的三条硬保证:
    (a) 所有缩放用 2 的幂（移位），绝不用除法做缩放
    (b) 所有被移位的量在移位前恒非负（acc1 过 ReLU 后非负；softmax 的 d = max-logit 非负）
        -> C 的算术右移 == 数学 floor == Python 的 >>，语义无歧义
    (c) 唯一取整函数 round_half_up(x) = int(x+0.5) if x>=0 else -int(-x+0.5)
        （禁止 Python 默认的 banker's rounding）

用法:
    python tools/train.py                # 生成语料->训练->标定->导出->host 对齐测试
    python tools/train.py --eval         # 只输出 JSON 评估报告并做门禁断言
    python tools/train.py --no-align     # 跳过 host 端 C/Python 对齐测试
    python tools/train.py --epochs 60    # 调整训练轮数
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import time

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
IN_DIM = 256         # NLU_DIM（扩容：字级 trigram 需要更大桶空间降低碰撞）
HID = 64             # NN_HIDDEN（扩容：更多容量分离 12 意图）
OUT = 12             # NN_CLASSES
LUT_ENTRIES = 513    # exp LUT 项数（契约要求 513）
LUT_SHIFT = 4        # exp LUT 输入步长 2^-4
# 布局：W1 int8 (IN_DIM*HID) + b1 int32 (HID*4) + W2 int8 (HID*OUT) + b2 int32 (OUT*4)
WEIGHTS_BYTES = IN_DIM * HID + HID * 4 + HID * OUT + OUT * 4   # 256*64+256+768+48 = 17456

NLU_MAX_CHARS = 128
NLU_MAX_TOKENS = 32
NLU_MAX_TOKEN_LEN = 31
NLU_BIGRAM_MAX = 31
USE_BIGRAM = 1            # 写进 nn/config.h 的 NLU_USE_BIGRAM（--no-bigram 时置 0）

DEFAULT_SEED = 20260101
TOP1_MIN = 0.95
PERTURB_TOP1_MIN = 0.85

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 与 shell/intent.h 严格一致
INTENTS = [
    "CLEAR", "MEMINFO", "CPUINFO", "SELFTEST", "DISKINFO", "MODELINFO",
    "CALC", "SCREENTEST", "HELP", "ABOUT", "REBOOT", "SHUTDOWN",
]

# 背景噪声词（不属于任何意图），用于把 OOV 推向均匀分布
BG_WORDS = [
    "weather", "song", "pizza", "flight", "hotel", "movie", "poem", "taxi",
    "cat", "dog", "dinner", "lunch", "music", "joke", "news", "mail",
    "ticket", "passport", "visa", "guitar", "salad", "coffee", "train",
    "bus", "beach", "mountain", "river", "cloud", "birthday", "holiday",
    "party", "garden", "kitchen", "window", "bottle", "candle", "planet",
    "rocket", "robot", "dragon", "castle", "forest", "desert", "island",
    "market", "banana", "painting", "wedding", "football", "ocean",
]
BG_PATTERNS = [
    "{s}", "{s}", "what is the {s}", "{s} please", "i want {s}",
    "tell me about {s}", "{s} now", "can you {s}",
]


# --------------------------------------------------------------------------
# 取整规范（唯一，禁止 banker's rounding）
# --------------------------------------------------------------------------
def round_half_up(x):
    """round_half_up(x) = int(x+0.5) if x>=0 else -int(-x+0.5)。"""
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def clamp_i(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


# --------------------------------------------------------------------------
# ARCH §6 特征抽取：Python 参考实现（与 nlu/nlu.c 逐字节一致）
# --------------------------------------------------------------------------
def nlu_normalize(text):
    """第 1 步（截断 128）+ 第 2 步（归一化）。

    关键修正（FR-N01 不变性）：先在 RAW 文本上剥掉首尾空白，再截 128。
    否则像 "   a...a  " 这样的变体，开头 3 个空格会吞掉截断额度，使
    归一化后的长度与基准不同，导致 char trigram 特征向量不一致。
    与 nlu/nlu.c 的「跳过首尾空白再截 128」严格一致（同为 space/tab/cr/lf）。
    """
    out = []
    n = 0
    if "\0" in text:
        text = text.split("\0", 1)[0]
    text = text.strip(" \t\r\n")          # 剥首尾空白：避免占用 128 截断额度
    for ch in text[:NLU_MAX_CHARS]:
        o = ord(ch)
        if 0x41 <= o <= 0x5A:            # 'A'..'Z' -> 小写（先于任何判定）
            o += 32
        if (0x61 <= o <= 0x7A) or (0x30 <= o <= 0x39):
            out.append(chr(o))
            n += 1
        elif n > 0 and out[-1] != " ":   # 折叠连续分隔符，不做 trim
            out.append(" ")
            n += 1
    return "".join(out)


def nlu_tokenize(norm):
    """第 3 步：分词，上限 32 token，单 token 截断到 31 字符（不丢弃）。"""
    toks = []
    for raw in norm.split(" "):
        if raw == "":
            continue
        if len(raw) > NLU_MAX_TOKEN_LEN:
            raw = raw[:NLU_MAX_TOKEN_LEN]
        toks.append(raw)
        if len(toks) >= NLU_MAX_TOKENS:
            break
    return toks


def fnv1a(data):
    """第 5 步：FNV-1a 32 位。"""
    h = 0x811C9DC5
    for b in data:
        h = (h ^ b) & 0xFFFFFFFF
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def nlu_extract_py(text):
    """ARCH §6 七步 -> 长度 IN_DIM 的 int 列表，值域 [-127, 127]。

    四类特征共享同一个有符号计数累加向量（与 nlu/nlu.c 逐字节一致）：
      * token unigram           —— 精确关键词信号（"reboot"/"clear"...）
      * token bigram / trigram  —— 词序与局部上下文
      * char trigram（滑窗 3 字符，含空格）
            —— 子词结构，对拼写错误/词序天然鲁棒：
               "helo" 与 "hello" 共享 hel/elo 等大量 trigram，特征向量近乎一致。
    全部映射进 IN_DIM 个桶（mask = IN_DIM-1，IN_DIM 为 2 的幂）。
    """
    norm = nlu_normalize(text)
    toks = nlu_tokenize(norm)
    dim = IN_DIM
    mask = dim - 1
    acc = [0] * dim

    def _add(h):
        acc[h & mask] += -1 if ((h >> 6) & 1) else 1

    # 第 4/5/6 步：token unigram
    for t in toks:
        _add(fnv1a(t.encode("latin-1")))

    # token bigram（与 unigram 共享同一 acc）
    nb = min(len(toks) - 1, NLU_BIGRAM_MAX) if len(toks) > 1 else 0
    for i in range(nb):
        _add(fnv1a((toks[i] + " " + toks[i + 1]).encode("latin-1")))

    # token trigram（相邻三词）
    nt = len(toks)
    if nt > 2:
        for i in range(nt - 2):
            _add(fnv1a((toks[i] + " " + toks[i + 1] + " " + toks[i + 2]).encode("latin-1")))

    # char trigram：在归一化文本上滑 3 字符窗（空格也参与），对拼写错误鲁棒。
    # 为保持 FR-N01 不变性（大小写/标点/空格变体必须同向量），左右空格先 strip。
    ctext = norm.strip()
    nlen = len(ctext)
    for i in range(nlen - 2):
        _add(fnv1a(ctext[i:i + 3].encode("latin-1")))

    # 第 7 步：最后统一 clamp（禁止边加边裁剪）
    return [clamp_i(v, -127, 127) for v in acc]


def feat_hex(feat):
    return "".join("%02x" % (v & 0xFF) for v in feat)


# --------------------------------------------------------------------------
# 语料加载与切分
# --------------------------------------------------------------------------
def load_corpus(path):
    if not os.path.isfile(path):
        raise SystemExit("[FAIL] corpus missing: %s (run tools/gen_corpus.py first)" % path)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data


AUG_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _aug_typo(ws, rng):
    """对随机一个长度>=4 的词做单字符级编辑（删/换位/重复），模拟拼写错误。
    与 gen_corpus.op_typo 同分布：只扰动非判别长词，单字符编辑。"""
    cand = [i for i, w in enumerate(ws) if len(w) >= 4]
    if not cand:
        return ws
    i = rng.choice(cand)
    w = ws[i]
    mode = rng.randrange(3)
    if mode == 0:                          # 删除一个字母
        k = rng.randrange(len(w))
        w2 = w[:k] + w[k + 1:]
    elif mode == 1 and len(w) >= 2:        # 交换相邻字母
        k = rng.randrange(len(w) - 1)
        w2 = w[:k] + w[k + 1] + w[k] + w[k + 2:]
    else:                                  # 重复一个字母
        k = rng.randrange(len(w))
        w2 = w[:k + 1] + w[k] + w[k + 1:]
    ws[i] = w2
    return ws


def _aug_order(ws, rng):
    """词序扰动：移动 please/now 到句首，否则交换前两个词。与 gen_corpus.op_order 一致。"""
    if len(ws) < 2:
        return ws
    if ws[-1] == "please":
        return ["please"] + ws[:-1]
    if ws[-1] == "now":
        return ["now"] + ws[:-1]
    if len(ws) >= 3 and ws[0] == "please":
        return ws[1:] + ["please"]
    ws[0], ws[1] = ws[1], ws[0]
    return ws


def augment(train, rng, n_aug, p_noise, p_drop, p_typo=0.0, p_order=0.0):
    """训练期数据增强：为每个带标签样本生成 n_aug 个副本。

    为什么需要它：ARCH §6 的 hashing trick 把每个 n-gram 独立映射到 IN_DIM 个桶，
    一个拼写错误的单词会变成一个**全新的桶**（与原词毫无关系）。如果不做增强，
    模型只能死记整句特征向量，遇到没见过的错拼词就崩（实测 typo 子集只有 0.56）。

    五类增强算子，直接对准这个失效模式：
      * 插入噪声词：随机 3..8 字母的无意义词 -> 模拟"出现了一个未知词"
      * 丢弃一个词：模拟"某个词没进来"
      * 字符级错拼（typo）：删/换位/重复一个字母 -> 模拟真实拼写错误
      * 词序扰动（order）：交换/移动词 -> 模拟语序变化
      * 替换一个词（丢+插噪声）：等价于"这个词被错拼成完全未知的词"
    其中 typo/order 与校验集（gen_corpus 生成的 perturb 子集）同分布，专门把
    hard(typo/order) 准确率拉过门槛。
    """
    if n_aug <= 0:
        return []
    extra = []
    for it in train:
        if it["intent"] < 0:
            continue
        words = it["text"].split()
        if not words:
            continue
        for _ in range(n_aug):
            ws = list(words)
            r = rng.random()

            def noise_word():
                return "".join(rng.choice(AUG_LETTERS)
                               for _ in range(rng.randrange(3, 9)))

            if r < p_noise:
                # (a) 只插入噪声词：模拟"多了一个未知词"
                ws.insert(rng.randrange(len(ws) + 1), noise_word())
                ops = ["augment"]
            elif r < p_noise + p_drop:
                # (b) 只丢弃一个词：模拟"某个词没进来"
                if len(ws) > 1:
                    del ws[rng.randrange(len(ws))]
                ops = ["augment"]
            elif r < p_noise + p_drop + p_typo:
                # (c) 字符级错拼：与 val typo 子集同分布
                ws = _aug_typo(ws, rng)
                ops = ["augment", "typo"]
            elif r < p_noise + p_drop + p_typo + p_order:
                # (d) 词序扰动：与 val order 子集同分布
                ws = _aug_order(ws, rng)
                ops = ["augment", "order"]
            else:
                # (e) 替换一个词：丢 + 插，等价于"这个词被错拼成完全未知的词"
                if len(ws) > 1:
                    del ws[rng.randrange(len(ws))]
                ws.insert(rng.randrange(len(ws) + 1), noise_word())
                ops = ["augment"]
            text = " ".join(ws)
            if text == it["text"]:
                continue
            feat = nlu_extract_py(text)
            extra.append({
                "text": text,
                "intent": it["intent"],
                "ops": ops,
                "_feat": feat,
                "_nz": [(i, v) for i, v in enumerate(feat) if v != 0],
            })
    return extra


def build_dataset(corpus, seed, val_per_intent=24, oov_bg=240):
    """返回 (train_items, val_items, oov_items)。
    train/val 按意图分层；OOV 语料严格不进训练集。"""
    rng = random.Random(seed)
    by_intent = {}
    for s in corpus["samples"]:
        by_intent.setdefault(s["intent"], []).append(s)
    train, val = [], []
    for k in sorted(by_intent):
        items = list(by_intent[k])
        rng.shuffle(items)
        val.extend(items[:val_per_intent])
        train.extend(items[val_per_intent:])
    for it in train + val:
        it["_feat"] = nlu_extract_py(it["text"])
        it["_nz"] = [(i, v) for i, v in enumerate(it["_feat"]) if v != 0]

    # 背景噪声：目标为均匀分布，用于压低 OOV 输入的置信度（FR-N06）
    bg = []
    for _ in range(oov_bg):
        k = rng.randrange(1, 4)
        s = " ".join(rng.choice(BG_WORDS) for _ in range(k))
        text = rng.choice(BG_PATTERNS).format(s=s)
        bg.append({"text": text, "intent": -1, "ops": ["background"]})
    for it in bg:
        it["_feat"] = nlu_extract_py(it["text"])
        it["_nz"] = [(i, v) for i, v in enumerate(it["_feat"]) if v != 0]
    train.extend(bg)

    oov = []
    for s in corpus["oov"]:
        s = dict(s)
        s["_feat"] = nlu_extract_py(s["text"])
        s["_nz"] = [(i, v) for i, v in enumerate(s["_feat"]) if v != 0]
        oov.append(s)

    train.extend(augment(train, rng, _AUG_N[0], _AUG_P_NOISE[0], _AUG_P_DROP[0],
                          _AUG_P_TYPO[0], _AUG_P_ORDER[0]))
    rng.shuffle(train)
    return train, val, oov


# 由 main() 在解析参数后写入，避免给 build_dataset 增加一堆位置参数
_AUG_N = [2]
_AUG_P_NOISE = [0.25]
_AUG_P_DROP = [0.20]
_AUG_P_TYPO = [0.30]
_AUG_P_ORDER = [0.15]


# --------------------------------------------------------------------------
# float MLP：前向 / 反向 / SGD
# --------------------------------------------------------------------------
def init_model(rng):
    s1 = math.sqrt(2.0 / IN_DIM)
    s2 = math.sqrt(2.0 / HID)
    W1 = [[rng.gauss(0.0, s1) for _ in range(IN_DIM)] for _ in range(HID)]
    b1 = [0.0] * HID
    W2 = [[rng.gauss(0.0, s2) for _ in range(HID)] for _ in range(OUT)]
    b2 = [0.0] * OUT
    return {"W1": W1, "b1": b1, "W2": W2, "b2": b2}


def fwd_train(m, nz):
    W1, b1, W2, b2 = m["W1"], m["b1"], m["W2"], m["b2"]
    acc1 = [0.0] * HID
    for i in range(HID):
        row = W1[i]
        s = b1[i]
        for j, v in nz:
            s += row[j] * v
        acc1[i] = s
    a1 = [x if x > 0.0 else 0.0 for x in acc1]
    nz1 = [i for i in range(HID) if a1[i] > 0.0]
    logits = []
    for c in range(OUT):
        row = W2[c]
        s = b2[c]
        for i in nz1:
            s += row[i] * a1[i]
        logits.append(s)
    mx = max(logits)
    ex = [math.exp(v - mx) for v in logits]
    sm = sum(ex)
    probs = [v / sm for v in ex]
    return acc1, a1, nz1, logits, probs


def fwd_float(m, feat):
    """只用特征向量做前向，返回 logits（浮点，评估用）。"""
    nz = [(i, v) for i, v in enumerate(feat) if v != 0]
    _, _, _, logits, _ = fwd_train(m, nz)
    return logits


def train_model(train, seed, epochs, lr0, batch, l2, mu, decay_every, verbose, l1=0.0):
    rng = random.Random(seed + 7)
    m = init_model(rng)
    W1, b1, W2, b2 = m["W1"], m["b1"], m["W2"], m["b2"]
    vW1 = [[0.0] * IN_DIM for _ in range(HID)]
    vW2 = [[0.0] * HID for _ in range(OUT)]
    vb1 = [0.0] * HID
    vb2 = [0.0] * OUT

    order = list(range(len(train)))
    t0 = time.time()
    for ep in range(epochs):
        rng.shuffle(order)
        lr = lr0 * (0.5 ** (ep // decay_every))
        inv_b = 1.0 / batch
        total_loss = 0.0
        pos = 0
        while pos < len(order):
            chunk = order[pos:pos + batch]
            pos += batch
            n = len(chunk)
            gW1 = [[0.0] * IN_DIM for _ in range(HID)]
            gW2 = [[0.0] * HID for _ in range(OUT)]
            gb1 = [0.0] * HID
            gb2 = [0.0] * OUT
            for si in chunk:
                it = train[si]
                nz = it["_nz"]
                y = it["intent"]
                acc1, a1, nz1, logits, probs = fwd_train(m, nz)
                if y < 0:
                    # 背景噪声：目标是 12 类均匀分布（压低 OOV 置信度）
                    d = [p - (1.0 / OUT) for p in probs]
                    total_loss += -sum(math.log(p + 1e-12) * (1.0 / OUT) for p in probs)
                else:
                    d = list(probs)
                    d[y] -= 1.0
                    total_loss += -math.log(probs[y] + 1e-12)
                # L2 梯度
                for c in range(OUT):
                    g = d[c]
                    if g == 0.0:
                        continue
                    gb2[c] += g
                    gr = gW2[c]
                    for i in nz1:
                        gr[i] += g * a1[i]
                for i in nz1:
                    s = 0.0
                    for c in range(OUT):
                        s += W2[c][i] * d[c]
                    if s == 0.0:
                        continue
                    gb1[i] += s
                    rw = gW1[i]
                    for j, v in nz:
                        rw[j] += s * v
            # 更新
            for i in range(HID):
                Wi, gi, vi = W1[i], gW1[i], vW1[i]
                for j in range(IN_DIM):
                    wj = Wi[j]
                    grad = gi[j] * inv_b + l2 * wj
                    if l1 != 0.0:
                        grad += l1 if wj > 0.0 else (-l1 if wj < 0.0 else 0.0)
                    vi[j] = mu * vi[j] - lr * grad
                    Wi[j] += vi[j]
                if gb1[i] != 0.0:
                    vb1[i] = mu * vb1[i] - lr * (gb1[i] * inv_b)
                    b1[i] += vb1[i]
            for c in range(OUT):
                Wc, gc, vc = W2[c], gW2[c], vW2[c]
                for i in range(HID):
                    wi = Wc[i]
                    grad = gc[i] * inv_b + l2 * wi
                    if l1 != 0.0:
                        grad += l1 if wi > 0.0 else (-l1 if wi < 0.0 else 0.0)
                    vc[i] = mu * vc[i] - lr * grad
                    Wc[i] += vc[i]
                if gb2[c] != 0.0:
                    vb2[c] = mu * vb2[c] - lr * (gb2[c] * inv_b)
                    b2[c] += vb2[c]
        if verbose:
            sys.stdout.write("    epoch %2d/%d  lr=%.5f  loss=%.4f  (%.1fs)\n"
                             % (ep + 1, epochs, lr, total_loss / len(order),
                                time.time() - t0))
    m["seconds"] = time.time() - t0
    return m


# --------------------------------------------------------------------------
# 量化标定（ARCH §5.4 步骤 2..6）
# --------------------------------------------------------------------------
def fit_shift(maxabs, limit=127.0):
    """最大 k 使 maxabs * 2^k <= limit（等价 floor(log2(limit/maxabs))）。"""
    k = 0
    while maxabs * (2.0 ** k) > limit and k > -32:
        k -= 1
    while maxabs * (2.0 ** (k + 1)) <= limit and k < 32:
        k += 1
    return k


def quantize(m, train_feats):
    W1, b1, W2, b2 = m["W1"], m["b1"], m["W2"], m["b2"]

    # 步骤 2：k1
    mw1 = max(abs(v) for row in W1 for v in row)
    k1 = fit_shift(mw1)
    p1 = 2.0 ** k1
    W1q = [[clamp_i(round_half_up(v * p1), -127, 127) for v in row] for row in W1]
    b1q = [round_half_up(v * p1) for v in b1]

    # 步骤 3：全训练集算 max_a1 -> r1
    max_a1 = 0
    for feat in train_feats:
        nz = [(i, v) for i, v in enumerate(feat) if v != 0]
        for i in range(HID):
            row = W1q[i]
            acc = b1q[i]
            for j, v in nz:
                acc += row[j] * v
            if acc > max_a1:
                max_a1 = acc
    r1 = 0
    while (max_a1 >> r1) > 127:
        r1 += 1

    # 步骤 4：k2
    mw2 = max(abs(v) for row in W2 for v in row)
    k2 = fit_shift(mw2)
    p2 = 2.0 ** k2
    W2q = [[clamp_i(round_half_up(v * p2), -127, 127) for v in row] for row in W2]

    # 步骤 5：OUT_SHIFT = k1 + k2 - r1，并把它夹在 [8, 14]
    out_shift = k1 + k2 - r1
    if out_shift < 8:
        r1 -= (8 - out_shift)
        if r1 < 0:
            r1 = 0
        out_shift = k1 + k2 - r1
    elif out_shift > 14:
        r1 += (out_shift - 14)
        out_shift = k1 + k2 - r1

    # 步骤 6：b2q（定点 Q(OUT_SHIFT)）
    p_out = 2.0 ** out_shift
    b2q = [round_half_up(v * p_out) for v in b2]

    # exp LUT（Q15）
    lut = []
    for i in range(LUT_ENTRIES):
        q = round_half_up(math.exp(-(i * (2.0 ** -LUT_SHIFT))) * 32768.0)
        lut.append(clamp_i(q, 0, 65535))

    return {
        "k1": k1, "r1": r1, "k2": k2, "out_shift": out_shift,
        "lut_shift": LUT_SHIFT,
        "soft_idx_shift": out_shift - LUT_SHIFT,
        "max_abs_w1": mw1, "max_abs_w2": mw2, "max_a1": max_a1,
        "W1q": W1q, "b1q": b1q, "W2q": W2q, "b2q": b2q, "lut": lut,
        "bytes": WEIGHTS_BYTES,
    }


# --------------------------------------------------------------------------
# 整数参考实现：逐位复刻 C 的移位 / 饱和 / 求和顺序（ARCH §5.5）
# --------------------------------------------------------------------------
def ref_forward(feat, Q):
    W1q, b1q, W2q, b2q = Q["W1q"], Q["b1q"], Q["W2q"], Q["b2q"]
    r1 = Q["r1"]
    a1 = []
    for i in range(HID):
        row = W1q[i]
        acc = b1q[i]
        for j in range(IN_DIM):
            acc += row[j] * feat[j]
        if acc < 0:
            acc = 0
        acc >>= r1                      # 被移位量恒非负，>> == floor，与 C 一致
        if acc > 127:
            acc = 127
        a1.append(acc)
    logits = []
    for c in range(OUT):
        row = W2q[c]
        acc = b2q[c]
        for i in range(HID):
            acc += row[i] * a1[i]
        logits.append(acc)
    return logits


def ref_softmax_top3(logits, Q):
    d_max = 511 << Q["soft_idx_shift"]
    sh = Q["soft_idx_shift"]
    lut = Q["lut"]
    m = max(logits)
    probs = []
    for l in logits:
        d = m - l
        if d > d_max:
            d = d_max
        probs.append(lut[d >> sh])
    s = sum(probs)
    pct = [((p * 100) + (s >> 1)) // s for p in probs]
    # Top-3：三轮线性 argmax，同分取 id 较小者
    used = []
    idx = []
    pcs = []
    for _ in range(3):
        best_i = 0
        best_v = -1
        for c in range(OUT):
            if c in used:
                continue
            if pct[c] > best_v:
                best_v = pct[c]
                best_i = c
        used.append(best_i)
        idx.append(best_i)
        pcs.append(pct[best_i])
    return probs, pct, idx, pcs, s


def argmax(v):
    bi = 0
    bv = v[0]
    for i in range(1, len(v)):
        if v[i] > bv:
            bv = v[i]
            bi = i
    return bi


# --------------------------------------------------------------------------
# 评估
# --------------------------------------------------------------------------
def evaluate(m, Q, val, oov):
    res = {}
    n_ok = 0
    n_pt = 0
    n_pt_ok = 0
    n_hard = 0
    n_hard_ok = 0
    agree = 0
    for it in val:
        lg_i = ref_forward(it["_feat"], Q)
        top_i = argmax(lg_i)
        lg_f = fwd_float(m, it["_feat"])
        top_f = argmax(lg_f)
        if top_i == it["intent"]:
            n_ok += 1
        if top_i == top_f:
            agree += 1
        if it.get("ops"):
            n_pt += 1
            if top_i == it["intent"]:
                n_pt_ok += 1
        if ("typo" in it.get("ops", [])) or ("order" in it.get("ops", [])):
            n_hard += 1
            if top_i == it["intent"]:
                n_hard_ok += 1
    res["val_n"] = len(val)
    res["top1"] = n_ok / len(val) if val else 0.0
    res["float_int_agreement"] = agree / len(val) if val else 0.0
    res["perturb_n"] = n_pt
    res["perturb_top1"] = (n_pt_ok / n_pt) if n_pt else 1.0
    res["hard_n"] = n_hard
    res["hard_top1"] = (n_hard_ok / n_hard) if n_hard else 1.0

    # float 版自身的准确率（用于步骤 8 对账参考）
    f_ok = sum(1 for it in val if argmax(fwd_float(m, it["_feat"])) == it["intent"])
    res["float_top1"] = f_ok / len(val) if val else 0.0

    # OOV 兜底率（FR-N06）
    fb = 0
    conf = []
    for it in oov:
        lg = ref_forward(it["_feat"], Q)
        _, _, _, pcs, _ = ref_softmax_top3(lg, Q)
        conf.append(pcs[0])
        if pcs[0] < 35:
            fb += 1
    res["oov_n"] = len(oov)
    res["oov_fallback_rate"] = (fb / len(oov)) if oov else 0.0
    res["oov_max_top1_pct"] = max(conf) if conf else 0
    res["oov_mean_top1_pct"] = (sum(conf) / len(conf)) if conf else 0.0
    return res


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------
def fmt_ints(vals, per_line, width=4):
    lines = []
    for i in range(0, len(vals), per_line):
        lines.append("    " + " ".join("%*d," % (width, v) for v in vals[i:i + per_line]))
    return "\n".join(lines)


def export_config(path, Q):
    sh = Q["soft_idx_shift"]
    txt = []
    txt.append("/* nn/config.h —— 由 tools/train.py 自动生成，禁止手改。")
    txt.append(" *")
    txt.append(" * 定点标定结果（ARCH §5.4 十步）：")
    txt.append(" *   k1 = W1_SHIFT      = %d   （W1/b1 定点小数位）" % Q["k1"])
    txt.append(" *   r1 = ACT1_SHIFT    = %d   （ReLU 后激活再量化右移位）" % Q["r1"])
    txt.append(" *   k2 = W2_SHIFT      = %d   （W2 定点小数位）" % Q["k2"])
    txt.append(" *   OUT_SHIFT          = %d   （= k1 + k2 - r1，logits 定点小数位）" % Q["out_shift"])
    txt.append(" *   LUT_SHIFT          = %d   （exp LUT 输入步长 2^-%d）" % (Q["lut_shift"], Q["lut_shift"]))
    txt.append(" *   SOFT_IDX_SHIFT     = %d   （= OUT_SHIFT - LUT_SHIFT）" % sh)
    txt.append(" *   D_MAX              = %d   （= 511 << SOFT_IDX_SHIFT）" % (511 << sh))
    txt.append(" */")
    txt.append("#ifndef AIOS_NN_CONFIG_H_")
    txt.append("#define AIOS_NN_CONFIG_H_")
    txt.append("")
    txt.append('#include "core/types.h"')
    txt.append("")
    txt.append("/* ---- 维度契约（与模型权重严格一致） ---- */")
    txt.append("#define NLU_DIM         %d" % IN_DIM)
    txt.append("#define NN_HIDDEN       %d" % HID)
    txt.append("#define NN_CLASSES      %d" % OUT)
    txt.append("")
    txt.append("/* ARCH §3.7 的别名，供 shell/ 与 hw/ 使用 */")
    txt.append("#define NN_IN           NLU_DIM")
    txt.append("#define NN_HID          NN_HIDDEN")
    txt.append("#define NN_OUT          NN_CLASSES")
    txt.append("")
    txt.append("/* ---- 特征抽取常量（ARCH §6） ---- */")
    txt.append("#define NLU_MAX_CHARS     128")
    txt.append("#define NLU_MAX_TOKENS    32")
    txt.append("#define NLU_MAX_TOKEN_LEN 31")
    txt.append("#define NLU_USE_BIGRAM    %d" % USE_BIGRAM)
    txt.append("")
    txt.append("/* ---- 定点常量（训练脚本标定，勿手改） ---- */")
    txt.append("#define W1_SHIFT        %d" % Q["k1"])
    txt.append("#define ACT1_SHIFT      %d" % Q["r1"])
    txt.append("#define W2_SHIFT        %d" % Q["k2"])
    txt.append("#define OUT_SHIFT       %d" % Q["out_shift"])
    txt.append("#define LUT_SHIFT       %d" % Q["lut_shift"])
    txt.append("#define SOFT_IDX_SHIFT  (OUT_SHIFT - LUT_SHIFT)")
    txt.append("#define D_MAX           (511u << SOFT_IDX_SHIFT)")
    txt.append("#define CONF_THRESHOLD  35")
    txt.append("#define NN_LUT_ENTRIES  %d" % LUT_ENTRIES)
    txt.append("#define WEIGHTS_BYTES   %du" % Q["bytes"])
    txt.append("#define NN_WEIGHTS_BYTES WEIGHTS_BYTES")
    txt.append("")
    txt.append("STATIC_ASSERT(NLU_DIM == %d);" % IN_DIM)
    txt.append("STATIC_ASSERT(NN_HIDDEN == %d);" % HID)
    txt.append("STATIC_ASSERT(NN_CLASSES == %d);" % OUT)
    txt.append("STATIC_ASSERT(SOFT_IDX_SHIFT >= 0);")
    txt.append("STATIC_ASSERT(WEIGHTS_BYTES == (%d + %d + %d + %d));"
               % (IN_DIM * HID, HID * 4, HID * OUT, OUT * 4))
    txt.append("")
    txt.append("#endif  /* AIOS_NN_CONFIG_H_ */")
    txt.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(txt))


def export_weights(path, Q):
    txt = []
    txt.append("/* nn/model_weights.h —— 由 tools/train.py 自动生成，禁止手改。")
    txt.append(" *")
    txt.append(" * 布局（共 %d 字节，全部落在 .rodata）：" % Q["bytes"])
    txt.append(" *   nn_w1          %d x %d x 1B = %d   (int8,  Q%d)"
               % (HID, IN_DIM, HID * IN_DIM, Q["k1"]))
    txt.append(" *   nn_b1          %d     x 4B = %4d   (int32, Q%d)" % (HID, HID * 4, Q["k1"]))
    txt.append(" *   nn_w2          %d x %d x 1B = %d   (int8,  Q%d)"
               % (OUT, HID, OUT * HID, Q["k2"]))
    txt.append(" *   nn_b2          %d     x 4B = %4d   (int32, Q%d)" % (OUT, OUT * 4, Q["out_shift"]))
    txt.append(" *   nn_exp_lut_q15 %3d    x 2B = %4d   (uint16, Q15)" % (LUT_ENTRIES, LUT_ENTRIES * 2))
    txt.append(" *   nn_weights_bytes                         4   (uint32)")
    txt.append(" *")
    txt.append(" * 说明：本头文件同时给出 extern 声明与数据本体。数据本体被")
    txt.append(" * AIOS_NN_WEIGHTS_IMPL 宏包住，只有 nn/nn.c 在包含本文件前定义了它，")
    txt.append(" * 因此链接期只有一份定义，其他翻译单元只看到 extern 声明。")
    txt.append(" */")
    txt.append("#ifndef AIOS_NN_MODEL_WEIGHTS_H_")
    txt.append("#define AIOS_NN_MODEL_WEIGHTS_H_")
    txt.append("")
    txt.append('#include "nn/config.h"')
    txt.append("")
    txt.append("/* ---- 对外契约：extern 声明（任何翻译单元都能看到） ---- */")
    txt.append("extern const s8  nn_w1[NN_HIDDEN][NLU_DIM];")
    txt.append("extern const s32 nn_b1[NN_HIDDEN];")
    txt.append("extern const s8  nn_w2[NN_CLASSES][NN_HIDDEN];")
    txt.append("extern const s32 nn_b2[NN_CLASSES];")
    txt.append("extern const u16 nn_exp_lut_q15[%d];" % LUT_ENTRIES)
    txt.append("extern const u32 nn_weights_bytes;")
    txt.append("")
    txt.append("#ifdef AIOS_NN_WEIGHTS_IMPL")
    txt.append("/* ---- 数据本体：只在 nn/nn.c 里展开一次 ---- */")
    txt.append("")
    txt.append("const s8 nn_w1[NN_HIDDEN][NLU_DIM] = {")
    for i in range(HID):
        txt.append("    {" + ", ".join(str(v) for v in Q["W1q"][i]) + "},")
    txt.append("};")
    txt.append("")
    txt.append("const s32 nn_b1[NN_HIDDEN] = {")
    txt.append("    " + ", ".join(str(v) for v in Q["b1q"]) + ",")
    txt.append("};")
    txt.append("")
    txt.append("const s8 nn_w2[NN_CLASSES][NN_HIDDEN] = {")
    for c in range(OUT):
        txt.append("    {" + ", ".join(str(v) for v in Q["W2q"][c]) + "},")
    txt.append("};")
    txt.append("")
    txt.append("const s32 nn_b2[NN_CLASSES] = {")
    txt.append("    " + ", ".join(str(v) for v in Q["b2q"]) + ",")
    txt.append("};")
    txt.append("")
    txt.append("/* exp(-i * 2^-%d) 的 Q15 定点表，i ∈ [0, %d]；[0] = 32768 */"
               % (Q["lut_shift"], LUT_ENTRIES - 1))
    txt.append("const u16 nn_exp_lut_q15[%d] = {" % LUT_ENTRIES)
    for i in range(0, LUT_ENTRIES, 16):
        txt.append("    " + ", ".join(str(v) for v in Q["lut"][i:i + 16]) + ",")
    txt.append("};")
    txt.append("")
    txt.append("const u32 nn_weights_bytes = %du;" % Q["bytes"])
    txt.append("")
    txt.append("#endif  /* AIOS_NN_WEIGHTS_IMPL */")
    txt.append("#endif  /* AIOS_NN_MODEL_WEIGHTS_H_ */")
    txt.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(txt))


def export_golden_features(path, items):
    payload = {
        "version": 1,
        "dim": IN_DIM,
        "count": len(items),
        "spec": "ARCH §6 七步；大小写/标点/空格变体必须产生完全相同的 NLU_DIM 字节（256）",
        "items": items,
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def export_golden_vectors(path, items, Q):
    payload = {
        "version": 1,
        "dim": IN_DIM,
        "classes": OUT,
        "count": len(items),
        "shifts": {
            "W1_SHIFT": Q["k1"], "ACT1_SHIFT": Q["r1"], "W2_SHIFT": Q["k2"],
            "OUT_SHIFT": Q["out_shift"], "LUT_SHIFT": Q["lut_shift"],
            "SOFT_IDX_SHIFT": Q["soft_idx_shift"],
            "D_MAX": 511 << Q["soft_idx_shift"],
        },
        "items": items,
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


# --------------------------------------------------------------------------
# golden 数据构造
# --------------------------------------------------------------------------
def c_escape(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif 0x20 <= o <= 0x7E:
            out.append(ch)
        else:
            out.append("\\x%02x" % o)
    return "".join(out)


def make_golden_features(val, oov):
    """40 句 x 5 种变体 = 200 条，覆盖 12 类意图 + 边界输入。"""
    rng = random.Random(DEFAULT_SEED + 11)
    bases = []
    per = {}
    for it in val:
        k = it["intent"]
        if per.get(k, 0) < 3 and not it.get("ops"):
            bases.append(it["text"])
            per[k] = per.get(k, 0) + 1
    # 边界输入
    bases.append("")
    bases.append("   ")
    bases.append("!!!!????....")
    bases.append("a" * 200)
    bases.append("what is 0x100 times 0x10")
    # 归一化后为空 / 超长单词 / 纯数字
    while len(bases) < 40:
        bases.append(rng.choice(val)["text"])

    items = []
    for b in bases[:40]:
        variants = [
            b,
            b.upper(),
            b.title(),
            b + "!!!",
            "   " + b.replace(" ", "  ") + "  ",
        ]
        for vi, v in enumerate(variants):
            feat = nlu_extract_py(v)
            items.append({
                "id": len(items),
                "base_id": len(items) // 5,
                "variant": vi,
                "text": v,
                "feat": feat_hex(feat),
            })
    return items


def make_golden_vectors(val, Q):
    """20 条前向 golden：logits[12] + Top-3 idx/pct。"""
    rng = random.Random(DEFAULT_SEED + 23)
    picked = []
    seen = set()
    by_intent = {}
    for it in val:
        by_intent.setdefault(it["intent"], []).append(it)
    for k in sorted(by_intent):
        picked.append(by_intent[k][0])
    while len(picked) < 20:
        it = rng.choice(val)
        if it["text"] in seen:
            continue
        seen.add(it["text"])
        picked.append(it)
    items = []
    for it in picked[:20]:
        feat = nlu_extract_py(it["text"])
        lg = ref_forward(feat, Q)
        probs, pct, idx, pcs, s = ref_softmax_top3(lg, Q)
        items.append({
            "text": it["text"],
            "intent": it["intent"],
            "intent_name": INTENTS[it["intent"]],
            "feat": feat_hex(feat),
            "logits": lg,
            "prob_q15": probs,
            "pct": pct,
            "top3_id": idx,
            "top3_pct": pcs,
        })
    return items


def make_fuzz_strings(n, rng):
    """随机 / 对抗输入，用于特征对齐压力测试（NFR-06）。"""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,!?-_/\\|@#$%^&*()[]{}<>~`;:'\"=+"
    out = []
    for i in range(n):
        mode = i % 6
        if mode == 0:
            out.append("".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 128))))
        elif mode == 1:
            out.append("".join(rng.choice(alphabet) for _ in range(rng.randrange(128, 300))))
        elif mode == 2:
            out.append("z" * rng.randrange(1, 200))            # 超长单词
        elif mode == 3:
            out.append("".join(rng.choice("!@#$%^&*()") for _ in range(rng.randrange(1, 64))))
        elif mode == 4:
            out.append(" ".join("w%d" % rng.randrange(1000) for _ in range(rng.randrange(1, 60))))
        else:
            out.append("".join(rng.choice("0123456789 ") for _ in range(rng.randrange(0, 100))))
    return out


# --------------------------------------------------------------------------
# host 端 C / Python 对齐测试
# --------------------------------------------------------------------------
HOST_C_TMPL = r'''/* build/host_test/host_align.c —— 由 tools/train.py 自动生成，勿手改。
 *
 * 目的：把 nn/nn.c 与 nlu/nlu.c 编译成 host 可执行程序（freestanding 源码，
 * 不经任何修改），喂进与 Python 参考实现完全相同的输入，逐字节比对输出。
 * 这里刻意不 include 任何 libc 头文件（core/types.h 自 typedef 了 size_t，
 * 与宿主机 size_t 冲突），只手工声明一个 printf。
 */
extern int printf(const char *fmt, ...);

#include "nlu/nlu.h"
#include "nn/nn.h"

#define N_TEXT %d
#define N_FEAT %d

static const char *const g_text[N_TEXT] = {
%s
};

static const s8 g_feat[N_FEAT][NLU_DIM] = {
%s
};

int main(void)
{
    int i, j;
    for (i = 0; i < N_TEXT; i++) {
        s8 f[NLU_DIM];
        nlu_extract(g_text[i], f);
        printf("FEAT %%d ", i);
        for (j = 0; j < NLU_DIM; j++) {
            printf("%%02x", (u32)(u8)f[j]);
        }
        printf("\n");
    }
    for (i = 0; i < N_FEAT; i++) {
        s32 lg[NN_CLASSES];
        u8 idx[3];
        u8 pct[3];
        int k;
        nn_forward(g_feat[i], lg);
        nn_softmax_top3(lg, idx, pct);
        printf("FWD %%d", i);
        for (k = 0; k < NN_CLASSES; k++) {
            printf(" %%d", lg[k]);
        }
        printf(" |");
        for (k = 0; k < 3; k++) {
            printf(" %%u", (u32)idx[k]);
        }
        printf(" |");
        for (k = 0; k < 3; k++) {
            printf(" %%u", (u32)pct[k]);
        }
        printf("\n");
    }
    printf("META %%u %%u %%u %%u %%u\n",
           (u32)NN_CLASSES, (u32)NLU_DIM, (u32)NN_HIDDEN,
           (u32)nn_rom_bytes(), (u32)nn_weights_bytes);
    return 0;
}
'''


def find_zig():
    env = os.environ.get("AIOS_ZIG")
    if env and os.path.isfile(env):
        return [env]
    cand = os.path.join(
        os.path.dirname(os.path.dirname(sys.executable)),
        "Scripts", "python-zig.exe")
    if os.path.isfile(cand):
        return [cand]
    return [sys.executable, "-m", "ziglang"]


def run_host_align(feat_texts, feat_items, Q, verbose=True):
    """编译 nlu.c + nn.c 到 host 目标并跑数值对齐。返回 (ok, lines[])。"""
    out = []
    work = os.path.join(ROOT, "build", "host_test")
    os.makedirs(work, exist_ok=True)
    src = os.path.join(work, "host_align.c")
    exe = os.path.join(work, "host_align.exe")

    text_block = "\n".join('    "%s",' % c_escape(t) for t in feat_texts)
    feat_block = "\n".join(
        "    {" + ", ".join(str(v) for v in it["_vals"]) + "},"
        for it in feat_items)
    with open(src, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(HOST_C_TMPL % (len(feat_texts), len(feat_items), text_block, feat_block))

    zig = find_zig()
    cmd = zig + [
        "cc", "-target", "x86_64-windows-gnu", "-O2",
        "-I", ROOT,
        "-o", exe, src,
        os.path.join(ROOT, "nn", "nn.c"),
        os.path.join(ROOT, "nlu", "nlu.c"),
    ]
    if verbose:
        out.append("[align] compile: " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        out.append("[align] COMPILE FAILED rc=%d" % proc.returncode)
        out.append(proc.stdout[-4000:])
        out.append(proc.stderr[-4000:])
        return False, out
    run = subprocess.run([exe], capture_output=True, text=True)
    if run.returncode != 0:
        out.append("[align] RUN FAILED rc=%d" % run.returncode)
        out.append(run.stdout[-4000:])
        out.append(run.stderr[-4000:])
        return False, out

    c_feat = {}
    c_fwd = {}
    meta = None
    for line in run.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "FEAT":
            c_feat[int(parts[1])] = parts[2]
        elif parts[0] == "FWD":
            i = int(parts[1])
            bar1 = parts.index("|")
            rest = parts[bar1 + 1:]
            bar2 = rest.index("|")
            logits = [int(x) for x in parts[2:bar1]]
            idx = [int(x) for x in rest[:bar2]]
            pct = [int(x) for x in rest[bar2 + 1:]]
            c_fwd[i] = (logits, idx, pct)
        elif parts[0] == "META":
            meta = [int(x) for x in parts[1:]]

    # ---- 比对特征 ----
    bad_f = []
    for i, t in enumerate(feat_texts):
        want = feat_hex(nlu_extract_py(t))
        got = c_feat.get(i)
        if got != want:
            bad_f.append((i, t, want, got))
    # ---- 比对方 ----
    bad_g = []
    for i, it in enumerate(feat_items):
        lg = ref_forward(it["_vals"], Q)
        _, _, idx, pcs, _ = ref_softmax_top3(lg, Q)
        got = c_fwd.get(i)
        if got is None:
            bad_g.append((i, it.get("text", ""), "missing", None))
            continue
        if got[0] != lg or got[1] != idx or got[2] != pcs:
            bad_g.append((i, it.get("text", ""), (lg, idx, pcs), got))

    out.append("[align] feature vectors : %d/%d match"
               % (len(feat_texts) - len(bad_f), len(feat_texts)))
    out.append("[align] forward  vectors: %d/%d match"
               % (len(feat_items) - len(bad_g), len(feat_items)))
    if meta:
        out.append("[align] C META classes=%d dim=%d hidden=%d rom_bytes=%d var=%d"
                   % tuple(meta))
    for b in bad_f[:5]:
        out.append("[align]   FEAT MISMATCH #%d %r want=%s got=%s" % b)
    for b in bad_g[:5]:
        out.append("[align]   FWD  MISMATCH #%d %r\n           want=%s\n           got =%s" % b)
    return (len(bad_f) == 0 and len(bad_g) == 0), out


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="AIOS int8 MLP trainer")
    ap.add_argument("--corpus", default=os.path.join(HERE, "intent_corpus.json"))
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lr", type=float, default=0.03)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--l2", type=float, default=1e-5)
    ap.add_argument("--momentum", type=float, default=0.9)
    ap.add_argument("--decay-every", type=int, default=12)
    ap.add_argument("--val-per-intent", type=int, default=24)
    ap.add_argument("--oov-bg", type=int, default=240)
    ap.add_argument("--aug", type=int, default=2,
                    help="每个训练样本生成几个增强副本")
    ap.add_argument("--aug-noise", type=float, default=0.25)
    ap.add_argument("--aug-drop", type=float, default=0.20)
    ap.add_argument("--aug-typo", type=float, default=0.30,
                    help="增强中字符级错拼（typo）占比，对齐 val typo 子集")
    ap.add_argument("--aug-order", type=float, default=0.15,
                    help="增强中词序扰动（order）占比，对齐 val order 子集")
    ap.add_argument("--no-bigram", action="store_true",
                    help="关闭 bigram 特征（默认按 ARCH §6 开启）")
    ap.add_argument("--eval", action="store_true", help="只输出 JSON 报告")
    ap.add_argument("--diag", action="store_true", help="打印诊断信息（冲突/混淆矩阵）")
    ap.add_argument("--no-align", action="store_true")
    ap.add_argument("--no-train", action="store_true",
                    help="从 build/model_float.json 载入已训练的浮点模型")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    build_dir = os.path.join(ROOT, "build")
    os.makedirs(build_dir, exist_ok=True)
    log = []

    def emit(s):
        log.append(s)
        if not args.eval or args.verbose:
            sys.stdout.write(s + "\n")

    if args.no_bigram:
        globals()["NLU_BIGRAM_MAX"] = 0
        globals()["USE_BIGRAM"] = 0
    _AUG_N[0] = args.aug
    _AUG_P_NOISE[0] = args.aug_noise
    _AUG_P_DROP[0] = args.aug_drop
    _AUG_P_TYPO[0] = args.aug_typo
    _AUG_P_ORDER[0] = args.aug_order

    corpus = load_corpus(args.corpus)
    emit("[train] corpus: %d labeled + %d oov = %d"
         % (len(corpus["samples"]), len(corpus["oov"]), corpus["total"]))
    emit("[train] bigram: %s   aug: %d copy/sample (noise=%.2f drop=%.2f)"
         % ("OFF" if args.no_bigram else "ON", args.aug, args.aug_noise, args.aug_drop))

    train, val, oov = build_dataset(corpus, args.seed, args.val_per_intent, args.oov_bg)
    emit("[train] split : train=%d (含 %d 条背景噪声)  val=%d  oov=%d"
         % (len(train), args.oov_bg, len(val), len(oov)))
    emit("[train] features computed for %d items"
         % (len(train) + len(val) + len(oov)))

    float_cache = os.path.join(build_dir, "model_float.json")
    t0 = time.time()
    if args.no_train and os.path.isfile(float_cache):
        with open(float_cache, "r", encoding="utf-8") as fh:
            m = json.load(fh)
        m = {"W1": m["W1"], "b1": m["b1"], "W2": m["W2"], "b2": m["b2"]}
        emit("[train] loaded float model from %s" % float_cache)
    else:
        m = train_model(train, args.seed, args.epochs, args.lr, args.batch,
                        args.l2, args.momentum, args.decay_every, args.verbose)
        emit("[train] float SGD done in %.1fs (%d epochs)"
             % (time.time() - t0, args.epochs))
        with open(float_cache, "w", encoding="utf-8") as fh:
            json.dump({"W1": m["W1"], "b1": m["b1"], "W2": m["W2"], "b2": m["b2"]}, fh)

    train_feats = [it["_feat"] for it in train if it["intent"] >= 0]
    Q = quantize(m, train_feats)
    emit("[quant] k1=%d  max|W1|=%.4f" % (Q["k1"], Q["max_abs_w1"]))
    emit("[quant] max_a1=%d -> r1=%d" % (Q["max_a1"], Q["r1"]))
    emit("[quant] k2=%d  max|W2|=%.4f" % (Q["k2"], Q["max_abs_w2"]))
    emit("[quant] OUT_SHIFT = k1 + k2 - r1 = %d + %d - %d = %d"
         % (Q["k1"], Q["k2"], Q["r1"], Q["out_shift"]))
    emit("[quant] LUT_SHIFT=%d  SOFT_IDX_SHIFT=%d  D_MAX=%d"
         % (Q["lut_shift"], Q["soft_idx_shift"], 511 << Q["soft_idx_shift"]))
    emit("[quant] weights rom = %d bytes" % Q["bytes"])

    if args.diag:
        emit("[diag ] ---- feature collision ----")
        buckets = {}
        for it in train + val:
            if it["intent"] < 0:
                continue
            buckets.setdefault(tuple(it["_feat"]), set()).add(it["intent"])
        conflict = {k: v for k, v in buckets.items() if len(v) > 1}
        emit("[diag ] distinct labeled feature vectors: %d / %d"
             % (len(buckets), sum(1 for it in train + val if it["intent"] >= 0)))
        emit("[diag ] feature vectors with conflicting labels: %d" % len(conflict))
        zero = sum(1 for it in train + val
                   if it["intent"] >= 0 and all(v == 0 for v in it["_feat"]))
        emit("[diag ] all-zero feature vectors: %d" % zero)

        emit("[diag ] ---- accuracy on TRAIN (float) ----")
        tr_ok = sum(1 for it in train
                    if it["intent"] >= 0 and argmax(fwd_float(m, it["_feat"])) == it["intent"])
        tr_n = sum(1 for it in train if it["intent"] >= 0)
        emit("[diag ] train_top1 = %.4f (%d/%d)" % (tr_ok / tr_n, tr_ok, tr_n))

        emit("[diag ] ---- val confusion (rows=true, cols=pred) ----")
        cm = [[0] * OUT for _ in range(OUT)]
        for it in val:
            p = argmax(ref_forward(it["_feat"], Q))
            cm[it["intent"]][p] += 1
        emit("[diag ]        " + " ".join("%5s" % n[:5] for n in INTENTS))
        for r in range(OUT):
            emit("[diag ] %-6s " % INTENTS[r][:6] + " ".join("%5d" % v for v in cm[r]))
        emit("[diag ] ---- per-op val accuracy ----")
        for op in ["", "case", "punct", "synonym", "typo", "order", "background"]:
            sub = [it for it in val if (op in it.get("ops", []) if op else not it.get("ops"))]
            if not sub:
                continue
            ok = sum(1 for it in sub
                     if argmax(ref_forward(it["_feat"], Q)) == it["intent"])
            emit("[diag ]   %-11s n=%3d  acc=%.4f" % (op or "clean", len(sub), ok / len(sub)))

    res = evaluate(m, Q, val, oov)
    emit("[eval ] top1                = %.4f  (%d/%d)"
         % (res["top1"], round(res["top1"] * res["val_n"]), res["val_n"]))
    emit("[eval ] perturb_top1        = %.4f  (n=%d)"
         % (res["perturb_top1"], res["perturb_n"]))
    emit("[eval ] hard(typo/order)    = %.4f  (n=%d)"
         % (res["hard_top1"], res["hard_n"]))
    emit("[eval ] float_top1          = %.4f" % res["float_top1"])
    emit("[eval ] int/float agreement = %.4f" % res["float_int_agreement"])
    emit("[eval ] oov fallback rate   = %.4f  (%d/%d), max top1 pct=%d%%"
         % (res["oov_fallback_rate"], round(res["oov_fallback_rate"] * res["oov_n"]),
            res["oov_n"], res["oov_max_top1_pct"]))

    # ---- golden 数据 ----
    gf = make_golden_features(val, oov)
    gv = make_golden_vectors(val, Q)
    emit("[golden] features=%d  vectors=%d" % (len(gf), len(gv)))

    # 不变性自查（FR-N01）
    inv_bad = 0
    groups = {}
    for it in gf:
        groups.setdefault(it["base_id"], []).append(it["feat"])
    for k, v in groups.items():
        if len(set(v)) != 1:
            inv_bad += 1
    emit("[golden] invariance groups=%d  violations=%d" % (len(groups), inv_bad))

    # ---- 导出 ----
    export_config(os.path.join(ROOT, "nn", "config.h"), Q)
    export_weights(os.path.join(ROOT, "nn", "model_weights.h"), Q)
    export_golden_features(os.path.join(HERE, "golden_features.json"), gf)
    export_golden_vectors(os.path.join(HERE, "golden_vectors.json"), gv, Q)
    emit("[export] nn/config.h  nn/model_weights.h")
    emit("[export] tools/golden_features.json  tools/golden_vectors.json")

    # ---- host 对齐 ----
    align_ok = None
    align_detail = []
    if not args.no_align:
        rng = random.Random(DEFAULT_SEED + 99)
        fuzz = make_fuzz_strings(60, rng)
        texts = [it["text"] for it in gf] + fuzz
        fits = []
        for it in gv:
            fits.append({"text": it["text"],
                         "_vals": [int(it["feat"][i * 2:i * 2 + 2], 16) - 256
                                   if int(it["feat"][i * 2:i * 2 + 2], 16) > 127
                                   else int(it["feat"][i * 2:i * 2 + 2], 16)
                                   for i in range(IN_DIM)]})
        # 再补 20 条随机特征向量，覆盖极值
        for _ in range(20):
            v = [rng.randrange(-127, 128) for _ in range(IN_DIM)]
            fits.append({"text": "<random>", "_vals": v})
        ok, detail = run_host_align(texts, fits, Q, verbose=args.verbose)
        align_ok = ok
        align_detail = detail
        for line in detail:
            emit(line)
        emit("[align] %s (%d feature texts, %d forward vectors)"
             % ("PASS" if ok else "FAIL", len(texts), len(fits)))

    # ---- 报告 ----
    report = {
        "version": 1,
        "seed": args.seed,
        "corpus": {
            "labeled": len(corpus["samples"]),
            "oov": len(corpus["oov"]),
            "total": corpus["total"],
            "per_intent": corpus.get("per_intent"),
        },
        "split": {"train": len(train), "val": len(val), "oov_eval": len(oov),
                  "oov_background": args.oov_bg, "val_per_intent": args.val_per_intent},
        "train": {"epochs": args.epochs, "lr": args.lr, "batch": args.batch,
                  "l2": args.l2, "momentum": args.momentum,
                  "seconds": round(m.get("seconds", 0.0), 2)},
        "quant": {
            "k1": Q["k1"], "r1": Q["r1"], "k2": Q["k2"],
            "OUT_SHIFT": Q["out_shift"], "LUT_SHIFT": Q["lut_shift"],
            "SOFT_IDX_SHIFT": Q["soft_idx_shift"],
            "D_MAX": 511 << Q["soft_idx_shift"],
            "max_abs_w1": Q["max_abs_w1"], "max_abs_w2": Q["max_abs_w2"],
            "max_a1": Q["max_a1"],
            "weights_bytes": Q["bytes"],
        },
        "metrics": res,
        "golden": {"features": len(gf), "vectors": len(gv),
                   "invariance_violations": inv_bad},
        "align": {"ok": align_ok, "detail": align_detail},
    }
    with open(os.path.join(build_dir, "train_report.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    if args.eval:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=1) + "\n")

    gate = []
    if res["top1"] < TOP1_MIN:
        gate.append("top1=%.4f < %.2f" % (res["top1"], TOP1_MIN))
    if res["perturb_top1"] < PERTURB_TOP1_MIN:
        gate.append("perturb_top1=%.4f < %.2f" % (res["perturb_top1"], PERTURB_TOP1_MIN))
    if res["float_int_agreement"] < 0.99:
        gate.append("float_int_agreement=%.4f < 0.99" % res["float_int_agreement"])
    if inv_bad != 0:
        gate.append("invariance_violations=%d" % inv_bad)
    if align_ok is False:
        gate.append("host_align=FAIL")

    if gate:
        sys.stderr.write("[FAIL] gate: " + "; ".join(gate) + "\n")
        return 1
    sys.stdout.write("[OK] gate passed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
