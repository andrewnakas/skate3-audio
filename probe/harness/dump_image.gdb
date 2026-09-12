# Dump the decrypted guest image out of a running recomp.
#
# default.xex is XEX2 with compressed .rdata, so no external string or constant search can
# find a container magic: zero hits for "PFDx" in every image on disk, and zero for the
# 0x50464478 immediate across all 47,889 lifted functions. The decrypted image exists only in
# the running process at virtual_membase + 0x82000000.
#
# ptrace_scope is 1 here, so an external attach is refused and gdb must be the parent, which
# run_session.sh's GDB_SCRIPT path already arranges.
#
# The membase is READ, not assumed. Every lifted function is
# void sub_X(PPCContext& ctx, uint8_t* base), so under SysV base is in rsi. xmemory.h says the
# base is "often something like 0x100000000"; often is not always.
#
# sub_82EE7828 is the second guest function called in a boot (p11 trace), and guest code cannot
# run before memory is mapped, so it is early and safe.
#
# Absolute paths throughout: run_session.sh cd's into $OUT before exec'ing gdb, and relative
# paths here resolve one level deeper and fail silently.
#
# 2 MB chunks because reserved guest pages are PROT_NONE. gdb fails a command rather than
# faulting the game, so an unmapped region costs one chunk, not the attempt.
set pagination off
set confirm off
set print thread-events off
set debuginfod enabled off
handle all nostop noprint pass
break sub_82EE7828
run
echo \n===MEMBASE===\n
p/x $rsi
set $mb = (unsigned char *) $rsi
echo \n===DUMPING===\n
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_8200.bin $mb+0x82000000 $mb+0x82200000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_8220.bin $mb+0x82200000 $mb+0x82400000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_8240.bin $mb+0x82400000 $mb+0x82600000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_8260.bin $mb+0x82600000 $mb+0x82800000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_8280.bin $mb+0x82800000 $mb+0x82A00000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_82A0.bin $mb+0x82A00000 $mb+0x82C00000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_82C0.bin $mb+0x82C00000 $mb+0x82E00000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_82E0.bin $mb+0x82E00000 $mb+0x83000000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_8300.bin $mb+0x83000000 $mb+0x83200000
dump binary memory /home/nakas/Documents/sk8Audio/probe/harness/out/image/g_8320.bin $mb+0x83200000 $mb+0x83400000
echo \n===DONE===\n
kill
quit
