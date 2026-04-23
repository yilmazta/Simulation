# `simpy.resources` — Shared resource primitives

SimPy implements three types of resources that can be used to synchronize processes or to model congestion points:

`resource`

Shared resources supporting priorities and preemption.

`container`

Resource for sharing homogeneous matter between processes, either continuous (like water) or discrete (like apples).

`store`

Shared resources for storing a possibly unlimited amount of objects supporting requests for specific objects.

They are derived from the base classes defined in the `base` module. These classes are also meant to support the implementation of custom resource types.

---

## Resources — `simpy.resources.resource`

Shared resources supporting priorities and preemption.

These resources can be used to limit the number of processes using them concurrently. A process needs to request the usage right to a resource. Once the usage right is not needed any more it has to be released. A gas station can be modelled as a resource with a limited amount of fuel-pumps. Vehicles arrive at the gas station and request to use a fuel-pump. If all fuel-pumps are in use, the vehicle needs to wait until one of the users has finished refueling and releases its fuel-pump.

These resources can be used by a limited number of processes at a time. Processes request these resources to become a user and have to release them once they are done. For example, a gas station with a limited number of fuel pumps can be modeled with a `Resource`. Arriving vehicles request a fuel-pump. Once one is available they refuel. When they are done, the release the fuel-pump and leave the gas station.

Requesting a resource is modelled as “putting a process’ token into the resources” and releasing a resources correspondingly as “getting a process’ token out of the resource”. Thus, calling `request()`/`release()` is equivalent to calling `put()`/`get()`. Note, that releasing a resource will always succeed immediately, no matter if a process is actually using a resource or not.

Besides `Resource`, there is a `PriorityResource`, where processes can define a request priority, and a `PreemptiveResource` whose resource users can be preempted by requests with a higher priority.

## class `simpy.resources.resource.Resource(env: Environment, capacity: int = 1)`

Resource with `capacity` of usage slots that can be requested by processes.

If all slots are taken, requests are enqueued. Once a usage request is released, a pending request will be triggered.

The `env` parameter is the `Environment` instance the resource is bound to.

### `users: List[Request]`
List of `Request` events for the processes that are currently using the resource.

### `queue`
Queue of pending `Request` events. Alias of `put_queue`.

### property `count: int`
Number of users currently using the resource.

### `request`
alias of `Request`

### `release`
alias of `Release`

---

## class `simpy.resources.resource.PriorityResource(env: Environment, capacity: int = 1)`

A `Resource` supporting prioritized requests.

Pending requests in the `queue` are sorted in ascending order by their `priority` (that means lower values are more important).

### `PutQueue`
Type of the put queue. See `put_queue` for details.

alias of `SortedQueue`

### `GetQueue`
Type of the get queue. See `get_queue` for details.

alias of `list`

### `request`
alias of `PriorityRequest`

### `release`
alias of `Release`

---

## class `simpy.resources.resource.PreemptiveResource(env: Environment, capacity: int = 1)`

A `PriorityResource` with preemption.

If a request is preempted, the process of that request will receive an `Interrupt` with a `Preempted` instance as cause.

### `users: List[PriorityRequest]`
List of `Request` events for the processes that are currently using the resource.

---

## class `simpy.resources.resource.Preempted(by: Process | None, usage_since: SimTime | None, resource: Resource)`

Cause of a preemption `Interrupt` containing information about the preemption.

### `by`
The preempting `simpy.events.Process`.

### `usage_since`
The simulation time at which the preempted process started to use the resource.

### `resource`
The resource which was lost, i.e., caused the preemption.

---

## class `simpy.resources.resource.Request(resource: ResourceType)`

Request usage of the `resource`. The event is triggered once access is granted. Subclass of `simpy.resources.base.Put`.

If the maximum capacity of users has not yet been reached, the request is triggered immediately. If the maximum capacity has been reached, the request is triggered once an earlier usage request on the resource is released.

The request is automatically released when the request was created within a `with` statement.

### `usage_since: SimTime | None = None`
The time at which the request succeeded.

---

## class `simpy.resources.resource.PriorityRequest(resource: Resource, priority: int = 0, preempt: bool = True)`

Request the usage of `resource` with a given `priority`. If the `resource` supports preemption and `preempt` is `True` other usage requests of the `resource` may be preempted (see `PreemptiveResource` for details).

This event type inherits `Request` and adds some additional attributes needed by `PriorityResource` and `PreemptiveResource`

### `priority`
The priority of this request. A smaller number means higher priority.

### `preempt`
Indicates whether the request should preempt a resource user or not (`PriorityResource` ignores this flag).

### `time`
The time at which the request was made.

### `key`
Key for sorting events. Consists of the priority (lower value is more important), the time at which the request was made (earlier requests are more important) and finally the preemption flag (preempt requests are more important).

---

## class `simpy.resources.resource.Release(resource: Resource, request: Request)`

Releases the usage of `resource` granted by `request`. This event is triggered immediately. Subclass of `simpy.resources.base.Get`.

### `request`
The request (`Request`) that is to be released.

---

## class `simpy.resources.resource.SortedQueue(maxlen: int | None = None)`

Queue for sorting events by their `key` attribute.

### `maxlen`
Maximum length of the queue.

### `append(item: Any) → None`
Sort `item` into the queue.

Raise a `RuntimeError` if the queue is full.

---

## Containers — `simpy.resources.container`

Resource for sharing homogeneous matter between processes, either continuous (like water) or discrete (like apples).

A `Container` can be used to model the fuel tank of a gasoline station. Tankers increase and refuelled cars decrease the amount of gas in the station’s fuel tanks.

## class `simpy.resources.container.Container(env: Environment, capacity: int | float = inf, init: int | float = 0)`

Resource containing up to `capacity` of matter which may either be continuous (like water) or discrete (like apples). It supports requests to put or get matter into/from the container.

The `env` parameter is the `Environment` instance the container is bound to.

The `capacity` defines the size of the container. By default, a container is of unlimited size. The initial amount of matter is specified by `init` and defaults to `0`.

Raise a `ValueError` if `capacity <= 0`, `init < 0` or `init > capacity`.

### property `level: int | float`
The current amount of the matter in the container.

### `put`
alias of `ContainerPut`

### `get`
alias of `ContainerGet`

---

## class `simpy.resources.container.ContainerPut(container: Container, amount: int | float)`

Request to put `amount` of matter into the `container`. The request will be triggered once there is enough space in the container available.

Raise a `ValueError` if `amount <= 0`.

### `amount`
The amount of matter to be put into the container.

---

## class `simpy.resources.container.ContainerGet(container: Container, amount: int | float)`

Request to get `amount` of matter from the `container`. The request will be triggered once there is enough matter available in the container.

Raise a `ValueError` if `amount <= 0`.

### `amount`
The amount of matter to be taken out of the container.

---

## Stores — `simpy.resources.store`

Shared resources for storing a possibly unlimited amount of objects supporting requests for specific objects.

The `Store` operates in a FIFO (first-in, first-out) order. Objects are retrieved from the store in the order they were put in. The `get` requests of a `FilterStore` can be customized by a `filter` to only retrieve objects matching a given criterion.

## class `simpy.resources.store.Store(env: Environment, capacity: float | int = inf)`

Resource with `capacity` slots for storing arbitrary objects. By default, the `capacity` is unlimited and objects are put and retrieved from the store in a first-in first-out order.

The `env` parameter is the `Environment` instance the container is bound to.

### `items: List[Any]`
List of the items available in the store.

### `put`
alias of `StorePut`

### `get`
alias of `StoreGet`

### property `capacity: float | int`
Maximum capacity of the resource.

---

## class `simpy.resources.store.PriorityItem(priority, item)`

Wrap an arbitrary `item` with an order-able `priority`.

Pairs a priority with an arbitrary item. Comparisons of `PriorityItem` instances only consider the `priority` attribute, thus supporting use of unorderable items in a `PriorityStore` instance.

### `priority: Any`
Priority of the item.

### `item: Any`
The item to be stored.

---

## class `simpy.resources.store.PriorityStore(env: Environment, capacity: float | int = inf)`

Resource with `capacity` slots for storing objects in priority order.

Unlike `Store` which provides first-in first-out discipline, `PriorityStore` maintains items in sorted order such that the smallest items value are retrieved first from the store.

All items in a `PriorityStore` instance must be order-able; which is to say that items must implement `__lt__()`. To use unorderable items with `PriorityStore`, use `PriorityItem`.

---

## class `simpy.resources.store.FilterStore(env: Environment, capacity: float | int = inf)`

Resource with `capacity` slots for storing arbitrary objects supporting filtered `get` requests. Like the `Store`, the capacity is unlimited by default and objects are put and retrieved from the store in a first-in first-out order.

Get requests can be customized with a `filter` function to only trigger for items for which said filter function returns `True`.

> **Note**
> In contrast to `Store`, `get` requests of a `FilterStore` won’t necessarily be triggered in the same order they were issued.
>
> Example: The store is empty. Process 1 tries to get an item of type `a`, Process 2 an item of type `b`. Another process puts one item of type `b` into the store. Though Process 2 made his request after Process 1, it will receive that new item because Process 1 doesn’t want it.

### `get`
alias of `FilterStoreGet`

---

## class `simpy.resources.store.StorePut(store: Store, item: Any)`

Request to put `item` into the `store`. The request is triggered once there is space for the `item` in the store.

### `item`
The item to put into the store.

---

## class `simpy.resources.store.StoreGet(resource: ResourceType)`

Request to get an `item` from the `store`. The request is triggered once there is an item available in the store.

---

## class `simpy.resources.store.FilterStoreGet(resource: ~simpy.resources.store.FilterStore, filter: ~typing.Callable[[~typing.Any], bool] = <function FilterStoreGet.<lambda>>)`

Request to get an `item` from the `store` matching the `filter`. The request is triggered once there is such an item available in the store.

`filter` is a function receiving one item. It should return `True` for items matching the filter criterion. The default function returns `True` for all items, which makes the request to behave exactly like `StoreGet`.

### `filter`
The filter function to filter items in the store.

---

## Base classes — `simpy.resources.base`

Base classes of for SimPy’s shared resource types.

`BaseResource` defines the abstract base resource. It supports `get` and `put` requests, which return `Put` and `Get` events respectively. These events are triggered once the request has been completed.

## class `simpy.resources.base.BaseResource(env: Environment, capacity: float | int)`

Abstract base class for a shared resource.

You can `put()` something into the resources or `get()` something out of it. Both methods return an event that is triggered once the operation is completed. If a `put()` request cannot complete immediately (for example if the resource has reached a capacity limit) it is enqueued in the `put_queue` for later processing. Likewise for `get()` requests.

Subclasses can customize the resource by:

* providing custom `PutQueue` and `GetQueue` types,
* providing custom `Put` respectively `Get` events,
* and implementing the request processing behaviour through the methods `_do_get()` and `_do_put()`.

### `PutQueue`
The type to be used for the `put_queue`. It is a plain `list` by default. The type must support index access (e.g. `__getitem__()` and `__len__()`) as well as provide `append()` and `pop()` operations.

alias of `list`

### `GetQueue`
The type to be used for the `get_queue`. It is a plain `list` by default. The type must support index access (e.g. `__getitem__()` and `__len__()`) as well as provide `append()` and `pop()` operations.

alias of `list`

### `put_queue: MutableSequence[PutType]`
Queue of pending put requests.

### `get_queue: MutableSequence[GetType]`
Queue of pending get requests.

### property `capacity: float | int`
Maximum capacity of the resource.

### `put`
alias of `Put`

### `get`
alias of `Get`

---

## class `simpy.resources.base.Put(resource: ResourceType)`

Generic event for requesting to put something into the resource.

This event (and all of its subclasses) can act as context manager and can be used with the `with` statement to automatically cancel the request if an exception (like an `simpy.exceptions.Interrupt` for example) occurs:

```python
with res.put(item) as request:
    yield request
```

### `cancel() → None`

Cancel this put request.

This method has to be called if the put request must be aborted, for example if a process needs to handle an exception like an `Interrupt`.

If the put request was created in a `with` statement, this method is called automatically.

---

## class `simpy.resources.base.Get(resource: ResourceType)`

Generic event for requesting to get something from the resource.

This event (and all of its subclasses) can act as context manager and can be used with the `with` statement to automatically cancel the request if an exception (like an `simpy.exceptions.Interrupt` for example) occurs:

```python
with res.get() as request:
    item = yield request

cancel() → None
Cancel this get request.

This method has to be called if the get request must be aborted, for example if a process needs to handle an exception like an Interrupt.

If the get request was created in a with statement, this method is called automatically.
