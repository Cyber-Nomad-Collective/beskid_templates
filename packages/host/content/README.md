# {{name}}

Beskid host composition created from `beskid.templates.host`.

Defines `AppHost` with a singleton `Logger` registry entry and launches it from
`Main`. The empty service type supports default construction; add a source
constructor when a service needs value fields.

```bash
beskid lock
beskid build
beskid run
```
