"""Isolated installed SDK portable-conversion worker, with no provider client."""
from pathlib import Path
import hashlib
import socket
import sys

from .broker_rpc import Channel, _encode
from .portable_history import METHODS
from .sdk_imports import activate


def main():
    channel = None
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode or len(sys.argv) != 5:
            raise ValueError('Portable conversion requires isolated worker invocation')
        package = Path(__file__).resolve().parents[2]
        if not package.is_relative_to(Path(sys.prefix).resolve()):
            raise ValueError('Portable conversion requires installed runtime')
        channel = Channel(socket.socket(fileno=int(sys.argv[1])), task=sys.argv[2], session=sys.argv[3],
                          methods=METHODS, expires=float(sys.argv[4]))
        finder = activate(package/'_sdk_payload')
        request = channel.request('portable.start', {})
        if not isinstance(request, dict) or set(request) != {'input_sha256', 'payload'}:
            raise ValueError('Invalid portable request')
        payload = request['payload']
        if hashlib.sha256(_encode(payload)).hexdigest() != request['input_sha256'] or not isinstance(payload,dict) or set(payload) != {'history','images'}:
            raise ValueError('Portable request identity differs')
        from .sdk_portable import convert
        messages = convert(finder, payload['history'].encode(), images=payload['images'])
        receipt = {'messages_sha256':hashlib.sha256(messages).hexdigest()}
        if channel.request('portable.finish', {'input_sha256':request['input_sha256'], 'messages':messages.decode()}) != receipt:
            raise ValueError('Portable acknowledgement differs')
        finder.verify_origins()
        print(_encode(receipt).decode())
        return 0
    except Exception:
        print('Portable conversion failed; original history retained.',file=sys.stderr)
        return 2
    finally:
        if channel is not None: channel.close()


if __name__ == '__main__':
    raise SystemExit(main())
