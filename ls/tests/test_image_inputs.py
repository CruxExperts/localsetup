import base64
from dataclasses import replace
import hashlib
import threading

import pytest

from ls.core.agent import image_inputs
from ls.core.agent.file_broker import FileBroker
from ls.core.agent.coding_protocol import request
from ls.tests.test_coding_protocol import payload
from ls.tests.test_session_owner import state,own,broker

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


def test_image_bytes_and_capability_contract(state,broker):
    (broker.grant.root/'src/pixel.png').write_bytes(PNG)
    allowed=FileBroker(replace(broker.grant,disclose=('src',)),broker.lease_root)
    with own(state,broker) as owner:
        images=image_inputs.load(owner,allowed,['src/pixel.png'])
        assert image_inputs.validate(images)==[(PNG,'image/png')]
        assert images[0]['sha256']==hashlib.sha256(PNG).hexdigest() and owner.inspect()=={}
        with pytest.raises(PermissionError):image_inputs.load(owner,broker,['src/pixel.png'])
    value=payload();value['images']=images
    with pytest.raises(ValueError,match='image support'):request(value)
    value['profile']['capabilities'].append('images');request(value)
    images[0]['sha256']='0'*64
    with pytest.raises(ValueError):request(value)


def test_refuse_oversize_unsafe_format_and_final_revocation(state,broker,monkeypatch):
    root=broker.grant.root;path=root/'src/image';path.write_bytes(b'not an image')
    revoked=threading.Event();allowed=FileBroker(replace(broker.grant,disclose=('src',),revoked=revoked),broker.lease_root)
    with own(state,broker) as owner:
        with pytest.raises(ValueError,match='PNG or JPEG'):image_inputs.load(owner,allowed,['src/image'])
        path.write_bytes(PNG+b'x'*image_inputs.MAX_IMAGE)
        with pytest.raises(ValueError,match='512 KiB'):image_inputs.load(owner,allowed,['src/image'])
        path.write_bytes(PNG)
        validate=image_inputs.validate
        def expired(images):
            result=validate(images);revoked.set();return result
        monkeypatch.setattr(image_inputs,'validate',expired)
        with pytest.raises(PermissionError,match='revoked'):image_inputs.load(owner,allowed,['src/image'])
    for values in [['x']*5,['x','x'],['../x']]:
        with pytest.raises((ValueError,PermissionError)):image_inputs.paths(values)
