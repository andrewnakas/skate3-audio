# Run the game under gdb, stopping only on the arithmetic fault being chased. The recomp
# uses signals for its own work (guest memory faults, thread control), so every other
# signal passes straight through without stopping or printing.
set pagination off
set confirm off
set print thread-events off
set debuginfod enabled off
handle all nostop noprint pass
handle SIGFPE stop print nopass
run
echo \n===SIGNAL===\n
info program
echo \n===BACKTRACE===\n
bt 30
echo \n===INSTRUCTIONS===\n
info symbol $pc
x/6i $pc
echo \n===REGISTERS===\n
info registers rip rsp rax rbx rcx rdx rsi rdi r8 r9 r10 r11 eflags
echo \n===END===\n
kill
quit
