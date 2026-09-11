//! EA `.mus` interactive-music streams.
//!
//! Structurally distinct from the block-chained `.sns` / `.dat` payloads: the length
//! field lives in a **12-byte block header** rather than inline before each chunk, and
//! blocks are grouped into segments that a companion `.mpf` sequences at runtime.
//!
//! ```text
//! block   [u32 flags<<24 | size]   size COUNTS the 12-byte header
//!         [u32 num_samples]
//!         [u32 length_field]       same encoding as eaac::chunk_length
//!         [body ...]
//! ```
//!
//! Flag bit `0x80` marks the last block of a segment. That block is padded out to an
//! alignment boundary, so its body is longer than its declared length.
//!
//! Note the file's segment count at offset 4 is **little-endian** while everything else
//! in the format is big-endian.

use crate::{be32, eaac, Error, Result};

/// Byte size of a block header.
pub const HEADER_SIZE: usize = 12;
/// Flag in the top byte of the size word marking a segment's final block.
pub const FLAG_SEGMENT_END: u32 = 0x80;

/// One block of a music segment.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Block {
    pub offset: usize,
    /// Stride to the next block, including this header.
    pub size: u32,
    pub flags: u8,
    pub num_samples: u32,
    /// Declared payload length; never larger than `size - HEADER_SIZE`.
    pub data_len: u32,
}

impl Block {
    pub fn is_segment_end(&self) -> bool {
        u32::from(self.flags) & FLAG_SEGMENT_END != 0
    }

    /// Byte range of the decodable payload, excluding any alignment padding.
    pub fn data_range(&self) -> std::ops::Range<usize> {
        let start = self.offset + HEADER_SIZE;
        start..start + self.data_len as usize
    }

    pub fn parse(data: &[u8], at: usize) -> Result<Self> {
        let word = be32(data, at)?;
        let size = word & 0x00FF_FFFF;
        if (size as usize) <= HEADER_SIZE {
            return Err(Error::new(at, format!("block size {size} does not advance")));
        }
        if at + size as usize > data.len() {
            return Err(Error::new(at, format!("block size {size} runs past end")));
        }
        let field = be32(data, at + 8)?;
        let data_len = eaac::chunk_length(field)
            .ok_or_else(|| Error::new(at + 8, format!("field {field} is not a valid length")))?;
        let body = size - HEADER_SIZE as u32;
        if data_len > body {
            return Err(Error::new(
                at + 8,
                format!("declared length {data_len} exceeds body {body}"),
            ));
        }
        Ok(Self {
            offset: at,
            size,
            flags: (word >> 24) as u8,
            num_samples: be32(data, at + 4)?,
            data_len,
        })
    }
}

/// A run of blocks ending at a `FLAG_SEGMENT_END`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Segment {
    pub blocks: Vec<Block>,
}

impl Segment {
    pub fn num_samples(&self) -> u64 {
        self.blocks.iter().map(|b| u64::from(b.num_samples)).sum()
    }

    /// Offset just past the final block, before any inter-segment padding.
    pub fn end(&self) -> usize {
        self.blocks.last().map_or(0, |b| b.offset + b.size as usize)
    }
}

/// Read one segment starting at `at`.
pub fn segment(data: &[u8], at: usize) -> Result<Segment> {
    let mut blocks = Vec::new();
    let mut pos = at;
    loop {
        let block = Block::parse(data, pos)?;
        pos += block.size as usize;
        let last = block.is_segment_end();
        blocks.push(block);
        if last {
            return Ok(Segment { blocks });
        }
        if blocks.len() > 4096 {
            return Err(Error::new(at, "no segment-end flag within 4096 blocks"));
        }
    }
}

/// Find the next block header at or after `from`, stepping over inter-segment padding.
///
/// Segments are separated by alignment padding whose width varies, so the next segment
/// has to be located rather than computed.
pub fn next_segment_start(data: &[u8], from: usize, limit: usize) -> Option<usize> {
    let mut at = from;
    while at + HEADER_SIZE <= data.len() && at < from + limit {
        if Block::parse(data, at).is_ok() && be32(data, at + 4).is_ok_and(|n| n > 0 && n <= 8192) {
            return Some(at);
        }
        at += 4;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn block(size: u32, samples: u32, len: u32, flags: u8) -> Vec<u8> {
        let mut v = ((u32::from(flags) << 24) | size).to_be_bytes().to_vec();
        v.extend_from_slice(&samples.to_be_bytes());
        v.extend_from_slice(&(4 * len + eaac::LENGTH_BIAS).to_be_bytes());
        v.resize(size as usize, 0);
        v
    }

    #[test]
    fn parses_a_block_header() {
        let raw = block(2043, 4736, 2031, 0);
        let b = Block::parse(&raw, 0).unwrap();
        assert_eq!(b.size, 2043);
        assert_eq!(b.num_samples, 4736);
        assert_eq!(b.data_len, 2031);
        assert!(!b.is_segment_end());
        assert_eq!(b.data_range(), 12..2043);
    }

    #[test]
    fn honours_the_segment_end_flag() {
        let raw = block(1971, 4384, 1911, 0x80);
        let b = Block::parse(&raw, 0).unwrap();
        assert!(b.is_segment_end());
        // the final block is padded: body is 1959 but only 1911 bytes are data
        assert_eq!(b.data_len, 1911);
        assert_eq!(b.size as usize - HEADER_SIZE, 1959);
    }

    #[test]
    fn rejects_a_length_longer_than_the_body() {
        let raw = block(100, 512, 4000, 0);
        assert!(Block::parse(&raw, 0).is_err());
    }

    #[test]
    fn walks_a_segment_to_its_flag() {
        let mut raw = block(60, 512, 40, 0);
        raw.extend(block(60, 512, 40, 0));
        raw.extend(block(60, 256, 40, 0x80));
        let seg = segment(&raw, 0).unwrap();
        assert_eq!(seg.blocks.len(), 3);
        assert_eq!(seg.num_samples(), 1280);
        assert_eq!(seg.end(), 180);
    }
}
