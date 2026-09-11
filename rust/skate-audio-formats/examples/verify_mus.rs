//! Walk real `.mus` segments and check them against the file's own SNR table.
//!
//! The SNR table states each segment's sample count independently of the block headers,
//! so agreement between the two is a real check rather than a self-consistency one.
//!
//!     cargo run --example verify_mus -- <file.mus> <snr-table-offset> <segments>

use skate_audio_formats::mus;

fn be32(d: &[u8], o: usize) -> u32 {
    u32::from_be_bytes([d[o], d[o + 1], d[o + 2], d[o + 3]])
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let path = args.next().ok_or("usage: verify_mus <file.mus> <snr-offset> <segments>")?;
    let snr: usize = args.next().ok_or("need SNR table offset")?.parse()?;
    let want: usize = args.next().unwrap_or_else(|| "8".into()).parse()?;
    let data = std::fs::read(&path)?;

    let count = u32::from_le_bytes([data[4], data[5], data[6], data[7]]);
    println!("{path}\n  segments declared (little-endian): {count}");

    // Audio begins after the SNR table, past its alignment padding.
    let mut at = mus::next_segment_start(&data, snr + 16 * count as usize, 0x4000)
        .ok_or("could not locate the first block header")?;
    println!("  first block header at {at:#x}");

    let (mut ok, mut bad) = (0usize, 0usize);
    for i in 0..want {
        let seg = match mus::segment(&data, at) {
            Ok(s) => s,
            Err(e) => {
                println!("  segment {i}: walk failed: {e}");
                bad += 1;
                break;
            }
        };
        let declared = be32(&data, snr + 16 * i + 4) & 0x1FFF_FFFF;
        let walked = seg.num_samples();
        let agree = u64::from(declared) == walked;
        if agree { ok += 1 } else { bad += 1 }
        if i < 4 || !agree {
            println!(
                "  segment {i}: {:3} blocks  walked {walked:6}  SNR says {declared:6}  {}",
                seg.blocks.len(),
                if agree { "match" } else { "MISMATCH" }
            );
        }
        match mus::next_segment_start(&data, seg.end(), 0x1000) {
            Some(n) => at = n,
            None => {
                println!("  segment {i}: no following segment found");
                break;
            }
        }
    }
    println!("  segments matching the SNR table: {ok}, failing: {bad}");
    Ok(())
}
