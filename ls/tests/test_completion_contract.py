import json
import pytest
from ls.core.agent.completion_contract import parse, validate_output, envelope, EXITS
from ls.core.agent.profiles import parse as profile_parse


def fixture():
    profile=profile_parse({'base_url':'https://fixture.invalid/v1/','api':'responses','model':'fixture',
        'credential_env':'KEY','timeout_seconds':5,'capabilities':['native_schema'],'allow_loopback_http':False})
    value={'interface_version':1,'model':'fixture','deadline_seconds':30,'max_attempts':1,
        'max_output_tokens':100,'input':{'facts':[]},'output_schema':{'type':'object',
        'required':['ok'],'properties':{'ok':{'type':'boolean'}},'additionalProperties':False}}
    return profile,value


def test_completion_request_and_output_contract():
    profile,value=fixture();request=parse(json.dumps(value).encode(),profile)
    assert validate_output('{"ok":true}',request)==('succeeded',{'ok':True})
    for text,status in [('{','malformed'),('\ud800','malformed'),('{"ok":true,"ok":false}','malformed'),
                        ('{"ok":"yes"}','schema_rejected'),('x'*1048577,'output_limit')]:
        assert validate_output(text,request)==(status,None)
    assert envelope('refused',data={'secret':'not retained'})['data'] is None
    assert len(set(EXITS.values()))==len(EXITS)


@pytest.mark.parametrize('change',[
    {'interface_version':True},{'max_attempts':2},{'deadline_seconds':False},
    {'model':'other'},{'max_output_tokens':0},{'unexpected':1},
    {'output_schema':{'$ref':'https://fixture.invalid/schema'}},
    {'output_schema':{'$id':'https://fixture.invalid/schema'}},
    {'output_schema':{'$ref':'#/$defs/missing'}},
    {'output_schema':{'$ref':'#missing-anchor'}},
    {'output_schema':{'type':'not-a-type'}},
])
def test_completion_preflight_refuses_invalid_requests(change):
    profile,value=fixture()
    with pytest.raises(ValueError):parse(json.dumps(value|change).encode(),profile)


def test_completion_native_capability_and_local_schema_refs():
    from dataclasses import replace
    profile,value=fixture();profile=replace(profile,capabilities=frozenset())
    with pytest.raises(ValueError):parse(json.dumps(value).encode(),profile)
    value.update(schema_mode='validate_only',output_schema={'$defs':{'flag':{'type':'boolean'}},'$ref':'#/$defs/flag'})
    request=parse(json.dumps(value).encode(),profile)
    assert validate_output('true',request)==('succeeded',True)
    assert validate_output('1',request)==('schema_rejected',None)


def test_completion_percent_encoded_local_pointer_resolution():
    profile,value=fixture()
    value['output_schema']={'$defs':{'a b':{'type':'boolean'}},'$ref':'#/$defs/a%20b'}
    request=parse(json.dumps(value).encode(),profile)
    assert validate_output('true',request)==('succeeded',True)
    value['output_schema']={'$defs':{'a%20b':{}},'$ref':'#/$defs/a%20b'}
    with pytest.raises(ValueError):parse(json.dumps(value).encode(),profile)
