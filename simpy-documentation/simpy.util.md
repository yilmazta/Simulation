# `simpy.util` — Utility functions for SimPy

A collection of utility functions:

`start_delayed(env, generator, delay)`

Return a helper process that starts another process for `generator` after a certain `delay`.

## `simpy.util.start_delayed(env: Environment, generator: Generator[Event, Any, Any], delay: int | float) → Process`

Return a helper process that starts another process for `generator` after a certain `delay`.

`process()` starts a process at the current simulation time. This helper allows you to start a process after a delay of `delay` simulation time units:

```python
from simpy import Environment
from simpy.util import start_delayed

def my_process(env, x):
    print(f'{env.now}, {x}')
    yield env.timeout(1)

env = Environment()
proc = start_delayed(env, my_process(env, 3), 5)
env.run()
5, 3

Raise a ValueError if delay <= 0.