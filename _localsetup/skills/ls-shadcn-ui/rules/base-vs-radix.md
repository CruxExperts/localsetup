# Base UI vs Radix Rules

- Confirm base from CLI `info`, setup flags, style values, and generated code.
- Radix composition commonly uses `asChild`.
- Base UI composition commonly uses `render` and may need
  `nativeButton={false}`.
- Do not mix primitive APIs from Radix and Base in the same component.
- Use migration helpers when moving existing projects between primitive families.
- Re-check imports after migration; newer Radix migration flows may consolidate
  imports into the `radix-ui` package.
