# {{name}}

Beskid fiber demo created from `beskid.templates.fiber-demo`.

Imports the implicit Corelib modules through `Std`, spawns a cooperative fiber
from a capture-free entry point, and joins its result. The app exits successfully
when the worker returns `42`; a failed join or unexpected value exits with code 1.

```bash
beskid lock
beskid build
beskid run
```
