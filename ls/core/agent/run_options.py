"""Public run arguments, without importing the SDK or initializing a provider."""
from pathlib import Path


def arguments(parser):
    parser.add_argument('--profile', required=True)
    parser.add_argument('--profiles', type=Path)
    parser.add_argument('--grant', type=Path, required=True, help='Explicit private read/write/disclosure and recipe JSON')
    parser.add_argument('--prompt-stdin', action='store_true', required=True)
    parser.add_argument('--format', choices=('text','jsonl'), default='text')
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('--resource-parent', type=Path, required=True)
    parser.add_argument('--approve-tools', action='store_true', help='Require one-use owner approval for each tool request (control FD and JSONL required)')
    parser.add_argument('--control-fd', type=int, help='Inherited local stream socket for schema-1 status/cancel messages')
    parser.add_argument('--task')
    parser.add_argument('--session')
    history=parser.add_mutually_exclusive_group()
    history.add_argument('--resume',metavar='CHECKPOINT')
    history.add_argument('--recover-from',metavar='CHECKPOINT')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--request-limit', type=int, default=8)
    parser.add_argument('--tool-limit', type=int, default=16)
    parser.add_argument('--token-limit', type=int, default=32768)


def defaults(args):
    from .diagnostics import locations
    found = locations(Path.home())
    args.runtime_root = (args.runtime_root or Path(found['runtimes'])).absolute()
    args.state_root = (args.state_root or Path(found['state'])).absolute()
    args.profiles = (args.profiles or Path(found['profiles'])).absolute()
    args.grant = args.grant.absolute()
    args.workspace = args.workspace.absolute()
    args.resource_parent = args.resource_parent.absolute()
    return args
