# `simpy.core` — SimPy’s core components

Core components for event-discrete simulation environments.

## class `simpy.core.Environment(initial_time: int | float = 0)`

Execution environment for an event-based simulation. The passing of time is simulated by stepping from event to event.

You can provide an `initial_time` for the environment. By default, it starts at 0.

This class also provides aliases for common event types, for example process, timeout and event.

### property `now: int | float`
The current simulation time.

### property `active_process: Process | None`
The currently active process of the environment.

### `process`
alias of `Process`

### `timeout`
alias of `Timeout`

### `event`
alias of `Event`

### `all_of`
alias of `AllOf`

### `any_of`
alias of `AnyOf`

### `schedule(event: Event, priority: EventPriority = 1, delay: int | float = 0) → None`
Schedule an event with a given priority and a delay.

### `peek() → int | float`
Get the time of the next scheduled event. Return Infinity if there is no further event.

### `step() → None`
Process the next event.

Raise an `EmptySchedule` if no further events are available.

### `run(until: int | float | Event | None = None) → Any | None`
Executes `step()` until the given criterion `until` is met.

If it is `None` (which is the default), this method will return when there are no further events to be processed.

If it is an `Event`, the method will continue stepping until this event has been triggered and will return its value. Raises a `RuntimeError` if there are no further events to be processed and the `until` event was not triggered.

If it is a number, the method will continue stepping until the environment’s time reaches `until`.

---

## class `simpy.core.BoundClass(cls: Type[T])`

Allows classes to behave like methods.

The `__get__()` descriptor is basically identical to `function.__get__()` and binds the first argument of the `cls` to the descriptor instance.

### static `bind_early(instance: object) → None`
Bind all `BoundClass` attributes of the instance’s class to the instance itself to increase performance.

---

## class `simpy.core.EmptySchedule`

Thrown by an `Environment` if there are no further events to be processed.

---

## `simpy.core.Infinity: float = inf`

Convenience alias for infinity