# `simpy.rt` — Real-time simulation

Execution environment for events that synchronizes passing of time with the real-time (aka wall-clock time).

---

## class `simpy.rt.RealtimeEnvironment(initial_time: int | float = 0, factor: float = 1.0, strict: bool = True)`

Execution environment for an event-based simulation which is synchronized with the real-time (also known as wall-clock time). A time step will take `factor` seconds of real time (one second by default). A step from 0 to 3 with a `factor=0.5` will, for example, take at least 1.5 seconds.

The `step()` method will raise a `RuntimeError` if a time step took too long to compute. This behaviour can be disabled by setting `strict` to `False`.

### `now`
The current simulation time.

### `active_process`
The currently active process of the environment.

### `factor`
Scaling factor of the real-time.

### `strict`
Running mode of the environment. `step()` will raise a `RuntimeError` if this is set to `True` and the processing of events takes too long.

### `process(generator)`
Create a new `Process` instance for generator.

### `timeout(delay, value=None)`
Return a new `Timeout` event with a delay and, optionally, a value.

### `event()`
Return a new `Event` instance. Yielding this event suspends a process until another process triggers the event.

### `all_of(events)`
Return a new `AllOf` condition for a list of events.

### `any_of(events)`
Return a new `AnyOf` condition for a list of events.

### `schedule(event: Event, priority: EventPriority = 1, delay: int | float = 0) → None`
Schedule an event with a given priority and a delay.

### `peek() → int | float`
Get the time of the next scheduled event. Return `Infinity` if there is no further event.

### `step() → None`
Process the next event after enough real-time has passed for the event to happen.

The delay is scaled according to the real-time factor. With `strict` mode enabled, a `RuntimeError` will be raised, if the event is processed too slowly.

### `sync() → None`
Synchronize the internal time with the current wall-clock time.

This can be useful to prevent `step()` from raising an error if a lot of time passes between creating the `RealtimeEnvironment` and calling `run()` or `step()`.

### `run(until: int | float | Event | None = None) → Any | None`
Executes `step()` until the given criterion `until` is met.

If it is `None` (which is the default), this method will return when there are no further events to be processed.

If it is an `Event`, the method will continue stepping until this event has been triggered and will return its value. Raises a `RuntimeError` if there are no further events to be processed and the `until` event was not triggered.

If it is a number, the method will continue stepping until the environment’s time reaches `until`.