# `simpy.exceptions` — Exception types used by SimPy

SimPy specific exceptions.

## exception `simpy.exceptions.SimPyException`

Base class for all SimPy specific exceptions.

## exception `simpy.exceptions.Interrupt(cause: Any | None)`

Exception thrown into a process if it is interrupted (see `interrupt()`).

`cause` provides the reason for the interrupt, if any.

If a process is interrupted concurrently, all interrupts will be thrown into the process in the same order as they occurred.

### property `cause: Any | None`

The cause of the interrupt or `None` if no cause was provided.