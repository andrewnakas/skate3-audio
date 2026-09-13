//! VMX128 bit-exactness probe — Rust side (the candidate).
//!
//! Each op is a hand translation of RexGlue's own lowering, which lives in
//! `generated/skate3_recomp.*.cpp` and `rex/ppc/intrinsics.h`. The C++ runner in
//! `../cpp/runner.cpp` holds those lowerings verbatim and defines the reference;
//! this file must reproduce them bit-for-bit over the shared `vectors.bin`.
//!
//! Translation rules being tested (PLAN.md section 5):
//!   * `vmaddfp*` rounds TWICE, as the recomp computes it: it is built without FMA, so SIMDe
//!     falls back to `(a * b) + c` and `-(a * b) + c`, which clang emits as `c - a * b`.
//!     (Corrected 2026-09-13; the probe used to require a fused multiply-add.)
//!   * flush-to-zero is toggled per instruction class, so every op runs under
//!     both MXCSR states.
//!   * the BE<->LE lane mask and the PPC estimate tables port as literal data.

#![allow(clippy::missing_safety_doc)]

use std::arch::x86_64::*;
use std::io::{Read, Write};

// ------------------------------------------------------------------ MXCSR / FTZ
const MM_FLUSH_ZERO_MASK: u32 = 0x8000;
const MM_DENORMALS_ZERO_MASK: u32 = 0x0040;

#[inline]
fn get_mxcsr() -> u32 {
    let mut v: u32 = 0;
    unsafe { std::arch::asm!("stmxcsr [{}]", in(reg) &mut v, options(nostack)) };
    v
}

#[inline]
fn set_mxcsr(v: u32) {
    unsafe { std::arch::asm!("ldmxcsr [{}]", in(reg) &v, options(nostack)) };
}

fn set_ftz(on: bool) {
    let mut csr = get_mxcsr();
    if on {
        csr |= MM_FLUSH_ZERO_MASK | MM_DENORMALS_ZERO_MASK;
    } else {
        csr &= !(MM_FLUSH_ZERO_MASK | MM_DENORMALS_ZERO_MASK);
    }
    set_mxcsr(csr);
}

// ------------------------------------------------------------- RexGlue helpers
/// Port of `rex::ppc::ppc_vrsqrtefp_bits` — the PowerPC reciprocal-square-root
/// estimate, which RexGlue implements as an integer table lookup rather than a
/// hardware estimate instruction. Pure integer code, so it ports literally.
fn ppc_vrsqrtefp_bits(bits: u32) -> u32 {
    const TABLE: [u32; 32] = [
        0x0568B4FD, 0x04F3AF97, 0x048DAAA5, 0x0435A618, 0x03E7A1E4, 0x03A29DFE,
        0x03659A5C, 0x032E96F8, 0x02FC93CA, 0x02D090CE, 0x02A88DFE, 0x02838B57,
        0x026188D4, 0x02438673, 0x02268431, 0x020B820B, 0x03D27FFA, 0x03807C29,
        0x033878AA, 0x02F97572, 0x02C27279, 0x02926FB7, 0x02666D26, 0x023F6AC0,
        0x021D6881, 0x01FD6665, 0x01E16468, 0x01C76287, 0x01AF60C1, 0x01995F12,
        0x01855D79, 0x01735BF4,
    ];
    let sign = bits >> 31;
    let biased_exp = (bits >> 23) & 0xFF;
    let mantissa = bits & 0x007FFFFF;

    if bits == 0xFF80_0000 {
        return 0x7FC0_0000;
    }
    if biased_exp == 0 {
        return if sign != 0 { 0xFF80_0000 } else { 0x7F80_0000 };
    }
    if biased_exp == 0xFF {
        if mantissa == 0 {
            return 0;
        }
        return bits | 0x0040_0000;
    }
    if sign != 0 {
        return 0x7FC0_0000;
    }

    let unbiased_exp = biased_exp as i32 - 127;
    let index = ((((unbiased_exp as u32) << 4) & 16) | (mantissa >> 19)) ^ 16;
    let interp = (mantissa >> 9) & 1023;
    let mut result_exp = (127 - biased_exp as i32) >> 1;
    let entry = TABLE[index as usize];
    let slope = entry >> 16;
    let base = (entry << 10) & 0x03FF_FC00;
    // C++ computes `int32_t(base) - int32_t(interp * slope)`; both operands wrap.
    let mut raw = (base as i32).wrapping_sub(interp.wrapping_mul(slope) as i32);

    if (raw & (1 << 25)) == 0 {
        let val = (raw as u32) & 0x01FF_FFFF;
        let lz = val.leading_zeros() as i32;
        let shift = lz - 6;
        result_exp += 6 - lz;
        // C++ `raw <<= shift` with negative shift is UB but in practice x86 masks
        // the count to 5 bits; reproduce that exactly rather than the abstract rule.
        raw = ((raw as u32) << ((shift as u32) & 31)) as i32;
    }

    if (raw & 5) != 0 && (raw & 2) != 0 {
        raw = raw.wrapping_add(4);
    }

    let mut result =
        ((result_exp << 23).wrapping_add(0x3F80_0000)) as u32 | (((raw as u32) >> 2) & 0x007F_FFFF);
    if ((result >> 23) & 0xFF) == 0 && (result & 0x007F_FFFF) != 0 {
        result = 0;
    }
    result
}

#[target_feature(enable = "sse4.1")]
unsafe fn vrsqrtefp_ps(v: __m128) -> __m128 {
    let mut l = [0f32; 4];
    _mm_storeu_ps(l.as_mut_ptr(), v);
    for x in l.iter_mut() {
        *x = f32::from_bits(ppc_vrsqrtefp_bits(x.to_bits()));
    }
    _mm_loadu_ps(l.as_ptr())
}

/// Port of `rex::ppc::ppc_vmsumfp_result`: overflow-to-QNaN, then guest FTZ.
fn ppc_vmsumfp_result_scalar(value: f32) -> f32 {
    if !value.is_finite() {
        return f32::from_bits(0x7FC0_0000);
    }
    let mut bits = value.to_bits();
    if ((bits >> 23) & 0xFF) == 0 && (bits & 0x007F_FFFF) != 0 {
        bits &= 0x8000_0000;
    }
    f32::from_bits(bits)
}

#[target_feature(enable = "sse4.1")]
unsafe fn ppc_vmsumfp_result(v: __m128) -> __m128 {
    let mut l = [0f32; 4];
    _mm_storeu_ps(l.as_mut_ptr(), v);
    _mm_set1_ps(ppc_vmsumfp_result_scalar(l[0]))
}

#[target_feature(enable = "sse4.1")]
unsafe fn cvtepu32_ps(src1: __m128i) -> __m128 {
    let xmm1 = _mm_add_epi32(src1, _mm_set1_epi32(127));
    let mut xmm0 = _mm_slli_epi32::<{ 31 - 8 }>(src1);
    xmm0 = _mm_srli_epi32::<31>(xmm0);
    xmm0 = _mm_add_epi32(xmm0, xmm1);
    xmm0 = _mm_srai_epi32::<8>(xmm0);
    xmm0 = _mm_add_epi32(xmm0, _mm_set1_epi32(0x4F80_0000u32 as i32));
    let xmm2 = _mm_cvtepi32_ps(src1);
    _mm_blendv_ps(xmm2, _mm_castsi128_ps(xmm0), _mm_castsi128_ps(src1))
}

#[target_feature(enable = "sse4.1")]
unsafe fn perm_epi8(a: __m128i, b: __m128i, c: __m128i) -> __m128i {
    let d = _mm_set1_epi8(0x0F);
    let e = _mm_sub_epi8(d, _mm_and_si128(c, d));
    _mm_blendv_epi8(
        _mm_shuffle_epi8(a, e),
        _mm_shuffle_epi8(b, e),
        _mm_slli_epi32::<3>(c),
    )
}

#[target_feature(enable = "sse4.1")]
unsafe fn vctsxs(src1: __m128) -> __m128i {
    let xmm2 = _mm_cmpunord_ps(src1, src1);
    let xmm0 = _mm_cvttps_epi32(src1);
    let mut xmm1 = _mm_cmpeq_epi32(xmm0, _mm_set1_epi32(i32::MIN));
    xmm1 = _mm_andnot_si128(_mm_castps_si128(src1), xmm1);
    let dest = _mm_blendv_ps(
        _mm_castsi128_ps(xmm0),
        _mm_castsi128_ps(_mm_set1_epi32(i32::MAX)),
        _mm_castsi128_ps(xmm1),
    );
    _mm_andnot_si128(_mm_castps_si128(xmm2), _mm_castps_si128(dest))
}

#[target_feature(enable = "sse4.1")]
unsafe fn vctuxs(src1: __m128) -> __m128i {
    let nan_mask = _mm_cmpunord_ps(src1, src1);
    let neg_mask = _mm_cmplt_ps(src1, _mm_setzero_ps());
    let max_val = _mm_set1_ps(4294967295.0f32);
    let overflow_mask = _mm_cmpge_ps(src1, max_val);
    let mut clamped = _mm_max_ps(src1, _mm_setzero_ps());
    clamped = _mm_min_ps(clamped, max_val);
    let half_range = _mm_set1_ps(2147483648.0f32);
    let high_bit_mask = _mm_cmpge_ps(clamped, half_range);
    let adjusted = _mm_sub_ps(clamped, _mm_and_ps(high_bit_mask, half_range));
    let low_bits = _mm_cvttps_epi32(adjusted);
    let high_bit = _mm_and_si128(
        _mm_castps_si128(high_bit_mask),
        _mm_set1_epi32(0x8000_0000u32 as i32),
    );
    let mut result = _mm_or_si128(low_bits, high_bit);
    result = _mm_andnot_si128(_mm_castps_si128(nan_mask), result);
    result = _mm_andnot_si128(_mm_castps_si128(neg_mask), result);
    result = _mm_or_si128(
        _mm_andnot_si128(_mm_castps_si128(overflow_mask), result),
        _mm_and_si128(_mm_castps_si128(overflow_mask), _mm_set1_epi32(-1)),
    );
    result
}

/// The BE<->LE lane-reversal mask RexGlue applies on every vector load and store.
/// Row 0 is the plain byte reversal used by lvx128/stvx128; later rows serve the
/// misaligned lvlx/lvrx/stvlx/stvrx forms. Ports as literal data.
static VECTOR_MASK_L: [u8; 128] = [
    0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0x00,
    0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01,
    0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02,
    0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03,
    0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05, 0x04,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06, 0x05,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07, 0x06,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F, 0x0E, 0x0D, 0x0C, 0x0B, 0x0A, 0x09, 0x08, 0x07,
];

// ------------------------------------------------------------------- op table
type OpFn = unsafe fn(__m128i, __m128i, __m128i) -> __m128i;

#[inline(always)]
unsafe fn p(x: __m128i) -> __m128 {
    _mm_castsi128_ps(x)
}
#[inline(always)]
unsafe fn f(x: __m128) -> __m128i {
    _mm_castps_si128(x)
}

macro_rules! ops {
    ($($name:literal => $fn:ident),* $(,)?) => {
        static OPS: &[(&str, OpFn)] = &[$(($name, $fn as OpFn)),*];
    };
}

#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vaddfp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(_mm_add_ps(p(a), p(b))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vsubfp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(_mm_sub_ps(p(a), p(b))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vmulfp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(_mm_mul_ps(p(a), p(b))) }
// vmaddfp: two roundings, the product first (see the header).
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vmaddfp(a: __m128i, b: __m128i, c: __m128i) -> __m128i { f(_mm_add_ps(_mm_mul_ps(p(a), p(b)), p(c))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vnmsubfp(a: __m128i, b: __m128i, c: __m128i) -> __m128i { f(_mm_sub_ps(p(c), _mm_mul_ps(p(a), p(b)))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vmaxfp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(_mm_max_ps(p(a), p(b))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vminfp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(_mm_min_ps(p(a), p(b))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vrefp(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { f(_mm_div_ps(_mm_set1_ps(1.0), p(a))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vrsqrtefp(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { f(vrsqrtefp_ps(p(a))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vrfiz(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { f(_mm_round_ps::<{ _MM_FROUND_TO_ZERO | _MM_FROUND_NO_EXC }>(p(a))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vmsum3fp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(ppc_vmsumfp_result(_mm_dp_ps::<0xEF>(p(a), p(b)))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vmsum4fp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(ppc_vmsumfp_result(_mm_dp_ps::<0xFF>(p(a), p(b)))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vcmpeqfp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(_mm_cmpeq_ps(p(a), p(b))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vcmpgefp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(_mm_cmpge_ps(p(a), p(b))) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vcmpgtfp(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { f(_mm_cmpgt_ps(p(a), p(b))) }

// vexptefp128 / vlogefp128 lower to scalar libm per lane. This is the one place the
// two languages might not share an implementation; that is exactly what we measure.
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vexptefp(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i {
    let mut l = [0f32; 4];
    _mm_storeu_ps(l.as_mut_ptr(), p(a));
    for x in l.iter_mut() { *x = x.exp2(); }
    f(_mm_loadu_ps(l.as_ptr()))
}
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vlogefp(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i {
    let mut l = [0f32; 4];
    _mm_storeu_ps(l.as_mut_ptr(), p(a));
    for x in l.iter_mut() { *x = x.log2(); }
    f(_mm_loadu_ps(l.as_ptr()))
}

#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vcsxwfp0(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { f(_mm_cvtepi32_ps(a)) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vcsxwfp15(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i {
    f(_mm_mul_ps(_mm_cvtepi32_ps(a), p(_mm_set1_epi32(0x3800_0000u32 as i32))))
}
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vcuxwfp0(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { f(cvtepu32_ps(a)) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vcfpsxws(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { vctsxs(p(a)) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vcfpuxws(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { vctuxs(p(a)) }

#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vperm(a: __m128i, b: __m128i, c: __m128i) -> __m128i { perm_epi8(a, b, c) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vsel(a: __m128i, b: __m128i, c: __m128i) -> __m128i { _mm_blendv_epi8(a, b, c) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vand(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_and_si128(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vandc(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_andnot_si128(b, a) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vor(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_or_si128(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vnor(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_xor_si128(_mm_or_si128(a, b), _mm_set1_epi32(-1)) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vxor(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_xor_si128(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vaddshs(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_adds_epi16(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vaddsws(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_add_epi32(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vsubsws(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_sub_epi32(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vadduwm(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_add_epi32(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vpkshus(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_packus_epi16(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vpkswss(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_packs_epi32(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vsraw(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { _mm_srai_epi32::<5>(a) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vslw(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { _mm_slli_epi32::<5>(a) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vsrw(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { _mm_srli_epi32::<5>(a) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vupkhsb(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { _mm_cvtepi8_epi16(a) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vmrghw(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_unpackhi_epi32(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vmrglw(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_unpacklo_epi32(a, b) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vspltw(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i { _mm_shuffle_epi32::<0b10_10_10_10>(a) }
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_vsldoi(a: __m128i, b: __m128i, _c: __m128i) -> __m128i { _mm_alignr_epi8::<4>(a, b) }

#[target_feature(enable = "sse4.1,fma")] unsafe fn o_lvx_swap(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i {
    _mm_shuffle_epi8(a, _mm_loadu_si128(VECTOR_MASK_L.as_ptr() as *const __m128i))
}
#[target_feature(enable = "sse4.1,fma")] unsafe fn o_lvlx_swap5(a: __m128i, _b: __m128i, _c: __m128i) -> __m128i {
    _mm_shuffle_epi8(a, _mm_loadu_si128(VECTOR_MASK_L.as_ptr().add(5 * 16) as *const __m128i))
}

ops! {
    "vaddfp128"     => o_vaddfp,    "vsubfp128"     => o_vsubfp,
    "vmulfp128"     => o_vmulfp,    "vmaddfp"       => o_vmaddfp,
    "vnmsubfp"      => o_vnmsubfp,  "vmaxfp128"     => o_vmaxfp,
    "vminfp128"     => o_vminfp,    "vrefp"         => o_vrefp,
    "vrsqrtefp"     => o_vrsqrtefp, "vrfiz128"      => o_vrfiz,
    "vmsum3fp128"   => o_vmsum3fp,  "vmsum4fp128"   => o_vmsum4fp,
    "vcmpeqfp128"   => o_vcmpeqfp,  "vcmpgefp128"   => o_vcmpgefp,
    "vcmpgtfp128"   => o_vcmpgtfp,  "vexptefp128"   => o_vexptefp,
    "vlogefp128"    => o_vlogefp,   "vcsxwfp128_0"  => o_vcsxwfp0,
    "vcsxwfp128_15" => o_vcsxwfp15, "vcuxwfp128_0"  => o_vcuxwfp0,
    "vcfpsxws128"   => o_vcfpsxws,  "vcfpuxws128"   => o_vcfpuxws,
    "vperm128"      => o_vperm,     "vsel"          => o_vsel,
    "vand128"       => o_vand,      "vandc128"      => o_vandc,
    "vor128"        => o_vor,       "vnor128"       => o_vnor,
    "vxor128"       => o_vxor,      "vaddshs"       => o_vaddshs,
    "vaddsws"       => o_vaddsws,   "vsubsws"       => o_vsubsws,
    "vadduwm"       => o_vadduwm,   "vpkshus128"    => o_vpkshus,
    "vpkswss128"    => o_vpkswss,   "vsraw128"      => o_vsraw,
    "vslw128"       => o_vslw,      "vsrw128"       => o_vsrw,
    "vupkhsb128"    => o_vupkhsb,   "vmrghw128"     => o_vmrghw,
    "vmrglw128"     => o_vmrglw,    "vspltw128"     => o_vspltw,
    "vsldoi128"     => o_vsldoi,   "lvx128_swap"   => o_lvx_swap,
    "lvlx128_swap5" => o_lvlx_swap5,
}

fn main() -> std::io::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let vecpath = args.get(1).map(String::as_str).unwrap_or("vectors.bin");
    let outpath = args.get(2).map(String::as_str).unwrap_or("rust_results.bin");

    let mut raw = Vec::new();
    std::fs::File::open(vecpath)?.read_to_end(&mut raw)?;
    let n = u32::from_le_bytes(raw[0..4].try_into().unwrap()) as usize;
    let lanes: Vec<u32> = (0..n)
        .map(|i| u32::from_le_bytes(raw[4 + i * 4..8 + i * 4].try_into().unwrap()))
        .collect();
    let nvec = n / 4;

    eprintln!("ops={} vectors={}", OPS.len(), nvec);

    let mut out = Vec::with_capacity(OPS.len() * nvec * 16 * 2);
    for ftz in 0..2 {
        set_ftz(ftz != 0);
        for (_name, opfn) in OPS.iter() {
            for v in 0..nvec {
                unsafe {
                    let a = _mm_loadu_si128(lanes.as_ptr().add(((v + 0) % nvec) * 4) as *const __m128i);
                    let b = _mm_loadu_si128(lanes.as_ptr().add(((v + 1) % nvec) * 4) as *const __m128i);
                    let c = _mm_loadu_si128(lanes.as_ptr().add(((v + 2) % nvec) * 4) as *const __m128i);
                    let r = opfn(a, b, c);
                    let mut o = [0u32; 4];
                    _mm_storeu_si128(o.as_mut_ptr() as *mut __m128i, r);
                    for w in o {
                        out.extend_from_slice(&w.to_le_bytes());
                    }
                }
            }
        }
    }
    set_ftz(false);
    std::fs::File::create(outpath)?.write_all(&out)?;
    Ok(())
}
