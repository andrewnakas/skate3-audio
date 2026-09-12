# sub_82B1F7E8

Seven lines: `mftb r3`, then return. The most-called function in the audio set at **11,147,383
calls per boot session**, and the one function here that can never be shadow-verified.

`docs/PLAN.md` names it as the reason gate 3 exists. Two calls return two different values, so
the register compare diverges on every call; and it writes no memory, so comparing memory
instead would be vacuously green. Neither failure says anything about the port, which is why the
gate is a property of the function rather than a problem to engineer around.

So it carries `kPortGate3`: the body is written and readable, the macro never arms the shadow
branch for it, and it is never promoted. `Windows()` returns false and is unreachable.

The port is a one-liner because `REX_QUERY_TIMEBASE()` is the same primitive the lifted body
uses. A Rust port would need a host timebase with the same tick rate, which is the only open
question here.
