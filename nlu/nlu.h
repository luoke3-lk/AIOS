#ifndef AIOS_NLU_NLU_H_
#define AIOS_NLU_NLU_H_

/* nlu/nlu.h —— 自然语言 -> NLU_DIM 维 int8 特征（ARCH §6 严格七步）
 *
 * 七步顺序不可交换（C 侧与 Python 侧必须逐字节一致）：
 *   1. 输入截断 NLU_MAX_CHARS(128) 字符（遇 '\0' 提前结束）
 *   2. 归一化：先大写转小写，再判 alnum（非字母数字 -> 空格），折叠连续空格，不 trim
 *   3. 分词：上限 32 token，单 token 超 31 字符则截断（不丢弃）
 *   4. n-gram 展开（四类，顺序不可交换，全部共享同一个累加向量）：
 *        (a) token unigram
 *        (b) token bigram  ：tok[i] + ' ' + tok[i+1]，数量 min(n-1, NLU_BIGRAM_MAX=31)
 *        (c) token trigram ：tok[i] + ' ' + tok[i+1] + ' ' + tok[i+2]，数量 n-2（≤30）
 *        (d) 字符级 trigram：先把 norm 首尾空格 strip 掉（等价 Python norm.strip()，
 *            这是「前导/尾随空格不变性」的必要条件），再在剩余区间上滑 3 字符窗，
 *            内部空格参与，数量 (e-s)-2
 *            —— 这一类是对拼写错误鲁棒的关键：它不看词边界，因此 "memroy"/"memory"
 *              这类错字仍与正确写法共享大部分字符窗口，使特征向量收敛。
 *   5. FNV-1a 32 位逐字节哈希
 *   6. 有符号计数：idx = h & (NLU_DIM - 1), sign = (h >> 6) & 1,
 *                  acc[idx] += sign ? -1 : +1
 *      —— NLU_DIM 恒为 2 的幂，故取桶用掩码而非取模，不引入除法。
 *   7. 最后统一 clamp 到 [-127, 127]（禁止边加边裁剪）
 *
 * 属性：无 libc、无浮点、无堆、无静态可变状态（可在裸机与 host 上同一份代码跑）。
 */
#include "nn/config.h"

/* 把一行 ASCII 文本抽取成 NLU_DIM 维 int8 特征（当前 NLU_DIM = 256，见 nn/config.h）。
 * out 必须是长度 >= NLU_DIM 的数组。
 * s 或 out 为 NULL 时直接返回（防御式，裸机下不崩溃）。 */
void nlu_extract(const char *s, s8 out[NLU_DIM]);

/* 单独暴露 FNV-1a 便于测试与讲解。 */
u32 nlu_fnv1a(const char *s, size_t n);

#endif  /* AIOS_NLU_NLU_H_ */
