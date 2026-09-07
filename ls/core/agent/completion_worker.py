"""Installed isolated direct completion; credentials arrive only through owner RPC."""
import asyncio
import hashlib
from pathlib import Path
import socket
import sys

from .broker_rpc import Channel,_encode
from .completion_run import METHODS,identity
from .completion_contract import envelope
from .profiles import parse
from .sdk_imports import activate


def main():
    channel=None
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode or len(sys.argv)!=5:
            raise ValueError('Completion requires isolated invocation')
        package=Path(__file__).resolve().parents[2]
        if not package.is_relative_to(Path(sys.prefix).resolve()):raise ValueError('Completion requires installed runtime')
        expires=float(sys.argv[4])
        channel=Channel(socket.socket(fileno=int(sys.argv[1])),task=sys.argv[2],session=sys.argv[3],methods=METHODS,expires=expires)
        finder=activate(package/'_sdk_payload')
        value=channel.request('complete.start',{})
        if not isinstance(value,dict) or set(value)!={'input_sha256','payload'} or identity(value['payload'])!=value['input_sha256']:
            raise ValueError('Completion request identity differs')
        payload=value['payload'];profile=parse(payload['profile'])
        from .sdk_completion import complete
        try:
            result=asyncio.run(complete(profile,{profile.credential_env:payload['credential']},finder,payload['request'].encode(),expires=expires,check=channel._check))
        except ValueError:result=envelope('invalid_request',model=profile.model)
        receipt={'result_sha256':hashlib.sha256(_encode(result)).hexdigest()}
        if channel.request('complete.finish',{'input_sha256':value['input_sha256'],'result':result})!=receipt:
            raise ValueError('Completion acknowledgement differs')
        finder.verify_origins();print(_encode(receipt).decode());return 0
    except Exception:
        print('Completion worker failed.',file=sys.stderr);return 2
    finally:
        if channel is not None:channel.close()


if __name__=='__main__':raise SystemExit(main())
