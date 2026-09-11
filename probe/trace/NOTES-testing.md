# Testing notes for the session harness

**Never delete an output file before provoking the event that writes it.** The crash-flush
test cleared `<log>.trace` and then sent SIGABRT — but the game had already faulted on its
own and the handler had already written the trace, so the `rm` destroyed the only copy. The
log line ("DUMPED 262144 entries ... - guest fault") was the sole surviving evidence that
the feature worked.

**A process that died before your signal did not die from your signal.** The same test
printed "process exited after SIGABRT" because `pkill` found nothing and the wait loop
exited immediately. Check the exit cause, not the absence of a process.

**Ring mode is not a free upgrade over first mode.** `first` records one entry per function;
`ring` records every call, and each record dereferences r3/r4/r5 looking for strings. Three
sessions in `first` mode took zero faults; the first `ring` session faulted 217 ms after
arming, reading the address sitting in r5.
