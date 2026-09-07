"""Explicit bounded image-byte disclosure; no URL fetching or image decoding."""
import base64
import hashlib

from .file_grants import relative

MAX_IMAGE=512*1024


def media(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=24 and raw[12:16]==b'IHDR':
        return 'image/png'
    if raw.startswith(b'\xff\xd8\xff') and raw.endswith(b'\xff\xd9'):
        return 'image/jpeg'
    raise ValueError('Image requires a PNG or JPEG envelope')


def paths(values):
    if not isinstance(values,list) or len(values)>4 or any(not isinstance(v,str) for v in values) or len(set(values))!=len(values):
        raise ValueError('Select at most four distinct images')
    for value in values:relative(value)
    return values


def validate(images):
    if not isinstance(images,list) or len(images)>4:
        raise ValueError('Invalid image inventory')
    names=[];total=0;decoded=[]
    for value in images:
        if not isinstance(value,dict) or set(value)!={'path','media_type','sha256','data'} or not isinstance(value['data'],str) or len(value['data'])>4*((MAX_IMAGE+2)//3):
            raise ValueError('Invalid image request fields or size')
        raw=base64.b64decode(value['data'],validate=True);total+=len(raw)
        if len(raw)>MAX_IMAGE or total>4*MAX_IMAGE or media(raw)!=value['media_type'] or hashlib.sha256(raw).hexdigest()!=value['sha256']:
            raise ValueError('Image identity or format differs from its bytes')
        names.append(value['path']);decoded.append((raw,value['media_type']))
    paths(names)
    return decoded


def load(owner,broker,names):
    names=paths(names);images=[]
    with owner._operation():
        bound=owner._broker(broker);grant=bound.grant
        def check():
            for name in names:grant.check(grant.task,grant.session,'read',name,provider=True)
            owner._check()
        check()
        for name in names:
            raw=bound.read(grant.task,grant.session,name,for_provider=True)
            if len(raw)>MAX_IMAGE:raise ValueError('Image exceeds 512 KiB')
            images.append({'path':name,'media_type':media(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                           'data':base64.b64encode(raw).decode('ascii')})
        validate(images);check()
        return images
