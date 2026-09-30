#ifndef AIOS_NN_NN_H_
#define AIOS_NN_NN_H_

/* nn/nn.h —— int8 量化 MLP 推理引擎（全整数、零浮点）
 *
 * 网络    : NLU_DIM(256) -> NN_HIDDEN(64, ReLU) -> NN_CLASSES(12, 线性)
 * 量化域  : W1q 定点 Q(k1)      = W1_SHIFT
 *           a1  定点 Q(k1-r1)   = ACT1_SHIFT 之后回到 int8 量级
 *           W2q 定点 Q(k2)      = W2_SHIFT
 *           logit 定点 Q(OUT_SHIFT)，OUT_SHIFT = k1 + k2 - r1
 * 推理    : acc1 = b1q + sum(W1q * x)      (int32)
 *           a1   = clamp(0..127, acc1 >> ACT1_SHIFT)
 *           acc2 = b2q + sum(W2q * a1)     (int32) -> 即 logit
 * Softmax : m = max(logit); d = clamp(m - logit, 0, D_MAX); idx = d >> SOFT_IDX_SHIFT;
 *           e = nn_exp_lut_q15[idx]; pct = (e*100 + sum/2) / sum
 *
 * 所有缩放一律用 2 的幂（移位），绝不用除法做缩放。
 * 所有被移位的量在移位前恒非负，故 C 的算术右移 == 数学 floor == Python 的 >>。
 *
 * 权重数据本体在 nn/model_weights.h（由 tools/train.py 生成，禁止手改）。
 */
#include "nn/config.h"

/* 一次完整推理的结果（ARCH §3.7）。top1 是置信度最高的类别 id。 */
typedef struct {
    s32 logits[NN_CLASSES];      /* 定点 Q(OUT_SHIFT) 的 logits */
    u16 prob_q15[NN_CLASSES];    /* Q15 定点概率（未归一化到 100） */
    u8  pct[NN_CLASSES];         /* 百分比整数，和约等 100（定点误差 ±3） */
    s8  top3_id[3];              /* Top-3 类别 id，按 pct 降序 */
    u8  top3_pct[3];             /* Top-3 百分比 */
    u8  top1;                    /* top3_id[0] 的副本，方便调用方 */
    u32 prob_sum;                /* Q15 概率之和，调试/自检用 */
} nn_result_t;

/* 前向：256 维 int8 特征 -> 12 个 int32 logit（定点 Q(OUT_SHIFT)）。 */
void nn_forward(const s8 x[NLU_DIM], s32 logits[NN_CLASSES]);

/* 定点 softmax + Top-3：三轮线性 argmax（禁 qsort、禁浮点）。
 * idx[3] 为类别 id（降序），pct[3] 为对应百分比整数。 */
void nn_softmax_top3(const s32 logits[NN_CLASSES], u8 idx[3], u8 pct[3]);

/* 定点 softmax 全量：写出 12 路 Q15 概率与 12 路百分比；sum_out 可为 NULL。 */
void nn_softmax_full(const s32 logits[NN_CLASSES],
                     u16 prob_q15[NN_CLASSES],
                     u8 pct[NN_CLASSES],
                     u32 *sum_out);

/* 一次跑完前向 + softmax + Top-3，直接填 nn_result_t（ARCH §3.7 兼容入口）。 */
void nn_forward_full(const s8 x[NLU_DIM], nn_result_t *out);

/* 权重 ROM 自检用（INTENT_MODELINFO）。
 *
 * 注意：权重字节数同时以三种形态提供，任选其一即可：
 *   1) 宏        WEIGHTS_BYTES   （编译期常量，2608u）
 *   2) 常量变量  nn_weights_bytes（model_weights.h 中 extern const u32，链接期）
 *   3) 函数      nn_rom_bytes()  （本文件提供）
 * 之所以没有把函数命名为 nn_weights_bytes()：C 语言里同名标识符不能同时是
 * 外部链接的函数和外部链接的对象，否则属于类型冲突的未定义行为。
 */
const s8 *nn_weights_w1(void);       /* W1 首元素地址 */
u32  nn_weights_rom_addr(void);      /* 权重 ROM 的物理地址 */
extern const u32 nn_weights_bytes;   /* 权重 ROM 字节数（model_weights.h 定义，链接期） */
size_t nn_rom_bytes(void);           /* 权重 ROM 字节数，= WEIGHTS_BYTES = 17456 */

#endif  /* AIOS_NN_NN_H_ */
