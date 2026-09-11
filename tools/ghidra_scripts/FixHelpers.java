//Mark the PPC __savegprlr_/__restgprlr_ prologue helpers so the decompiler stops
//treating them as value-returning calls.
//
//These are compiler register save/restore stubs with a custom convention. Ghidra
//models them as ordinary functions, so a prologue `bl __savegprlr_26` decompiles as
//`iVar2 = __savegprlr_26();` and the real first argument in r3 is lost -- every
//function using one gets its parameters mis-recovered. Setting them void/no-params
//and inline lets the decompiler see through them.
//@category Skate3
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.VoidDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.ParameterImpl;
import ghidra.program.model.symbol.SourceType;

import java.util.ArrayList;
import java.util.List;

public class FixHelpers extends GhidraScript {

    @Override
    public void run() throws Exception {
        int fixed = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (monitor.isCancelled()) {
                break;
            }
            String n = f.getName();
            if (!n.startsWith("__savegprlr_") && !n.startsWith("__restgprlr_")
                    && !n.startsWith("__savefpr_") && !n.startsWith("__restfpr_")
                    && !n.startsWith("__savevmx_") && !n.startsWith("__restvmx_")) {
                continue;
            }
            f.setReturnType(VoidDataType.dataType, SourceType.USER_DEFINED);
            f.replaceParameters(new ArrayList<ParameterImpl>(),
                    Function.FunctionUpdateType.DYNAMIC_STORAGE_FORMAL_PARAMS,
                    true, SourceType.USER_DEFINED);
            f.setInline(true);
            f.setNoReturn(false);
            fixed++;
        }
        println("FixHelpers: adjusted " + fixed + " helper functions");
    }
}
