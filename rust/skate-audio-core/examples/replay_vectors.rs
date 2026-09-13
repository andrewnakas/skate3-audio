//! Phase 4 tier 1: replay the shadow harness's recorded vectors against the Rust port.
//!
//! Usage: replay_vectors VECTORS.tsv [voice_live_hex voice_gone_hex]
//!
//! The vectors come from real gameplay, recorded by `skate3_audio_shadow.cpp` when
//! `skate3_audio_vectors_path` is set: the entry registers, the watched windows, the bytes on
//! entry, and the bytes the **original lifted body** produced. This feeds the identical inputs
//! to the Rust port and compares byte for byte, which is what tier 1 asks for — with real
//! inputs rather than generated ones.
//!
//! Two limits are reported rather than hidden. Functions with no Rust port yet are **skipped
//! and counted**; a pass rate with an invisible skip count reads as verification. And the
//! producer's query path writes a constant read from guest `.rdata`, which no recorded window
//! contains, so those vectors compare only the NaN sentinel unless the two constants are passed
//! on the command line. Deriving them from the expected bytes would be using the answer to
//! check the answer.

use skate_audio_core::{Guest, buffers, cursors, dsp, player, scheduler, system};

struct Vector {
    name: String,
    run: u64,
    r3: u32,
    r4: u32,
    r5: u32,
    r6: u32,
    r7: u32,
    ret_r3: u32,
    /// Entry `f1`..`f4` as raw bit patterns. A DSP kernel's scale factor arrives in `f1`, so
    /// without these its memory and integer registers record a call that cannot be replayed.
    f: [u64; 4],
    /// The read set: memory the function saw but does not write.
    inputs: Vec<(u32, Vec<u8>)>,
    /// The write set: entry bytes, and what the original lifted body produced.
    windows: Vec<(u32, Vec<u8>, Vec<u8>)>,
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len() / 2).map(|i| u8::from_str_radix(&s[i * 2..i * 2 + 2], 16).unwrap()).collect()
}

fn parse(line: &str) -> Option<Vector> {
    let f: Vec<&str> = line.split('\t').collect();
    if f.len() < 9 {
        return None;
    }
    let hex = |s: &str| u32::from_str_radix(s, 16).unwrap_or(0);
    let mut inputs = Vec::new();
    let mut windows = Vec::new();
    let mut fprs = [0u64; 4];
    for tok in &f[8..] {
        let p: Vec<&str> = tok.split(':').collect();
        match (p.first(), p.len()) {
            (Some(&"I"), 4) => inputs.push((hex(p[1]), unhex(p[3]))),
            (Some(&"W"), 5) => windows.push((hex(p[1]), unhex(p[3]), unhex(p[4]))),
            // Vectors recorded before the float columns existed simply have none, and every
            // function that needs one fails loudly rather than replaying against a zero.
            (Some(&"F"), 3) => {
                if let (Ok(i), Ok(bits)) = (p[1].parse::<usize>(), u64::from_str_radix(p[2], 16)) {
                    if (1..=4).contains(&i) {
                        fprs[i - 1] = bits;
                    }
                }
            }
            _ => {}
        }
    }
    if windows.is_empty() {
        return None; // a vector with no write set compares nothing; counted as malformed
    }
    Some(Vector {
        f: fprs,
        name: f[0].to_string(),
        run: f[1].parse().unwrap_or(0),
        r3: hex(f[2]),
        r4: hex(f[3]),
        r5: hex(f[4]),
        r6: hex(f[5]),
        r7: hex(f[6]),
        ret_r3: hex(f[7]),
        inputs,
        windows,
    })
}

/// Build guest memory holding exactly what was recorded, as the function saw it **on entry**.
///
/// Nothing is invented. An address the function reaches that was not recorded stays uncovered
/// and the vector is reported `unreplayable`, never zero-filled: feeding the port fabricated
/// inputs would turn a failure into a meaningless pass.
///
/// Two things this has to get right, both found by replaying the scheduler and cursor vectors:
///
/// **The `W:` entry bytes are authoritative wherever they overlap an `I:` span.** The recorder
/// snapshots the read set *after* the original body has run, so any cell that is both read and
/// written is recorded holding the post-call value. That is not a guess: across
/// `sched_cursors.tsv` there are 4,454 bytes covered by both an `I:` span and a `W:` span whose
/// entry and expected bytes differ, and in **4,454 of 4,454** the `I:` byte equals the
/// *expected* byte and in none of them the *entry* byte. The `W:` entry column is the only
/// record of true entry state for those cells, so it is laid down last and wins.
///
/// **Spans are merged byte-wise, not stored one segment each.** Overlap is common — a window
/// often sits inside a larger read span, and sometimes shares its base — and a whole-segment
/// model resolves it by whichever segment `Guest::locate` happens to reach first, which is
/// insertion order. That silently fed `sub_82B489D0` a bucket byte from the read set while its
/// own store landed in the window segment the comparison then read, and it truncated
/// `sub_82B39690`'s 16-byte node span to the 8 bytes of a window sharing its base, losing the
/// `which` byte four bytes past the end. Merging into one map and coalescing runs of adjacent
/// recorded bytes removes both, without covering a single byte that was not recorded.
fn guest_of(v: &Vector) -> Guest {
    let mut cells: std::collections::BTreeMap<u32, u8> = Default::default();
    for (addr, bytes) in &v.inputs {
        for (i, b) in bytes.iter().enumerate() {
            cells.insert(addr.wrapping_add(i as u32), *b);
        }
    }
    // Laid down second, so the entry bytes overwrite the read set's post-call copy.
    for (addr, entry, _) in &v.windows {
        for (i, b) in entry.iter().enumerate() {
            cells.insert(addr.wrapping_add(i as u32), *b);
        }
    }

    let mut g = Guest::default();
    let mut run: Vec<u8> = Vec::new();
    let mut base = 0u32;
    let mut last = 0u32;
    for (addr, byte) in cells {
        if !run.is_empty() && addr == last.wrapping_add(1) && addr != 0 {
            run.push(byte);
        } else {
            if !run.is_empty() {
                g.put(base, std::mem::take(&mut run));
            }
            base = addr;
            run.push(byte);
        }
        last = addr;
    }
    if !run.is_empty() {
        g.put(base, run);
    }
    g
}

#[derive(Default)]
struct Tally {
    passed: u64,
    failed: u64,
    partial: u64,
    skipped: u64,
    /// The vector lacked memory the function needed — a gap in the recording, not a
    /// disagreement. Kept apart from `failed` so neither is mistaken for the other.
    unreplayable: u64,
    first_failure: Option<String>,
    first_gap: Option<String>,
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: replay_vectors VECTORS.tsv [voice_live_hex voice_gone_hex]");
        std::process::exit(2);
    }
    let consts = if args.len() >= 4 {
        Some(system::Constants {
            voice_live_bits: u32::from_str_radix(args[2].trim_start_matches("0x"), 16).unwrap(),
            voice_gone_bits: u32::from_str_radix(args[3].trim_start_matches("0x"), 16).unwrap(),
        })
    } else {
        None
    };

    let text = std::fs::read_to_string(&args[1]).expect("cannot read vectors");
    let mut by_name: std::collections::BTreeMap<String, Tally> = Default::default();
    let mut total = 0u64;

    for line in text.lines().filter(|l| !l.starts_with('#') && !l.trim().is_empty()) {
        let Some(v) = parse(line) else { continue };
        total += 1;
        let t = by_name.entry(v.name.clone()).or_default();
        let mut g = guest_of(&v);

        // Dispatch. A name with no Rust port is skipped and counted, never dropped.
        let outcome: std::result::Result<Option<u32>, String> = match v.name.as_str() {
            "BUFPAIR" => buffers::init_buffer_pair(&mut g, v.r3, v.r4, v.r5, v.r6, v.r7)
                .map(Some)
                .map_err(|e| e.to_string()),
            "EVENT_SUBMIT" => player::event_submit(&mut g, v.r3).map(Some).map_err(|e| e.to_string()),
            "EVENT_PLAY" => {
                let mut restarted = 0u32;
                player::event_play(&mut g, v.r3, Some(&mut |_| restarted += 1))
                    .map(Some)
                    .map_err(|e| e.to_string())
                    .and_then(|r| {
                        if restarted > 0 {
                            Err("the restart branch fired, which no observed call does".into())
                        } else {
                            Ok(r)
                        }
                    })
            }
            "ENQUEUE" => {
                let c = consts.unwrap_or(system::Constants {
                    voice_live_bits: 0,
                    voice_gone_bits: 0,
                });
                if v.r4 > 2 && consts.is_none() {
                    t.partial += 1;
                }
                system::enqueue(&mut g, v.r3, v.r4, v.r5, &c)
                    .map(|_| None)
                    .map_err(|e| e.to_string())
            }
            // The scheduler and cursor ports, addressed by their guest names. Each argument's
            // register is the one its module doc states; getting one wrong would not fail
            // gracefully, it would compare a different call.
            "sub_82B32550" => cursors::claim_ring_slot(&mut g, v.r3, v.r4)
                .map(|r| Some(r as u32))
                .map_err(|e| e.to_string()),
            "sub_82B349A8" => cursors::advance_ring_cursor(&mut g, v.r3)
                .map(|_| None)
                .map_err(|e| e.to_string()),
            "sub_82B3C9D8" => cursors::advance_segment_position(&mut g, v.r3, v.r4)
                .map(|_| None)
                .map_err(|e| e.to_string()),
            "sub_82B39690" => scheduler::recycle_node(&mut g, v.r3, v.r4)
                .map(|_| None)
                .map_err(|e| e.to_string()),
            "sub_82B489D0" => scheduler::detach_instance(&mut g, u64::from(v.r3), v.r4)
                .map(|r| Some(r as u32))
                .map_err(|e| e.to_string()),
            // The DSP kernels. `count` is r6, not r5, and the scale arrives in f1 -- both
            // straight from the module docs, both easy to get wrong in a way that still runs.
            "sub_82B3BED8" => dsp::scale::scale(&mut g, v.r3, v.r4, v.r6, f64::from_bits(v.f[0]))
                .map(|_| None)
                .map_err(|e| e.to_string()),
            "sub_82B44B20" => {
                dsp::scale::scale_accumulate(&mut g, v.r3, v.r4, v.r6, f64::from_bits(v.f[0]))
                    .map(|_| None)
                    .map_err(|e| e.to_string())
            }
            "sub_82B3C098" => dsp::gain_ramp::gain_ramp_copy(
                &mut g, v.r3, v.r4, f64::from_bits(v.f[0]), f64::from_bits(v.f[1]))
                .map(|_| None)
                .map_err(|e| e.to_string()),
            _ => {
                t.skipped += 1;
                continue;
            }
        };

        match outcome {
            Err(why) => {
                if why.contains("no segment covers") {
                    t.unreplayable += 1;
                    if t.first_gap.is_none() {
                        t.first_gap = Some(format!("run {}: {}", v.run, why));
                    }
                } else {
                    t.failed += 1;
                    if t.first_failure.is_none() {
                        t.first_failure = Some(format!("run {}: {}", v.run, why));
                    }
                }
            }
            Ok(ret) => {
                let mut bad = None;
                // The query path's constant word is unverifiable without the .rdata values.
                let skip_constant = v.name == "ENQUEUE" && v.r4 > 2 && consts.is_none();
                for (addr, _, expected) in &v.windows {
                    let got = g.span(*addr, expected.len()).expect("window vanished");
                    for i in 0..expected.len() {
                        if got[i] != expected[i] {
                            if skip_constant && (4..8).contains(&i) {
                                continue; // params+0xC, the .rdata constant
                            }
                            bad = Some(format!(
                                "run {}: {:08X}+{} expected {:02X}, got {:02X}",
                                v.run, addr, i, expected[i], got[i]
                            ));
                            break;
                        }
                    }
                    if bad.is_some() {
                        break;
                    }
                }
                if bad.is_none() {
                    if let Some(r) = ret {
                        if r != v.ret_r3 {
                            bad = Some(format!(
                                "run {}: returned {:08X}, expected {:08X}",
                                v.run, r, v.ret_r3
                            ));
                        }
                    }
                }
                match bad {
                    None => t.passed += 1,
                    Some(why) => {
                        t.failed += 1;
                        if t.first_failure.is_none() {
                            t.first_failure = Some(why);
                        }
                    }
                }
            }
        }
    }

    println!("replayed {total} recorded vectors\n");
    let mut any_failed = false;
    for (name, t) in &by_name {
        print!(
            "  {name:<13} pass={:<6} fail={:<5} skip={:<4} unreplayable={:<5}",
            t.passed, t.failed, t.skipped, t.unreplayable
        );
        if t.partial > 0 {
            print!(" partial={} (.rdata constant not supplied)", t.partial);
        }
        println!();
        if let Some(f) = &t.first_failure {
            println!("      first DISAGREEMENT: {f}");
            any_failed = true;
        }
        if let Some(gp) = &t.first_gap {
            println!("      first recording gap: {gp}");
        }
    }
    let skipped: u64 = by_name.values().map(|t| t.skipped).sum();
    if skipped > 0 {
        println!("\n  {skipped} vectors skipped: no Rust port for that function yet.");
    }
    let gaps: u64 = by_name.values().map(|t| t.unreplayable).sum();
    if gaps > 0 {
        println!(
            "  {gaps} vectors unreplayable: the recording lacks memory the function reached.\n  \
             A fixed read set cannot capture a linked-list walk, so this is expected for the\n  \
             producer's query path whenever the FIFO is non-empty."
        );
    }
    if any_failed {
        std::process::exit(1);
    }
}
