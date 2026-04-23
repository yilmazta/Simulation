# `simpy.events` — Core event types

This module contains the basic event types used in SimPy.

The base class for all events is `Event`. Though it can be directly used, there are several specialized subclasses of it.

`Event(env)`

An event that may happen at some point in time.

`Timeout(env, delay[, value])`

A `Event` that gets processed after a delay has passed.

`Process(env, generator)`

Process an event yielding generator.

`AnyOf(env, events)`

A `Condition` event that is triggered if any of a list of events has been successfully triggered.

`AllOf(env, events)`

A `Condition` event that is triggered if all of a list of events have been successfully triggered.

## `simpy.events.PENDING = object()`
Unique object to identify pending values of events.

## `simpy.events.URGENT: EventPriority = 0`
Priority of interrupts and process initialization events.

## `simpy.events.NORMAL: EventPriority = 1`
Default priority used by events.

---

## class `simpy.events.Event(env: Environment)`

An event that may happen at some point in time.

An event

may happen (`triggered` is `False`),

is going to happen (`triggered` is `True`) or

has happened (`processed` is `True`).

Every event is bound to an environment `env` and is initially not triggered. Events are scheduled for processing by the environment after they are triggered by either `succeed()`, `fail()` or `trigger()`. These methods also set the `ok` flag and the value of the event.

An event has a list of callbacks. A callback can be any callable. Once an event gets processed, all callbacks will be invoked with the event as the single argument. Callbacks can check if the event was successful by examining `ok` and do further processing with the value it has produced.

Failed events are never silently ignored and will raise an exception upon being processed. If a callback handles an exception, it must set `defused` to `True` to prevent this.

This class also implements `__and__()` (`&`) and `__or__()` (`|`). If you concatenate two events using one of these operators, a `Condition` event is generated that lets you wait for both or one of them.

### `env`
The `Environment` the event lives in.

### `callbacks: List[Callable[[EventType], None]]`
List of functions that are called when the event is processed.

### property `triggered: bool`
Becomes `True` if the event has been triggered and its callbacks are about to be invoked.

### property `processed: bool`
Becomes `True` if the event has been processed (e.g., its callbacks have been invoked).

### property `ok: bool`
Becomes `True` when the event has been triggered successfully.

A “successful” event is one triggered with `succeed()`.

Raises : `AttributeError` – if accessed before the event is triggered.

### property `defused: bool`
Becomes `True` when the failed event’s exception is “defused”.

When an event fails (i.e. with `fail()`), the failed event’s value is an exception that will be re-raised when the `Environment` processes the event (i.e. in `step()`).

It is also possible for the failed event’s exception to be defused by setting `defused` to `True` from an event callback. Doing so prevents the event’s exception from being re-raised when the event is processed by the `Environment`.

### property `value: Any | None`
The value of the event if it is available.

The value is available when the event has been triggered.

Raises `AttributeError` if the value is not yet available.

### `trigger(event: Event) → None`
Trigger the event with the state and value of the provided event. Return `self` (this event instance).

This method can be used directly as a callback function to trigger chain reactions.

### `succeed(value: Any | None = None) → Event`
Set the event’s value, mark it as successful and schedule it for processing by the environment. Returns the event instance.

Raises `RuntimeError` if this event has already been triggered.

### `fail(exception: Exception) → Event`
Set exception as the events value, mark it as failed and schedule it for processing by the environment. Returns the event instance.

Raises `TypeError` if exception is not an `Exception`.

Raises `RuntimeError` if this event has already been triggered.

---

## class `simpy.events.Timeout(env: Environment, delay: SimTime, value: Any | None = None)`

A `Event` that gets processed after a delay has passed.

This event is automatically triggered when it is created.

### `env`
The `Environment` the event lives in.

### `callbacks: List[Callable[[EventType], None]]`
List of functions that are called when the event is processed.

### property `defused: bool`
Becomes `True` when the failed event’s exception is “defused”.

When an event fails (i.e. with `fail()`), the failed event’s value is an exception that will be re-raised when the `Environment` processes the event (i.e. in `step()`).

It is also possible for the failed event’s exception to be defused by setting `defused` to `True` from an event callback. Doing so prevents the event’s exception from being re-raised when the event is processed by the `Environment`.

### `fail(exception: Exception) → Event`
Set exception as the events value, mark it as failed and schedule it for processing by the environment. Returns the event instance.

Raises `TypeError` if exception is not an `Exception`.

Raises `RuntimeError` if this event has already been triggered.

### property `ok: bool`
Becomes `True` when the event has been triggered successfully.

A “successful” event is one triggered with `succeed()`.

Raises : `AttributeError` – if accessed before the event is triggered.

### property `processed: bool`
Becomes `True` if the event has been processed (e.g., its callbacks have been invoked).

### `succeed(value: Any | None = None) → Event`
Set the event’s value, mark it as successful and schedule it for processing by the environment. Returns the event instance.

Raises `RuntimeError` if this event has already been triggered.

### `trigger(event: Event) → None`
Trigger the event with the state and value of the provided event. Return `self` (this event instance).

This method can be used directly as a callback function to trigger chain reactions.

### property `triggered: bool`
Becomes `True` if the event has been triggered and its callbacks are about to be invoked.

### property `value: Any | None`
The value of the event if it is available.

The value is available when the event has been triggered.

Raises `AttributeError` if the value is not yet available.

---

## class `simpy.events.Initialize(env: Environment, process: Process)`

Initializes a process. Only used internally by `Process`.

This event is automatically triggered when it is created.

### `env`
The `Environment` the event lives in.

### `callbacks: List[Callable[[EventType], None]]`
List of functions that are called when the event is processed.

### property `defused: bool`
Becomes `True` when the failed event’s exception is “defused”.

When an event fails (i.e. with `fail()`), the failed event’s value is an exception that will be re-raised when the `Environment` processes the event (i.e. in `step()`).

It is also possible for the failed event’s exception to be defused by setting `defused` to `True` from an event callback. Doing so prevents the event’s exception from being re-raised when the event is processed by the `Environment`.

### `fail(exception: Exception) → Event`
Set exception as the events value, mark it as failed and schedule it for processing by the environment. Returns the event instance.

Raises `TypeError` if exception is not an `Exception`.

Raises `RuntimeError` if this event has already been triggered.

### property `ok: bool`
Becomes `True` when the event has been triggered successfully.

A “successful” event is one triggered with `succeed()`.

Raises : `AttributeError` – if accessed before the event is triggered.

### property `processed: bool`
Becomes `True` if the event has been processed (e.g., its callbacks have been invoked).

### `succeed(value: Any | None = None) → Event`
Set the event’s value, mark it as successful and schedule it for processing by the environment. Returns the event instance.

Raises `RuntimeError` if this event has already been triggered.

### `trigger(event: Event) → None`
Trigger the event with the state and value of the provided event. Return `self` (this event instance).

This method can be used directly as a callback function to trigger chain reactions.

### property `triggered: bool`
Becomes `True` if the event has been triggered and its callbacks are about to be invoked.

### property `value: Any | None`
The value of the event if it is available.

The value is available when the event has been triggered.

Raises `AttributeError` if the value is not yet available.

---

## class `simpy.events.Interruption(process: Process, cause: Any | None)`

Immediately schedules an `Interrupt` exception with the given cause to be thrown into process.

This event is automatically triggered when it is created.

### `env`
The `Environment` the event lives in.

### `callbacks: List[Callable[[EventType], None]]`
List of functions that are called when the event is processed.

### property `defused: bool`
Becomes `True` when the failed event’s exception is “defused”.

When an event fails (i.e. with `fail()`), the failed event’s value is an exception that will be re-raised when the `Environment` processes the event (i.e. in `step()`).

It is also possible for the failed event’s exception to be defused by setting `defused` to `True` from an event callback. Doing so prevents the event’s exception from being re-raised when the event is processed by the `Environment`.

### `fail(exception: Exception) → Event`
Set exception as the events value, mark it as failed and schedule it for processing by the environment. Returns the event instance.

Raises `TypeError` if exception is not an `Exception`.

Raises `RuntimeError` if this event has already been triggered.

### property `ok: bool`
Becomes `True` when the event has been triggered successfully.

A “successful” event is one triggered with `succeed()`.

Raises : `AttributeError` – if accessed before the event is triggered.

### property `processed: bool`
Becomes `True` if the event has been processed (e.g., its callbacks have been invoked).

### `succeed(value: Any | None = None) → Event`
Set the event’s value, mark it as successful and schedule it for processing by the environment. Returns the event instance.

Raises `RuntimeError` if this event has already been triggered.

### `trigger(event: Event) → None`
Trigger the event with the state and value of the provided event. Return `self` (this event instance).

This method can be used directly as a callback function to trigger chain reactions.

### property `triggered: bool`
Becomes `True` if the event has been triggered and its callbacks are about to be invoked.

### property `value: Any | None`
The value of the event if it is available.

The value is available when the event has been triggered.

Raises `AttributeError` if the value is not yet available.

---

## class `simpy.events.Process(env: Environment, generator: ProcessGenerator)`

Process an event yielding generator.

A generator (also known as a coroutine) can suspend its execution by yielding an event. `Process` will take care of resuming the generator with the value of that event once it has happened. The exception of failed events is thrown into the generator.

`Process` itself is an event, too. It is triggered, once the generator returns or raises an exception. The value of the process is the return value of the generator or the exception, respectively.

Processes can be interrupted during their execution by `interrupt()`.

### `env`
The `Environment` the event lives in.

### `callbacks: List[Callable[[EventType], None]]`
List of functions that are called when the event is processed.

### property `target: Event`
The event that the process is currently waiting for.

Returns `None` if the process is dead, or it is currently being interrupted.

### property `name: str`
Name of the function used to start the process.

### property `is_alive: bool`
`True` until the process generator exits.

### `interrupt(cause: Any | None = None) → None`
Interrupt this process optionally providing a cause.

A process cannot be interrupted if it already terminated. A process can also not interrupt itself. Raise a `RuntimeError` in these cases.

### property `defused: bool`
Becomes `True` when the failed event’s exception is “defused”.

When an event fails (i.e. with `fail()`), the failed event’s value is an exception that will be re-raised when the `Environment` processes the event (i.e. in `step()`).

It is also possible for the failed event’s exception to be defused by setting `defused` to `True` from an event callback. Doing so prevents the event’s exception from being re-raised when the event is processed by the `Environment`.

### `fail(exception: Exception) → Event`
Set exception as the events value, mark it as failed and schedule it for processing by the environment. Returns the event instance.

Raises `TypeError` if exception is not an `Exception`.

Raises `RuntimeError` if this event has already been triggered.

### property `ok: bool`
Becomes `True` when the event has been triggered successfully.

A “successful” event is one triggered with `succeed()`.

Raises : `AttributeError` – if accessed before the event is triggered.

### property `processed: bool`
Becomes `True` if the event has been processed (e.g., its callbacks have been invoked).

### `succeed(value: Any | None = None) → Event`
Set the event’s value, mark it as successful and schedule it for processing by the environment. Returns the event instance.

Raises `RuntimeError` if this event has already been triggered.

### `trigger(event: Event) → None`
Trigger the event with the state and value of the provided event. Return `self` (this event instance).

This method can be used directly as a callback function to trigger chain reactions.

### property `triggered: bool`
Becomes `True` if the event has been triggered and its callbacks are about to be invoked.

### property `value: Any | None`
The value of the event if it is available.

The value is available when the event has been triggered.

Raises `AttributeError` if the value is not yet available.

---

## class `simpy.events.Condition(env: Environment, evaluate: Callable[[Tuple[Event, ...], int], bool], events: Iterable[Event])`

An event that gets triggered once the condition function `evaluate` returns `True` on the given list of events.

The value of the condition event is an instance of `ConditionValue` which allows convenient access to the input events and their values. The `ConditionValue` will only contain entries for those events that occurred before the condition is processed.

If one of the events fails, the condition also fails and forwards the exception of the failing event.

The `evaluate` function receives the list of target events and the number of processed events in this list: `evaluate(events, processed_count)`. If it returns `True`, the condition is triggered. The `Condition.all_events()` and `Condition.any_events()` functions are used to implement `and` (`&`) and `or` (`|`) for events.

Condition events can be nested.

### static `all_events(events: Tuple[Event, ...], count: int) → bool`
An evaluation function that returns `True` if all events have been triggered.

### static `any_events(events: Tuple[Event, ...], count: int) → bool`
An evaluation function that returns `True` if at least one of events has been triggered.

### property `defused: bool`
Becomes `True` when the failed event’s exception is “defused”.

When an event fails (i.e. with `fail()`), the failed event’s value is an exception that will be re-raised when the `Environment` processes the event (i.e. in `step()`).

It is also possible for the failed event’s exception to be defused by setting `defused` to `True` from an event callback. Doing so prevents the event’s exception from being re-raised when the event is processed by the `Environment`.

### `fail(exception: Exception) → Event`
Set exception as the events value, mark it as failed and schedule it for processing by the environment. Returns the event instance.

Raises `TypeError` if exception is not an `Exception`.

Raises `RuntimeError` if this event has already been triggered.

### property `ok: bool`
Becomes `True` when the event has been triggered successfully.

A “successful” event is one triggered with `succeed()`.

Raises : `AttributeError` – if accessed before the event is triggered.

### property `processed: bool`
Becomes `True` if the event has been processed (e.g., its callbacks have been invoked).

### `succeed(value: Any | None = None) → Event`
Set the event’s value, mark it as successful and schedule it for processing by the environment. Returns the event instance.

Raises `RuntimeError` if this event has already been triggered.

### `trigger(event: Event) → None`
Trigger the event with the state and value of the provided event. Return `self` (this event instance).

This method can be used directly as a callback function to trigger chain reactions.

### property `triggered: bool`
Becomes `True` if the event has been triggered and its callbacks are about to be invoked.

### property `value: Any | None`
The value of the event if it is available.

The value is available when the event has been triggered.

Raises `AttributeError` if the value is not yet available.

### `callbacks: List[Callable[[EventType], None]]`
List of functions that are called when the event is processed.

### `env`
The `Environment` the event lives in.

---

## class `simpy.events.AllOf(env: Environment, events: Iterable[Event])`

A `Condition` event that is triggered if all of a list of events have been successfully triggered. Fails immediately if any of events failed.

### property `defused: bool`
Becomes `True` when the failed event’s exception is “defused”.

When an event fails (i.e. with `fail()`), the failed event’s value is an exception that will be re-raised when the `Environment` processes the event (i.e. in `step()`).

It is also possible for the failed event’s exception to be defused by setting `defused` to `True` from an event callback. Doing so prevents the event’s exception from being re-raised when the event is processed by the `Environment`.

### `fail(exception: Exception) → Event`
Set exception as the events value, mark it as failed and schedule it for processing by the environment. Returns the event instance.

Raises `TypeError` if exception is not an `Exception`.

Raises `RuntimeError` if this event has already been triggered.

### property `ok: bool`
Becomes `True` when the event has been triggered successfully.

A “successful” event is one triggered with `succeed()`.

Raises : `AttributeError` – if accessed before the event is triggered.

### property `processed: bool`
Becomes `True` if the event has been processed (e.g., its callbacks have been invoked).

### `succeed(value: Any | None = None) → Event`
Set the event’s value, mark it as successful and schedule it for processing by the environment. Returns the event instance.

Raises `RuntimeError` if this event has already been triggered.

### `trigger(event: Event) → None`
Trigger the event with the state and value of the provided event. Return `self` (this event instance).

This method can be used directly as a callback function to trigger chain reactions.

### property `triggered: bool`
Becomes `True` if the event has been triggered and its callbacks are about to be invoked.

### property `value: Any | None`
The value of the event if it is available.

The value is available when the event has been triggered.

Raises `AttributeError` if the value is not yet available.

### `callbacks: List[Callable[[EventType], None]]`
List of functions that are called when the event is processed.

### `env`
The `Environment` the event lives in.

---

## class `simpy.events.AnyOf(env: Environment, events: Iterable[Event])`

A `Condition` event that is triggered if any of a list of events has been successfully triggered. Fails immediately if any of events failed.

### property `defused: bool`
Becomes `True` when the failed event’s exception is “defused”.

When an event fails (i.e. with `fail()`), the failed event’s value is an exception that will be re-raised when the `Environment` processes the event (i.e. in `step()`).

It is also possible for the failed event’s exception to be defused by setting `defused` to `True` from an event callback. Doing so prevents the event’s exception from being re-raised when the event is processed by the `Environment`.

### `fail(exception: Exception) → Event`
Set exception as the events value, mark it as failed and schedule it for processing by the environment. Returns the event instance.

Raises `TypeError` if exception is not an `Exception`.

Raises `RuntimeError` if this event has already been triggered.

### property `ok: bool`
Becomes `True` when the event has been triggered successfully.

A “successful” event is one triggered with `succeed()`.

Raises : `AttributeError` – if accessed before the event is triggered.

### property `processed: bool`
Becomes `True` if the event has been processed (e.g., its callbacks have been invoked).

### `succeed(value: Any | None = None) → Event`
Set the event’s value, mark it as successful and schedule it for processing by the environment. Returns the event instance.

Raises `RuntimeError` if this event has already been triggered.

### `trigger(event: Event) → None`
Trigger the event with the state and value of the provided event. Return `self` (this event instance).

This method can be used directly as a callback function to trigger chain reactions.

### property `triggered: bool`
Becomes `True` if the event has been triggered and its callbacks are about to be invoked.

### property `value: Any | None`
The value of the event if it is available.

The value is available when the event has been triggered.

Raises `AttributeError` if the value is not yet available.

### `callbacks: List[Callable[[EventType], None]]`
List of functions that are called when the event is processed.

### `env`
The `Environment` the event lives in.

---

## class `simpy.events.ConditionValue`

Result of a `Condition`. It supports convenient dict-like access to the triggered events and their values. The events are ordered by their occurrences in the condition.