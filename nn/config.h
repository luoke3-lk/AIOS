/* nn/config.h —— 由 tools/train.py 自动生成，禁止手改。
 *
 * 定点标定结果（ARCH §5.4 十步）：
 *   k1 = W1_SHIFT      = 7   （W1/b1 定点小数位）
 *   r1 = ACT1_SHIFT    = 3   （ReLU 后激活再量化右移位）
 *   k2 = W2_SHIFT      = 5   （W2 定点小数位）
 *   OUT_SHIFT          = 9   （= k1 + k2 - r1，logits 定点小数位）
 *   LUT_SHIFT          = 4   （exp LUT 输入步长 2^-4）
 *   SOFT_IDX_SHIFT     = 5   （= OUT_SHIFT - LUT_SHIFT）
 *   D_MAX              = 16352   （= 511 << SOFT_IDX_SHIFT）
 */
#ifndef AIOS_NN_CONFIG_H_
#define AIOS_NN_CONFIG_H_

#include "core/types.h"

/* ---- 维度契约（与模型权重严格一致） ---- */
#define NLU_DIM         256
#define NN_HIDDEN       64
#define NN_CLASSES      12

/* ARCH §3.7 的别名，供 shell/ 与 hw/ 使用 */
#define NN_IN           NLU_DIM
#define NN_HID          NN_HIDDEN
#define NN_OUT          NN_CLASSES

/* ---- 特征抽取常量（ARCH §6） ---- */
#define NLU_MAX_CHARS     128
#define NLU_MAX_TOKENS    32
#define NLU_MAX_TOKEN_LEN 31
#define NLU_USE_BIGRAM    1

/* ---- 定点常量（训练脚本标定，勿手改） ---- */
#define W1_SHIFT        7
#define ACT1_SHIFT      3
#define W2_SHIFT        5
#define OUT_SHIFT       9
#define LUT_SHIFT       4
#define SOFT_IDX_SHIFT  (OUT_SHIFT - LUT_SHIFT)
#define D_MAX           (511u << SOFT_IDX_SHIFT)
#define CONF_THRESHOLD  35
#define NN_LUT_ENTRIES  513
#define WEIGHTS_BYTES   17456u
#define NN_WEIGHTS_BYTES WEIGHTS_BYTES

STATIC_ASSERT(NLU_DIM == 256);
STATIC_ASSERT(NN_HIDDEN == 64);
STATIC_ASSERT(NN_CLASSES == 12);
STATIC_ASSERT(SOFT_IDX_SHIFT >= 0);
STATIC_ASSERT(WEIGHTS_BYTES == (16384 + 256 + 768 + 48));

#endif  /* AIOS_NN_CONFIG_H_ */
