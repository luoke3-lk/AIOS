/* nn/nn.c —— int8 量化 MLP 前向 + 定点 softmax + Top-3
 *
 * 职责  : 全整数推理，不发射任何 x87/SSE/AVX 指令，不引 libc，不用堆。
 * 依赖  : core/types.h（经 nn/config.h）、nn/model_weights.h（训练脚本生成）。
 * 内存  : 仅栈上 s32 a1[32] + 若干局部变量，约 200 B。无静态可变状态。
 * 对应  : tools/train.py 的 ref_forward() / ref_softmax_top3()，两者逐位一致，
 *         由 tools/golden_vectors.json（20 条）+ host 对齐测试保证。
 *
 * 前向 MAC 次数：64*32 + 32*12 = 2432 次，远低于 NFR-02 的 200,000 条指令上限。
 */

/* 打开权重数据本体的编译开关：model_weights.h 里 extern 声明之后紧跟定义。 */
#define AIOS_NN_WEIGHTS_IMPL 1

#include "nn/model_weights.h"
#include "nn/nn.h"

/* ------------------------------------------------------------------ */
/* 第 1 层：acc1 = b1q + W1q * x ; ReLU ; 激活再量化回 int8 量级       */
/* ------------------------------------------------------------------ */
void nn_forward(const s8 x[NLU_DIM], s32 logits[NN_CLASSES])
{
    s32 a1[NN_HIDDEN];
    u32 i;
    u32 j;
    u32 c;

    for (i = 0u; i < (u32)NN_HIDDEN; i++) {
        const s8 *row = nn_w1[i];
        s32 acc = nn_b1[i];
        for (j = 0u; j < (u32)NLU_DIM; j++) {
            acc += (s32)row[j] * (s32)x[j];          /* int8 * int8 -> int32，无 libgcc 调用 */
        }
        if (acc < 0) {
            acc = 0;                                  /* ReLU 下限，保证后续右移语义 == floor */
        }
        acc >>= ACT1_SHIFT;                           /* 激活再量化 */
        if (acc > 127) {
            acc = 127;                                /* 回落到 int8 量级，防 int8 溢出 */
        }
        a1[i] = acc;
    }

    /* 第 2 层：acc2 = b2q + W2q * a1 -> 即定点 logit */
    for (c = 0u; c < (u32)NN_CLASSES; c++) {
        const s8 *row = nn_w2[c];
        s32 acc = nn_b2[c];
        for (i = 0u; i < (u32)NN_HIDDEN; i++) {
            acc += (s32)row[i] * a1[i];
        }
        logits[c] = acc;
    }
}

/* ------------------------------------------------------------------ */
/* 定点 softmax：Q15 exp LUT + 整数百分比                              */
/* ------------------------------------------------------------------ */
void nn_softmax_full(const s32 logits[NN_CLASSES],
                     u16 prob_q15[NN_CLASSES],
                     u8 pct[NN_CLASSES],
                     u32 *sum_out)
{
    s32 m;
    u32 c;
    u32 sum = 0u;

    m = logits[0];
    for (c = 1u; c < (u32)NN_CLASSES; c++) {
        if (logits[c] > m) {
            m = logits[c];
        }
    }

    for (c = 0u; c < (u32)NN_CLASSES; c++) {
        u32 d = (u32)(m - logits[c]);                /* 恒 >= 0，且在 int32 范围内 */
        u32 idx;
        u16 e;
        if (d > D_MAX) {
            d = D_MAX;                               /* 饱和：e^-31.9 ≈ 0 */
        }
        idx = d >> SOFT_IDX_SHIFT;                   /* 0..511，输入步长 2^-LUT_SHIFT */
        e = nn_exp_lut_q15[idx];
        prob_q15[c] = e;
        sum += (u32)e;                               /* 上界 12 * 32768 = 393216，安全 */
    }

    for (c = 0u; c < (u32)NN_CLASSES; c++) {
        /* pct = round(e * 100 / sum)，四舍五入靠 + sum/2，sum 恒 > 0 */
        pct[c] = (u8)((((u32)prob_q15[c] * 100u) + (sum >> 1u)) / sum);
    }

    if (sum_out != NULL) {
        *sum_out = sum;
    }
}

/* Top-3：三轮线性 argmax，pct 降序；同分取类别 id 较小者（与 Python 参考一致）。 */
void nn_softmax_top3(const s32 logits[NN_CLASSES], u8 idx[3], u8 pct[3])
{
    u16 prob[NN_CLASSES];
    u8  p[NN_CLASSES];
    u8  used[3];
    u32 k;
    u32 c;

    nn_softmax_full(logits, prob, p, NULL);

    used[0] = 255u;
    used[1] = 255u;
    used[2] = 255u;

    for (k = 0u; k < 3u; k++) {
        s32 best_v = -1;
        u8  best_i = 0u;
        for (c = 0u; c < (u32)NN_CLASSES; c++) {
            u32 t;
            s32 v;
            for (t = 0u; t < k; t++) {
                if (used[t] == (u8)c) {
                    break;
                }
            }
            if (t < k) {
                continue;                            /* 已经被选走 */
            }
            v = (s32)p[c];
            if (v > best_v) {
                best_v = v;
                best_i = (u8)c;
            }
        }
        idx[k] = best_i;
        pct[k] = p[best_i];
        used[k] = best_i;
    }
}

void nn_forward_full(const s8 x[NLU_DIM], nn_result_t *out)
{
    u32 c;
    if (out == NULL) {
        return;
    }
    nn_forward(x, out->logits);
    nn_softmax_full(out->logits, out->prob_q15, out->pct, &out->prob_sum);
    {
        u8 idx[3];
        u8 pct[3];
        nn_softmax_top3(out->logits, idx, pct);
        for (c = 0u; c < 3u; c++) {
            out->top3_id[c]  = (s8)idx[c];
            out->top3_pct[c] = pct[c];
        }
    }
    out->top1 = (u8)out->top3_id[0];
}

/* ------------------------------------------------------------------ */
/* 权重 ROM 自检                                                       */
/* ------------------------------------------------------------------ */
const s8 *nn_weights_w1(void)
{
    return &nn_w1[0][0];
}

u32 nn_weights_rom_addr(void)
{
    /* 32 位目标下指针本身就是 32 位。host 对齐测试会编成 64 位，先过一道 u64
       再截断：既消除 -Wpointer-to-int-cast，又不会引入 u64 移位/除法（常量折叠）。 */
    const s8 *p = nn_weights_w1();
    return (u32)((unsigned long long)p & 0xFFFFFFFFull);
}

size_t nn_rom_bytes(void)
{
    return (size_t)WEIGHTS_BYTES;
}
