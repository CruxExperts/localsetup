# TypeScript Quality Standards Snapshot

Source snapshot checked: 2026-05-11.

This reference is a dated starting point for agents. Always verify official
project docs before changing version-sensitive TypeScript, Node, framework,
lint, or build configuration.

## Current Version Signals

- TypeScript latest on npm: `6.0.3`, verified with
  `npm view typescript version dist-tags --json` on 2026-05-11. The official
  TypeScript 6.0 announcement was published on 2026-03-23 and says TypeScript
  6.0 is a bridge release toward the new Go-based TypeScript 7 line.
- Do not upgrade framework-pinned projects blindly. Angular, Next.js, Vite, and
  other framework toolchains may support only a bounded TypeScript or Node range.
- Node release guidance: production applications should use Active LTS or
  Maintenance LTS lines. As checked, Node 24 is the latest available LTS line
  and is Active LTS, Node 22 is Maintenance LTS, Node 20 is EOL, and Node 26 is
  the latest Current release line. For new production TypeScript projects,
  target Node 24 LTS unless framework, hosting, or package constraints require a
  different supported LTS line.

## Node Built-in TypeScript Type Stripping

Node's built-in TypeScript support is lightweight type stripping, not full
TypeScript compilation.

- Node performs no type checking.
- Node ignores `tsconfig.json` at runtime.
- `.tsx` files are unsupported.
- TypeScript syntax that requires code generation will error, including runtime
  `enum`, runtime `namespace`, parameter properties, import aliases, and
  decorators before JavaScript has native support for them.
- Type-only imports need the `type` keyword so Node does not treat them as value
  imports.
- Node refuses to run TypeScript files from dependencies under `node_modules`.
- For native type stripping, Node recommends TypeScript 5.8 or newer and these
  compiler settings:

```json
{
  "compilerOptions": {
    "noEmit": true,
    "target": "esnext",
    "module": "nodenext",
    "rewriteRelativeImportExtensions": true,
    "erasableSyntaxOnly": true,
    "verbatimModuleSyntax": true
  }
}
```

Use this mode for small scripts and carefully constrained runtime files. Use a
third-party runtime or build step when the project needs TSX, path aliases,
decorators, downlevel transforms, or full TypeScript syntax support.

## Typed Linting

typescript-eslint typed linting uses TypeScript's type checking APIs to power
rules that need type information. It is stronger than syntax-only linting, but
it costs more because TypeScript has to analyze the project.

- Prefer `recommendedTypeChecked` for a pragmatic baseline.
- Use `strictTypeChecked` only when the team and codebase can handle the added
  strictness.
- For typescript-eslint v8 and newer, `parserOptions.projectService: true` is
  the recommended parser option for typed linting.
- typescript-eslint currently documents ESLint support as
  `^8.57.0 || ^9.0.0 || ^10.0.0`, Node support as
  `^18.18.0 || ^20.9.0 || >=21.1.0`, and TypeScript support as the
  DefinitelyTyped less-than-two-years support window. Verify that page before
  changing dependencies.

## Framework Compatibility Examples

These examples are deliberately narrow. They show why agents must inspect the
project's pinned framework version before changing TypeScript or Node versions.

- Next.js installation docs list minimum Node.js `20.9` and minimum TypeScript
  `5.1.0`. Treat those as framework minimums, not a reason to target an older
  Node line when the latest LTS works.
- Vite guide docs list Node.js `20.19+` or `22.12+`. The Vite 8 announcement
  says Vite 8 keeps the same Node requirements as Vite 7.
- Angular compatibility docs for Angular `21.0.x` list Node
  `^20.19.0 || ^22.12.0 || ^24.0.0` and TypeScript `>=5.9.0 <6.0.0`.

## Practical Defaults

- For applications: run type checking, linting, tests, and a production build
  before claiming a TypeScript quality change is validated.
- For libraries: include declaration emit or package build validation when the
  public API types may change.
- For scripts: if using native Node type stripping, add or preserve a typecheck
  command because Node will run code with type errors.
- For monorepos: validate the affected package and at least one dependent
  package when exported types changed.

## Source URLs

- TypeScript 6.0 announcement:
  https://devblogs.microsoft.com/typescript/announcing-typescript-6-0/
- npm TypeScript package:
  https://www.npmjs.com/package/typescript
- Node release schedule:
  https://github.com/nodejs/Release
- Node releases page:
  https://nodejs.org/en/about/previous-releases
- Node TypeScript documentation:
  https://nodejs.org/api/typescript.html
- TypeScript `erasableSyntaxOnly` TSConfig reference:
  https://www.typescriptlang.org/tsconfig/erasableSyntaxOnly.html
- typescript-eslint dependency versions:
  https://typescript-eslint.io/users/dependency-versions/
- typescript-eslint typed linting:
  https://typescript-eslint.io/getting-started/typed-linting/
- Next.js installation:
  https://nextjs.org/docs/app/getting-started/installation
- Vite guide:
  https://vite.dev/guide/
- Vite 8 announcement:
  https://vite.dev/blog/announcing-vite8
- Angular version compatibility:
  https://angular.dev/reference/versions
