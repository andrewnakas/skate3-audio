// VMX128 bit-exactness probe — C++ side (the reference).
//
// Every op body below is RexGlue's own lowering, copied verbatim from
// generated/skate3_recomp.*.cpp and third_party/rexglue-sdk/include/rex/ppc/intrinsics.h.
// Nothing here is a reimplementation: this side defines what "exact" means, and the
// Rust side must reproduce it bit-for-bit.
//
// Each op runs twice, once with MXCSR flush-to-zero off and once on, because RexGlue
// toggles FTZ per instruction class rather than per function.

#include <simde/x86/avx.h>
#include <simde/x86/sse.h>
#include <simde/x86/sse4.1.h>
#include <simde/x86/fma.h>

#include <bit>
#include <climits>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#ifndef _MM_DENORMALS_ZERO_MASK
#define _MM_DENORMALS_ZERO_MASK 0x0040
#endif

// ---------------------------------------------------------------- RexGlue helpers
namespace rex_ppc {

inline uint32_t ppc_vrsqrtefp_bits(uint32_t bits) {
  static constexpr uint32_t table[32] = {
      0x0568B4FD, 0x04F3AF97, 0x048DAAA5, 0x0435A618, 0x03E7A1E4, 0x03A29DFE,
      0x03659A5C, 0x032E96F8, 0x02FC93CA, 0x02D090CE, 0x02A88DFE, 0x02838B57,
      0x026188D4, 0x02438673, 0x02268431, 0x020B820B, 0x03D27FFA, 0x03807C29,
      0x033878AA, 0x02F97572, 0x02C27279, 0x02926FB7, 0x02666D26, 0x023F6AC0,
      0x021D6881, 0x01FD6665, 0x01E16468, 0x01C76287, 0x01AF60C1, 0x01995F12,
      0x01855D79, 0x01735BF4,
  };
  uint32_t sign = bits >> 31;
  uint32_t biased_exp = (bits >> 23) & 0xFF;
  uint32_t mantissa = bits & 0x007FFFFF;
  if (bits == 0xFF800000u) return 0x7FC00000u;
  if (biased_exp == 0) return sign ? 0xFF800000u : 0x7F800000u;
  if (biased_exp == 0xFF) { if (mantissa == 0) return 0; return bits | 0x00400000u; }
  if (sign) return 0x7FC00000u;
  int32_t unbiased_exp = int32_t(biased_exp) - 127;
  uint32_t index = ((((uint32_t(unbiased_exp) << 4) & 16) | (mantissa >> 19)) ^ 16);
  uint32_t interp = (mantissa >> 9) & 1023;
  int32_t result_exp = (127 - int32_t(biased_exp)) >> 1;
  uint32_t entry = table[index];
  uint32_t slope = entry >> 16;
  uint32_t base = (entry << 10) & 0x3FFFC00u;
  int32_t raw = int32_t(base) - int32_t(interp * slope);
  if (!(raw & (1 << 25))) {
    uint32_t val = uint32_t(raw) & 0x1FFFFFFu;
    uint32_t lz = std::countl_zero(val);
    int32_t shift = int32_t(lz) - 6;
    result_exp += 6 - int32_t(lz);
    raw <<= shift;
  }
  if ((raw & 5) && (raw & 2)) raw += 4;
  uint32_t result = uint32_t((result_exp << 23) + 0x3F800000) | ((uint32_t(raw) >> 2) & 0x7FFFFFu);
  if (((result >> 23) & 0xFF) == 0 && (result & 0x7FFFFF)) result = 0;
  return result;
}

inline float ppc_vrsqrtefp(float value) {
  return std::bit_cast<float>(ppc_vrsqrtefp_bits(std::bit_cast<uint32_t>(value)));
}

inline simde__m128 simde_mm_vrsqrtefp_ps(simde__m128 value) {
  alignas(16) float lanes[4];
  simde_mm_store_ps(lanes, value);
  for (float& lane : lanes) lane = ppc_vrsqrtefp(lane);
  return simde_mm_load_ps(lanes);
}

inline float ppc_vmsumfp_result(float value) {
  constexpr uint32_t qnan_bits = 0x7FC00000u;
  if (!std::isfinite(value)) return std::bit_cast<float>(qnan_bits);
  uint32_t bits = std::bit_cast<uint32_t>(value);
  if (((bits >> 23) & 0xFF) == 0 && (bits & 0x007FFFFFu) != 0) bits &= 0x80000000u;
  return std::bit_cast<float>(bits);
}

inline simde__m128 ppc_vmsumfp_result(simde__m128 value) {
  alignas(16) float lanes[4];
  simde_mm_store_ps(lanes, value);
  return simde_mm_set1_ps(ppc_vmsumfp_result(lanes[0]));
}

inline simde__m128 simde_mm_vmsum3fp128_ps(simde__m128 a, simde__m128 b) {
  return ppc_vmsumfp_result(simde_mm_dp_ps(a, b, 0xEF));
}
inline simde__m128 simde_mm_vmsum4fp128_ps(simde__m128 a, simde__m128 b) {
  return ppc_vmsumfp_result(simde_mm_dp_ps(a, b, 0xFF));
}

inline simde__m128 simde_mm_cvtepu32_ps_(simde__m128i src1) {
  simde__m128i xmm1 = simde_mm_add_epi32(src1, simde_mm_set1_epi32(127));
  simde__m128i xmm0 = simde_mm_slli_epi32(src1, 31 - 8);
  xmm0 = simde_mm_srli_epi32(xmm0, 31);
  xmm0 = simde_mm_add_epi32(xmm0, xmm1);
  xmm0 = simde_mm_srai_epi32(xmm0, 8);
  xmm0 = simde_mm_add_epi32(xmm0, simde_mm_set1_epi32(0x4F800000));
  simde__m128 xmm2 = simde_mm_cvtepi32_ps(src1);
  return simde_mm_blendv_ps(xmm2, simde_mm_castsi128_ps(xmm0), simde_mm_castsi128_ps(src1));
}

inline simde__m128i simde_mm_perm_epi8_(simde__m128i a, simde__m128i b, simde__m128i c) {
  simde__m128i d = simde_mm_set1_epi8(0xF);
  simde__m128i e = simde_mm_sub_epi8(d, simde_mm_and_si128(c, d));
  return simde_mm_blendv_epi8(simde_mm_shuffle_epi8(a, e), simde_mm_shuffle_epi8(b, e),
                              simde_mm_slli_epi32(c, 3));
}

inline simde__m128i simde_mm_vctsxs(simde__m128 src1) {
  simde__m128 xmm2 = simde_mm_cmpunord_ps(src1, src1);
  simde__m128i xmm0 = simde_mm_cvttps_epi32(src1);
  simde__m128i xmm1 = simde_mm_cmpeq_epi32(xmm0, simde_mm_set1_epi32(INT_MIN));
  xmm1 = simde_mm_andnot_si128(simde_mm_castps_si128(src1), xmm1);
  simde__m128 dest = simde_mm_blendv_ps(simde_mm_castsi128_ps(xmm0),
                                        simde_mm_castsi128_ps(simde_mm_set1_epi32(INT_MAX)),
                                        simde_mm_castsi128_ps(xmm1));
  return simde_mm_andnot_si128(simde_mm_castps_si128(xmm2), simde_mm_castps_si128(dest));
}

inline simde__m128i simde_mm_vctuxs(simde__m128 src1) {
  simde__m128 nan_mask = simde_mm_cmpunord_ps(src1, src1);
  simde__m128 neg_mask = simde_mm_cmplt_ps(src1, simde_mm_setzero_ps());
  simde__m128 max_val = simde_mm_set1_ps(4294967295.0f);
  simde__m128 overflow_mask = simde_mm_cmpge_ps(src1, max_val);
  simde__m128 clamped = simde_mm_max_ps(src1, simde_mm_setzero_ps());
  clamped = simde_mm_min_ps(clamped, max_val);
  simde__m128 half_range = simde_mm_set1_ps(2147483648.0f);
  simde__m128 high_bit_mask = simde_mm_cmpge_ps(clamped, half_range);
  simde__m128 adjusted = simde_mm_sub_ps(clamped, simde_mm_and_ps(high_bit_mask, half_range));
  simde__m128i low_bits = simde_mm_cvttps_epi32(adjusted);
  simde__m128i high_bit = simde_mm_and_si128(simde_mm_castps_si128(high_bit_mask),
                                             simde_mm_set1_epi32(int(0x80000000u)));
  simde__m128i result = simde_mm_or_si128(low_bits, high_bit);
  result = simde_mm_andnot_si128(simde_mm_castps_si128(nan_mask), result);
  result = simde_mm_andnot_si128(simde_mm_castps_si128(neg_mask), result);
  result = simde_mm_or_si128(
      simde_mm_andnot_si128(simde_mm_castps_si128(overflow_mask), result),
      simde_mm_and_si128(simde_mm_castps_si128(overflow_mask), simde_mm_set1_epi32(-1)));
  return result;
}


// The BE<->LE lane-reversal mask RexGlue applies on every vector load and store.
// Row 0 is the plain byte reversal used by lvx128/stvx128; later rows serve the
// misaligned lvlx/lvrx/stvlx/stvrx forms.
inline uint8_t VectorMaskL[] = {
    0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0x00,
    0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01,
    0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02,
    0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03,
    0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07,
};

}  // namespace rex_ppc

// ---------------------------------------------------------------- op table
typedef simde__m128i (*OpFn)(simde__m128i, simde__m128i, simde__m128i);

#define F(x) simde_mm_castps_si128(x)
#define P(x) simde_mm_castsi128_ps(x)

struct Op { const char* name; int arity; OpFn fn; };

// A value-commutative float op is NOT NaN-payload-commutative: the result takes the
// NaN of whichever operand the compiler placed in src1. GCC's choice depends on
// register allocation, so it is not stable across inlining contexts. Building with
// -DPIN_COMMUTATIVE_OPERAND_ORDER forces src1 = a, which is also the AltiVec rule
// (first NaN in the order vA, vB). See docs/vmx128-exactness.md.
// A "+x" register barrier is NOT enough - it pins the operand to a register but
// leaves the compiler free to commute the instruction. Only writing the instruction
// out fixes src1.
#ifdef PIN_COMMUTATIVE_OPERAND_ORDER
#define VBINOP(mnem, a, b) ({ simde__m128 r_; \
    asm(mnem " %2,%1,%0" : "=x"(r_) : "x"(a), "x"(b)); r_; })
#else
#define VBINOP(mnem, a, b) SIMDE_CAT(simde_mm_, SIMDE_CAT(mnem, _ps))(a, b)
#endif

static simde__m128i op_vaddfp   (simde__m128i a, simde__m128i b, simde__m128i) {
#ifdef PIN_COMMUTATIVE_OPERAND_ORDER
  simde__m128 r; asm("vaddps %2,%1,%0" : "=x"(r) : "x"(P(a)), "x"(P(b))); return F(r);
#else
  return F(simde_mm_add_ps(P(a), P(b)));
#endif
}
static simde__m128i op_vsubfp   (simde__m128i a, simde__m128i b, simde__m128i) { return F(simde_mm_sub_ps(P(a), P(b))); }
static simde__m128i op_vmulfp   (simde__m128i a, simde__m128i b, simde__m128i) {
#ifdef PIN_COMMUTATIVE_OPERAND_ORDER
  simde__m128 r; asm("vmulps %2,%1,%0" : "=x"(r) : "x"(P(a)), "x"(P(b))); return F(r);
#else
  return F(simde_mm_mul_ps(P(a), P(b)));
#endif
}
static simde__m128i op_vmaddfp  (simde__m128i a, simde__m128i b, simde__m128i c) { return F(simde_mm_fmadd_ps(P(a), P(b), P(c))); }
static simde__m128i op_vnmsubfp (simde__m128i a, simde__m128i b, simde__m128i c) { return F(simde_mm_fnmadd_ps(P(a), P(b), P(c))); }
static simde__m128i op_vmaxfp   (simde__m128i a, simde__m128i b, simde__m128i) {
#ifdef PIN_COMMUTATIVE_OPERAND_ORDER
  simde__m128 r; asm("vmaxps %2,%1,%0" : "=x"(r) : "x"(P(a)), "x"(P(b))); return F(r);
#else
  return F(simde_mm_max_ps(P(a), P(b)));
#endif
}
static simde__m128i op_vminfp   (simde__m128i a, simde__m128i b, simde__m128i) {
#ifdef PIN_COMMUTATIVE_OPERAND_ORDER
  simde__m128 r; asm("vminps %2,%1,%0" : "=x"(r) : "x"(P(a)), "x"(P(b))); return F(r);
#else
  return F(simde_mm_min_ps(P(a), P(b)));
#endif
}
static simde__m128i op_vrefp    (simde__m128i a, simde__m128i, simde__m128i) { return F(simde_mm_div_ps(simde_mm_set1_ps(1.0f), P(a))); }
static simde__m128i op_vrsqrtefp(simde__m128i a, simde__m128i, simde__m128i) { return F(rex_ppc::simde_mm_vrsqrtefp_ps(P(a))); }
static simde__m128i op_vrfiz    (simde__m128i a, simde__m128i, simde__m128i) { return F(simde_mm_round_ps(P(a), SIMDE_MM_FROUND_TO_ZERO | SIMDE_MM_FROUND_NO_EXC)); }
static simde__m128i op_vmsum3fp (simde__m128i a, simde__m128i b, simde__m128i) { return F(rex_ppc::simde_mm_vmsum3fp128_ps(P(a), P(b))); }
static simde__m128i op_vmsum4fp (simde__m128i a, simde__m128i b, simde__m128i) { return F(rex_ppc::simde_mm_vmsum4fp128_ps(P(a), P(b))); }
static simde__m128i op_vcmpeqfp (simde__m128i a, simde__m128i b, simde__m128i) { return F(simde_mm_cmpeq_ps(P(a), P(b))); }
static simde__m128i op_vcmpgefp (simde__m128i a, simde__m128i b, simde__m128i) { return F(simde_mm_cmpge_ps(P(a), P(b))); }
static simde__m128i op_vcmpgtfp (simde__m128i a, simde__m128i b, simde__m128i) { return F(simde_mm_cmpgt_ps(P(a), P(b))); }

// vexptefp128 / vlogefp128: RexGlue emits scalar libm per lane.
static simde__m128i op_vexptefp (simde__m128i a, simde__m128i, simde__m128i) {
  alignas(16) float l[4]; simde_mm_store_ps(l, P(a));
  for (int i = 0; i < 4; i++) l[i] = exp2f(l[i]);
  return F(simde_mm_load_ps(l));
}
static simde__m128i op_vlogefp  (simde__m128i a, simde__m128i, simde__m128i) {
  alignas(16) float l[4]; simde_mm_store_ps(l, P(a));
  for (int i = 0; i < 4; i++) l[i] = log2f(l[i]);
  return F(simde_mm_load_ps(l));
}

static simde__m128i op_vcsxwfp0 (simde__m128i a, simde__m128i, simde__m128i) { return F(simde_mm_cvtepi32_ps(a)); }
static simde__m128i op_vcsxwfp15(simde__m128i a, simde__m128i, simde__m128i) {
  return F(simde_mm_mul_ps(simde_mm_cvtepi32_ps(a), P(simde_mm_set1_epi32(int(0x38000000)))));
}
static simde__m128i op_vcuxwfp0 (simde__m128i a, simde__m128i, simde__m128i) { return F(rex_ppc::simde_mm_cvtepu32_ps_(a)); }
static simde__m128i op_vcfpsxws (simde__m128i a, simde__m128i, simde__m128i) { return rex_ppc::simde_mm_vctsxs(P(a)); }
static simde__m128i op_vcfpuxws (simde__m128i a, simde__m128i, simde__m128i) { return rex_ppc::simde_mm_vctuxs(P(a)); }

static simde__m128i op_vperm    (simde__m128i a, simde__m128i b, simde__m128i c) { return rex_ppc::simde_mm_perm_epi8_(a, b, c); }
static simde__m128i op_vsel     (simde__m128i a, simde__m128i b, simde__m128i c) { return simde_mm_blendv_epi8(a, b, c); }
static simde__m128i op_vand     (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_and_si128(a, b); }
static simde__m128i op_vandc    (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_andnot_si128(b, a); }
static simde__m128i op_vor      (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_or_si128(a, b); }
static simde__m128i op_vnor     (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_xor_si128(simde_mm_or_si128(a, b), simde_mm_set1_epi32(-1)); }
static simde__m128i op_vxor     (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_xor_si128(a, b); }
static simde__m128i op_vaddshs  (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_adds_epi16(a, b); }
static simde__m128i op_vaddsws  (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_add_epi32(a, b); }
static simde__m128i op_vsubsws  (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_sub_epi32(a, b); }
static simde__m128i op_vadduwm  (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_add_epi32(a, b); }
static simde__m128i op_vpkshus  (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_packus_epi16(a, b); }
static simde__m128i op_vpkswss  (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_packs_epi32(a, b); }
static simde__m128i op_vsraw    (simde__m128i a, simde__m128i, simde__m128i) { return simde_mm_srai_epi32(a, 5); }
static simde__m128i op_vslw     (simde__m128i a, simde__m128i, simde__m128i) { return simde_mm_slli_epi32(a, 5); }
static simde__m128i op_vsrw     (simde__m128i a, simde__m128i, simde__m128i) { return simde_mm_srli_epi32(a, 5); }
static simde__m128i op_vupkhsb  (simde__m128i a, simde__m128i, simde__m128i) { return simde_mm_cvtepi8_epi16(a); }
static simde__m128i op_vmrghw   (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_unpackhi_epi32(a, b); }
static simde__m128i op_vmrglw   (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_unpacklo_epi32(a, b); }
static simde__m128i op_vspltw   (simde__m128i a, simde__m128i, simde__m128i) { return simde_mm_shuffle_epi32(a, SIMDE_MM_SHUFFLE(2,2,2,2)); }
static simde__m128i op_vsldoi   (simde__m128i a, simde__m128i b, simde__m128i) { return simde_mm_alignr_epi8(a, b, 4); }

// lvx128 / stvx128: the whole-vector BE<->LE reversal.
static simde__m128i op_lvx_swap(simde__m128i a, simde__m128i, simde__m128i) {
  return simde_mm_shuffle_epi8(a, simde_mm_loadu_si128((const simde__m128i*)rex_ppc::VectorMaskL));
}
// lvlx128 at a misalignment of 5 bytes: a mask row with 0xFF zeroing lanes.
static simde__m128i op_lvlx_swap5(simde__m128i a, simde__m128i, simde__m128i) {
  return simde_mm_shuffle_epi8(a, simde_mm_loadu_si128((const simde__m128i*)(rex_ppc::VectorMaskL + 5 * 16)));
}

static const Op OPS[] = {
  {"vaddfp128",    2, op_vaddfp},    {"vsubfp128",    2, op_vsubfp},
  {"vmulfp128",    2, op_vmulfp},    {"vmaddfp",      3, op_vmaddfp},
  {"vnmsubfp",     3, op_vnmsubfp},  {"vmaxfp128",    2, op_vmaxfp},
  {"vminfp128",    2, op_vminfp},    {"vrefp",        1, op_vrefp},
  {"vrsqrtefp",    1, op_vrsqrtefp}, {"vrfiz128",     1, op_vrfiz},
  {"vmsum3fp128",  2, op_vmsum3fp},  {"vmsum4fp128",  2, op_vmsum4fp},
  {"vcmpeqfp128",  2, op_vcmpeqfp},  {"vcmpgefp128",  2, op_vcmpgefp},
  {"vcmpgtfp128",  2, op_vcmpgtfp},  {"vexptefp128",  1, op_vexptefp},
  {"vlogefp128",   1, op_vlogefp},   {"vcsxwfp128_0", 1, op_vcsxwfp0},
  {"vcsxwfp128_15",1, op_vcsxwfp15}, {"vcuxwfp128_0", 1, op_vcuxwfp0},
  {"vcfpsxws128",  1, op_vcfpsxws},  {"vcfpuxws128",  1, op_vcfpuxws},
  {"vperm128",     3, op_vperm},     {"vsel",         3, op_vsel},
  {"vand128",      2, op_vand},      {"vandc128",     2, op_vandc},
  {"vor128",       2, op_vor},       {"vnor128",      2, op_vnor},
  {"vxor128",      2, op_vxor},      {"vaddshs",      2, op_vaddshs},
  {"vaddsws",      2, op_vaddsws},   {"vsubsws",      2, op_vsubsws},
  {"vadduwm",      2, op_vadduwm},   {"vpkshus128",   2, op_vpkshus},
  {"vpkswss128",   2, op_vpkswss},   {"vsraw128",     1, op_vsraw},
  {"vslw128",      1, op_vslw},      {"vsrw128",      1, op_vsrw},
  {"vupkhsb128",   1, op_vupkhsb},   {"vmrghw128",    2, op_vmrghw},
  {"vmrglw128",    2, op_vmrglw},    {"vspltw128",    1, op_vspltw},
  {"vsldoi128",    2, op_vsldoi},   {"lvx128_swap",  1, op_lvx_swap},
  {"lvlx128_swap5",1, op_lvlx_swap5},
};
static const int NOPS = int(sizeof(OPS) / sizeof(OPS[0]));

static void set_ftz(bool on) {
  uint32_t csr = simde_mm_getcsr();
  if (on) csr |= (SIMDE_MM_FLUSH_ZERO_MASK | _MM_DENORMALS_ZERO_MASK);
  else    csr &= ~(SIMDE_MM_FLUSH_ZERO_MASK | _MM_DENORMALS_ZERO_MASK);
  simde_mm_setcsr(csr);
}

int main(int argc, char** argv) {
  const char* vecpath = argc > 1 ? argv[1] : "vectors.bin";
  const char* outpath = argc > 2 ? argv[2] : "cpp_results.bin";

  FILE* f = fopen(vecpath, "rb");
  if (!f) { fprintf(stderr, "cannot open %s\n", vecpath); return 1; }
  uint32_t n = 0;
  if (fread(&n, 4, 1, f) != 1) return 1;
  std::vector<uint32_t> lanes(n);
  if (fread(lanes.data(), 4, n, f) != n) return 1;
  fclose(f);

  const uint32_t nvec = n / 4;
  FILE* o = fopen(outpath, "wb");
  if (!o) { fprintf(stderr, "cannot open %s\n", outpath); return 1; }

  // Manifest so the two sides cannot silently disagree about op order.
  fprintf(stderr, "ops=%d vectors=%u\n", NOPS, nvec);

  for (int ftz = 0; ftz < 2; ftz++) {
    set_ftz(ftz != 0);
    for (int oi = 0; oi < NOPS; oi++) {
      const Op& op = OPS[oi];
      for (uint32_t v = 0; v < nvec; v++) {
        simde__m128i a = simde_mm_loadu_si128((const simde__m128i*)&lanes[((v + 0) % nvec) * 4]);
        simde__m128i b = simde_mm_loadu_si128((const simde__m128i*)&lanes[((v + 1) % nvec) * 4]);
        simde__m128i c = simde_mm_loadu_si128((const simde__m128i*)&lanes[((v + 2) % nvec) * 4]);
        simde__m128i r = op.fn(a, b, c);
        alignas(16) uint32_t out[4];
        simde_mm_store_si128((simde__m128i*)out, r);
        fwrite(out, 4, 4, o);
      }
    }
  }
  set_ftz(false);
  fclose(o);
  return 0;
}
