# components.json

`components.json` is the project contract for where shadcn/ui places generated
files and how it writes imports.

## Fields To Inspect

- `style`: style family such as `new-york`, or style values that encode Radix
  or Base variants in newer setups.
- `tsx`: whether generated components use TypeScript/TSX.
- `rsc`: whether React Server Components are expected.
- `tailwind`: config, CSS file, base color, CSS variables, and prefix.
- `aliases`: `components`, `ui`, `lib`, `hooks`, and `utils`.
- `iconLibrary`: configured icon source.
- `registries`: official, private, or custom registry templates.
- `rtl`: right-to-left setup state when present.

## Current Base Selection Fact

The current public schema does not expose a top-level `base` field. Base choice
is selected during setup with CLI controls such as `--base radix|base`, style
values such as `radix-nova` or `base-nova`, and the CLI `info` output.

## Package Imports

When package imports are used, `package.json#imports` can provide private
`#...` aliases while `components.json` still tells the CLI where to place files.
Check both files before changing import paths.
