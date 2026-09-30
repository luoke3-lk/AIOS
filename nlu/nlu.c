/* nlu/nlu.c —— 特征抽取实现（ARCH §6 严格七步，顺序不可交换）
 *
 * 职责  : 一行 ASCII 文本 -> NLU_DIM 维 int8 有符号计数特征（token unigram/bigram/trigram + char trigram）。
 * 依赖  : core/types.h（经 nn/config.h 引入）。不引任何标准头，不用 libc。
 * 内存  : 全部在栈上，约 1.5 KB（norm 128 + tok 32x32 + bg 64 + acc 256）。
 * 确定性: 与 tools/train.py 的 nlu_extract_py() 逐字节一致，由
 *         tools/golden_features.json（200 条）+ host 对齐测试保证。
 * 不变性: 先跳过首尾空白再截 128 字符（等价于 Python 的
 *         text.strip(" \t\r\n")[:128]），保证大小写/标点/空格变体产生同一向量。
 */

#include "nlu/nlu.h"

#define NLU_SPACE        ' '
#define NLU_BIGRAM_MAX   31u
#define NLU_BIGRAM_BUF   ((NLU_MAX_TOKEN_LEN * 2u) + 2u)   /* 31 + 1 + 31 + 1 = 64 */
#define NLU_TRIGRAM_BUF  ((NLU_MAX_TOKEN_LEN * 3u) + 2u)   /* 31*3 + 2 = 95 */

/* FNV-1a 32 位：h = 0x811C9DC5; h ^= byte; h *= 0x01000193 （每步 mod 2^32） */
static u32 nlu_fnv1a_buf(const char *s, u32 n)
{
    u32 h = 0x811C9DC5u;
    u32 i;
    for (i = 0u; i < n; i++) {
        h = h ^ (u32)(u8)s[i];                       /* 先按无符号字节取值，防符号扩展 */
        h = (h * 0x01000193u) & 0xFFFFFFFFu;         /* unsigned int 自然回绕 */
    }
    return h;
}

u32 nlu_fnv1a(const char *s, size_t n)
{
    if (s == NULL) {
        return 0x811C9DC5u;
    }
    return nlu_fnv1a_buf(s, (u32)n);
}

void nlu_extract(const char *s, s8 out[NLU_DIM])
{
    char norm[NLU_MAX_CHARS];
    char tok[NLU_MAX_TOKENS][NLU_MAX_TOKEN_LEN + 1u];
    u8   tlen[NLU_MAX_TOKENS];
    s32  acc[NLU_DIM];
    u32  nlen = 0u;      /* norm 有效长度 */
    u32  ntok = 0u;      /* token 个数 */
    u32  p;
    u32  i;

    if (out == NULL) {
        return;
    }
    if (s == NULL) {
        s = "";
    }

    /* ---- 第 1 步 + 第 2 步：截断 128 字符并归一化（单遍扫描） ----
     * a. 大写转小写（先于任何判定）
     * b. 非 [a-z0-9] 一律视为分隔符 -> 写空格
     * c. 折叠连续分隔符：仅当 norm 末尾不是空格才写空格；不做 trim
     *
     * FR-N01 不变性修正：先跳过首尾空白再截 128。否则 "   a...a  "
     * 这样的变体，开头痛空格会吞掉截断额度，使归一化长度与基准不同。
     * 与 Python nlu_normalize 的 text.strip(" \t\r\n") 严格一致。
     */
    p = 0u;
    while (s[p] == ' ' || s[p] == '\t' || s[p] == '\r' || s[p] == '\n') {
        p++;
    }
    /* 跳过首空白后，再截取最多 NLU_MAX_CHARS(128) 个内容字符：
     * 等价于 Python nlu_normalize 的 text.strip(" \t\r\n")[:128]。
     * 用内容计数 cnt 限长，避免首空白占用 128 截断额度（FR-N01 不变性）。*/
    u32 cnt = 0u;
    for (; cnt < (u32)NLU_MAX_CHARS; cnt++, p++) {
        char c = s[p];
        if (c == '\0') {
            break;
        }
        if (c >= 'A' && c <= 'Z') {
            c = (char)(c + 32);
        }
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) {
            norm[nlen++] = c;
        } else if (nlen > 0u && norm[nlen - 1u] != NLU_SPACE) {
            norm[nlen++] = NLU_SPACE;
        }
    }

    /* ---- 第 3 步：按空格分词，上限 32 token，单 token 截断到 31 字符 ---- */
    p = 0u;
    while (p < nlen && ntok < (u32)NLU_MAX_TOKENS) {
        u32 k = 0u;
        if (norm[p] == NLU_SPACE) {
            p++;
            continue;
        }
        while (p < nlen && norm[p] != NLU_SPACE) {
            if (k < (u32)NLU_MAX_TOKEN_LEN) {
                tok[ntok][k++] = norm[p];
            }
            p++;
        }
        tok[ntok][k] = '\0';
        tlen[ntok] = (u8)k;
        ntok++;
    }

    /* ---- 第 4/5/6 步：四类特征共享同一个 s32 acc[NLU_DIM] ----
     * 与 tools/train.py 的 nlu_extract_py() 逐字节一致：
     *   idx = h & (NLU_DIM-1)   （NLU_DIM 为 2 的幂）
     *   sign = ((h >> 6) & 1u) ? -1 : +1
     *   acc[idx] += sign
     */
    {
        u32 mask = (u32)NLU_DIM - 1u;
        for (i = 0u; i < (u32)NLU_DIM; i++) {
            acc[i] = 0;
        }

        /* (a) token unigram */
        for (i = 0u; i < ntok; i++) {
            u32 h   = nlu_fnv1a_buf(tok[i], (u32)tlen[i]);
            acc[h & mask] += (((h >> 6) & 1u) != 0u) ? -1 : 1;
        }

        /* (b) token bigram */
#if NLU_USE_BIGRAM
        if (ntok > 1u) {
            char bg[NLU_BIGRAM_BUF];
            u32  nb = ntok - 1u;
            if (nb > NLU_BIGRAM_MAX) {
                nb = NLU_BIGRAM_MAX;
            }
            for (i = 0u; i < nb; i++) {
                u32 k = 0u;
                u32 a;
                for (a = 0u; a < (u32)tlen[i]; a++) {
                    bg[k++] = tok[i][a];
                }
                bg[k++] = NLU_SPACE;
                for (a = 0u; a < (u32)tlen[i + 1u]; a++) {
                    bg[k++] = tok[i + 1u][a];
                }
                {
                    u32 h = nlu_fnv1a_buf(bg, k);
                    acc[h & mask] += (((h >> 6) & 1u) != 0u) ? -1 : 1;
                }
            }
        }
#endif

        /* (c) token trigram（相邻三词：tok[i] SP tok[i+1] SP tok[i+2]） */
        if (ntok > 2u) {
            char tg[NLU_TRIGRAM_BUF];
            u32 nt = ntok - 2u;
            for (i = 0u; i < nt; i++) {
                u32 k = 0u;
                u32 a;
                for (a = 0u; a < (u32)tlen[i]; a++) {
                    tg[k++] = tok[i][a];
                }
                tg[k++] = NLU_SPACE;
                for (a = 0u; a < (u32)tlen[i + 1u]; a++) {
                    tg[k++] = tok[i + 1u][a];
                }
                tg[k++] = NLU_SPACE;
                for (a = 0u; a < (u32)tlen[i + 2u]; a++) {
                    tg[k++] = tok[i + 2u][a];
                }
                {
                    u32 h = nlu_fnv1a_buf(tg, k);
                    acc[h & mask] += (((h >> 6) & 1u) != 0u) ? -1 : 1;
                }
            }
        }

        /* (d) char trigram：在归一化文本上滑 3 字符窗（空格也参与），
         *     子词结构对拼写错误天然鲁棒。左右空格先 strip 以保证 FR-N01
         *     不变性（大小写/标点/空格变体必须产生相同向量），与 Python 侧
         *     norm.strip() 一致。 */
        {
            u32 s = 0u;
            while (s < nlen && norm[s] == NLU_SPACE) {
                s++;
            }
            u32 e = nlen;
            while (e > s && norm[e - 1u] == NLU_SPACE) {
                e--;
            }
            for (i = s; i + 3u <= e; i++) {
                char cg[3];
                cg[0] = norm[i];
                cg[1] = norm[i + 1u];
                cg[2] = norm[i + 2u];
                {
                    u32 h = nlu_fnv1a_buf(cg, 3u);
                    acc[h & mask] += (((h >> 6) & 1u) != 0u) ? -1 : 1;
                }
            }
        }
    }

    /* ---- 第 7 步：最后统一 clamp 到 [-127, 127]（禁止边加边裁剪） ---- */
    for (i = 0u; i < (u32)NLU_DIM; i++) {
        s32 v = acc[i];
        if (v < -127) {
            v = -127;
        }
        if (v > 127) {
            v = 127;
        }
        out[i] = (s8)v;
    }
}
