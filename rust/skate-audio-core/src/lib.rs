//! Skate 3 audio graph, ported from the shadow-verified native C++.
//!
//! Source: `skate3recomp-dev/src/skate3_audio_native.cpp`, each function of which was
//! checked against the original recompiled body under the shadow harness before being
//! translated here. Offsets come from `docs/rw_audio_structs.h` and are asserted below the
//! way `docs/rw_audio_structs_check.c` asserts them in C.
//!
//! Everything here operates on **guest memory**: big-endian, byte-addressed, at guest
//! addresses. That is deliberate rather than idiomatic. These are recovered layouts with
//! asserted offsets, and Phase 4's per-function criterion compares *bytes* against the
//! verified C++ — so a byte-addressed view makes that comparison direct, instead of routing
//! it through a serialisation step that could hide a discrepancy of its own.
//!
//! Unsafe is not forbidden crate-wide the way it is in `skate-audio-formats`, because the
//! DSP modules will scope `unsafe` to intrinsic calls. Nothing in this file needs it.

pub mod player;
pub mod system;

/// A guest memory window. Addresses are guest addresses; `base` is the address `mem[0]`
/// corresponds to.
pub struct Guest<'a> {
    pub mem: &'a mut [u8],
    pub base: u32,
}

/// Out-of-window access, reported rather than panicking silently.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Error {
    pub address: u32,
    pub message: String,
}

impl Error {
    pub fn new(address: u32, message: impl Into<String>) -> Self {
        Self { address, message: message.into() }
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "at {:#010x}: {}", self.address, self.message)
    }
}

impl std::error::Error for Error {}

pub type Result<T> = std::result::Result<T, Error>;

impl<'a> Guest<'a> {
    pub fn new(mem: &'a mut [u8], base: u32) -> Self {
        Self { mem, base }
    }

    fn at(&self, ea: u32, len: usize) -> Result<usize> {
        let off = ea
            .checked_sub(self.base)
            .ok_or_else(|| Error::new(ea, "below the window base"))? as usize;
        if off + len > self.mem.len() {
            return Err(Error::new(ea, "past the end of the window"));
        }
        Ok(off)
    }

    pub fn u32(&self, ea: u32) -> Result<u32> {
        let o = self.at(ea, 4)?;
        Ok(u32::from_be_bytes([self.mem[o], self.mem[o + 1], self.mem[o + 2], self.mem[o + 3]]))
    }

    pub fn set_u32(&mut self, ea: u32, value: u32) -> Result<()> {
        let o = self.at(ea, 4)?;
        self.mem[o..o + 4].copy_from_slice(&value.to_be_bytes());
        Ok(())
    }

    pub fn u8(&self, ea: u32) -> Result<u8> {
        let o = self.at(ea, 1)?;
        Ok(self.mem[o])
    }

    pub fn set_u8(&mut self, ea: u32, value: u8) -> Result<()> {
        let o = self.at(ea, 1)?;
        self.mem[o] = value;
        Ok(())
    }

    /// `f32` from the guest's big-endian bits, without touching the value.
    pub fn f32(&self, ea: u32) -> Result<f32> {
        Ok(f32::from_bits(self.u32(ea)?))
    }

    pub fn fill(&mut self, ea: u32, value: u8, len: u32) -> Result<()> {
        let o = self.at(ea, len as usize)?;
        self.mem[o..o + len as usize].fill(value);
        Ok(())
    }
}

#[cfg(test)]
pub(crate) mod testutil {
    use super::Guest;

    /// Guest addresses used by the tests. The window is flat, so everything lives inside it.
    pub const BASE: u32 = 0x4000_0000;
    pub const SYSTEM: u32 = 0x4000_0000;
    pub const RING: u32 = 0x4000_0200;
    pub const PLAYER: u32 = 0x4000_0400;
    pub const PACKET_A: u32 = 0x4000_0600;
    pub const PACKET_B: u32 = 0x4000_0620;
    pub const PARAMS: u32 = 0x4000_0700;
    pub const SOURCE: u32 = 0x4000_0740;

    pub fn window() -> Vec<u8> {
        vec![0u8; 0x800]
    }

    /// A player wired to a system with an empty ring, and a source object.
    pub fn wire(g: &mut Guest<'_>) {
        g.set_u32(PLAYER + crate::system::PLAYER_SYSTEM, SYSTEM).unwrap();
        g.set_u32(SYSTEM + crate::system::SYSTEM_CMD_BUFFER, RING).unwrap();
        g.set_u32(SYSTEM + crate::system::SYSTEM_CMD_WRITE_OFF, 0).unwrap();
        g.set_u32(PLAYER + crate::player::PLAYER_SOURCE, SOURCE).unwrap();
    }
}
