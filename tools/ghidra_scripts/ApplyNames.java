//Apply recovered symbol names to functions from a CSV of "HEXADDR,name" lines.
//Creates a function at the address if none exists, so imports and helpers that were
//never decompiled still render by name at their call sites.
//@category Skate3
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

import java.io.BufferedReader;
import java.io.FileReader;

public class ApplyNames extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("usage: ApplyNames <csv>");
            return;
        }
        int renamed = 0, created = 0, skipped = 0;
        try (BufferedReader r = new BufferedReader(new FileReader(args[0]))) {
            String line;
            while ((line = r.readLine()) != null) {
                if (monitor.isCancelled()) {
                    break;
                }
                int comma = line.indexOf(',');
                if (comma <= 0) {
                    continue;
                }
                long a;
                try {
                    a = Long.parseLong(line.substring(0, comma).trim(), 16);
                } catch (NumberFormatException e) {
                    continue;
                }
                String name = line.substring(comma + 1).trim();
                if (name.isEmpty()) {
                    continue;
                }
                Address addr = toAddr(a);
                Function f = getFunctionAt(addr);
                if (f == null) {
                    f = createFunction(addr, name);
                    if (f == null) {
                        skipped++;
                        continue;
                    }
                    created++;
                } else {
                    renamed++;
                }
                f.setName(name, SourceType.USER_DEFINED);
            }
        }
        println("ApplyNames: renamed " + renamed + ", created " + created
                + ", skipped " + skipped);
    }
}
