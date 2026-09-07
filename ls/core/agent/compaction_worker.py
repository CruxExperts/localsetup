"""Installed isolated compaction worker; credentials arrive only over owner RPC."""
import asyncio
import hashlib
from pathlib import Path
import socket
import sys

from .broker_rpc import Channel,_encode
from .compaction_run import METHODS,request
from .sdk_imports import activate


def main():
    channel=None
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode or len(sys.argv)!=5:
            raise ValueError('Compaction requires isolated worker invocation')
        package=Path(__file__).resolve().parents[2]
        if not package.is_relative_to(Path(sys.prefix).resolve()):raise ValueError('Compaction requires installed runtime')
        expires=float(sys.argv[4])
        channel=Channel(socket.socket(fileno=int(sys.argv[1])),task=sys.argv[2],session=sys.argv[3],methods=METHODS,expires=expires)
        finder=activate(package/'_sdk_payload')
        value=channel.request('compact.start',{})
        if not isinstance(value,dict) or set(value)!={'input_sha256','payload'} or request(value['payload'])!=value['input_sha256']:
            raise ValueError('Compaction request identity differs')
        payload=value['payload']
        from .profiles import parse
        from .sdk_models import model
        from .sdk_compaction import compact
        profile=parse(payload['profile'])
        async def run():
            async with model(profile,{profile.credential_env:payload['credential']},finder) as adapter:
                return await compact(adapter,finder,payload['history'].encode(),keep_messages=payload['keep_messages'],token_limit=payload['token_limit'],expires=expires,check=channel._check)
        result=asyncio.run(run())
        usage={k:result['usage'][k] for k in ('requests','tool_calls','input_tokens','output_tokens')}
        receipt={'messages_sha256':hashlib.sha256(result['messages']).hexdigest(),'usage':usage}
        if channel.request('compact.finish',{'input_sha256':value['input_sha256'],'messages':result['messages'].decode(),'summary':result['summary'],'usage':usage})!=receipt:
            raise ValueError('Compaction acknowledgement differs')
        finder.verify_origins();print(_encode(receipt).decode());return 0
    except Exception:
        print('Compaction worker failed; original checkpoint retained.',file=sys.stderr);return 2
    finally:
        if channel is not None:channel.close()


if __name__=='__main__':raise SystemExit(main())
