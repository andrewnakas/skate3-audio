//Decompile a list of guest functions and write one .c file per function.
//Reads newline-separated hex addresses (no 0x) from args[0]; writes to args[1].
//@category Skate3
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.FileWriter;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

public class DecompileAudio extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: DecompileAudio <addr-list> <out-dir>");
            return;
        }
        List<Long> addrs = new ArrayList<>();
        try (BufferedReader r = new BufferedReader(new FileReader(args[0]))) {
            String line;
            while ((line = r.readLine()) != null) {
                line = line.trim();
                if (!line.isEmpty()) {
                    addrs.add(Long.parseLong(line, 16));
                }
            }
        }
        Files.createDirectories(Paths.get(args[1]));
        println("DecompileAudio: " + addrs.size() + " addresses");

        // Define a function at every address first, so calls between them resolve to
        // named callees instead of raw pointers in the emitted C.
        int created = 0;
        for (long a : addrs) {
            if (monitor.isCancelled()) {
                return;
            }
            Address addr = toAddr(a);
            if (getFunctionAt(addr) == null) {
                if (createFunction(addr, String.format("sub_%08X", a)) != null) {
                    created++;
                }
            }
        }
        println("DecompileAudio: created " + created + " new functions");

        DecompInterface decomp = new DecompInterface();
        decomp.setOptions(new DecompileOptions());
        if (!decomp.openProgram(currentProgram)) {
            println("DecompileAudio: decompiler failed to open: " + decomp.getLastMessage());
            return;
        }

        int ok = 0, failed = 0;
        try {
            for (long a : addrs) {
                if (monitor.isCancelled()) {
                    break;
                }
                Function f = getFunctionAt(toAddr(a));
                if (f == null) {
                    failed++;
                    continue;
                }
                DecompileResults res = decomp.decompileFunction(f, 60, monitor);
                if (res == null || !res.decompileCompleted()
                        || res.getDecompiledFunction() == null) {
                    failed++;
                    continue;
                }
                String path = String.format("%s/sub_%08X.c", args[1], a);
                try (FileWriter w = new FileWriter(path)) {
                    w.write(res.getDecompiledFunction().getC());
                }
                ok++;
                if (ok % 100 == 0) {
                    println("DecompileAudio: " + ok + " done");
                }
            }
        } finally {
            decomp.dispose();
        }
        println("DecompileAudio: wrote " + ok + ", failed " + failed);
    }
}
