"""Installed isolated local recovery worker; no providers or tools are initialized."""
from __future__ import annotations

import hashlib
from pathlib import Path
import socket
import sys

from .broker_rpc import Channel, _encode
from .recovery import METHODS
from .sdk_imports import activate


def main():
    channel = None
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode or len(sys.argv) != 5:
            raise ValueError('Recovery requires isolated worker invocation')
        package = Path(__file__).resolve().parents[2]
        if not package.is_relative_to(Path(sys.prefix).resolve()):
            raise ValueError('Recovery requires an installed runtime')
        channel = Channel(socket.socket(fileno=int(sys.argv[1])), task=sys.argv[2], session=sys.argv[3],
                          methods=METHODS, expires=float(sys.argv[4]))
        finder = activate(package/'_sdk_payload')
        request = channel.request('recovery.start', {})
        if not isinstance(request, dict) or set(request) != {'input_sha256', 'payload'}:
            raise ValueError('Invalid recovery request')
        payload = request['payload']
        if hashlib.sha256(_encode(payload)).hexdigest() != request['input_sha256'] or not isinstance(payload, dict) or set(payload) != {'history', 'receipts', 'recipes'}:
            raise ValueError('Recovery request identity mismatch')
        from .process_rpc import Recipe
        from .sdk_recovery import reconstruct
        recipes = {}
        for name, value in payload['recipes'].items():
            if not isinstance(value, dict) or set(value) != {'command', 'files', 'seconds'}:
                raise ValueError('Invalid recovery recipe schema')
            recipes[name] = Recipe(tuple(value['command']), tuple(value['files']), value['seconds'])
        messages = reconstruct(finder, payload['history'].encode(), payload['receipts'], recipes=recipes)
        receipt = {'messages_sha256': hashlib.sha256(messages).hexdigest()}
        if channel.request('recovery.finish', {'input_sha256': request['input_sha256'], 'messages': messages.decode()}) != receipt:
            raise ValueError('Recovery acknowledgement differs')
        finder.verify_origins()
        print(_encode(receipt).decode())
        return 0
    except Exception:
        print('Recovery worker failed; original evidence retained.', file=sys.stderr)
        return 2
    finally:
        if channel is not None:
            channel.close()


if __name__ == '__main__':
    raise SystemExit(main())
