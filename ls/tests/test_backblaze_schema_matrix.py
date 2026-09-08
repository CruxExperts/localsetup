"""Schemas constrain every published operation, with independent JSONSchema checks."""
from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator
from test_backblaze_matrix import NATIVE_ARGS, S3_ARGS
from ls_backblaze import validation
from ls_backblaze.reporting import ToolError

CASES = {**{"s3." + name: args for name, args in S3_ARGS.items()}, **{"native." + name: args for name, args in NATIVE_ARGS.items()}}


@pytest.mark.parametrize("operation,args", CASES.items())
def test_valid_requests_and_every_required_field_agree(operation, args):
    schema = validation.request_schema()
    validator = Draft202012Validator(schema)
    validator.validate({"operation": operation, "args": args})
    validation.validate(operation, args)
    branch = next(item for item in schema["oneOf"] if item["properties"]["operation"]["const"] == operation)
    for field in branch["properties"]["args"]["required"]:
        broken = {key: value for key, value in args.items() if key != field}
        assert not validator.is_valid({"operation": operation, "args": broken}), (operation, field)
        with pytest.raises(ToolError): validation.validate(operation, broken)
    for field in branch["properties"]["args"]["properties"]:
        broken = {**args, field: None}
        assert not validator.is_valid({"operation": operation, "args": broken}), (operation, field)
        with pytest.raises(ToolError): validation.validate(operation, broken)


@pytest.mark.parametrize("operation,args", [
    ("s3.PutObject", {"bucket": "example.bucket", "key": "key", "source": "/file", "metadata": {"x": True}}),
    ("s3.PutObject", {"bucket": "example.bucket", "key": "key", "source": "/file", "encryption": {"algorithm": "SSE-C", "key": "raw"}}),
    ("s3.PutBucketCors", {"bucket": "example.bucket", "cors_rules": [{"AllowedMethods": ["GET", 1], "AllowedOrigins": [5]}]}),
    ("s3.PutObjectLockConfiguration", {"bucket": "example.bucket", "configuration": {"ObjectLockEnabled": "Enabled", "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE"}}}}),
    ("s3.DeleteObjects", {"bucket": "example.bucket", "objects": [{"key": "key", "version_id": 4}]}),
    ("native.CreateKey", {"key_name": "***", "capabilities": ["listBuckets"], "secret_output": "/file"}),
])
def test_nested_invalid_inputs_reject_in_both_interfaces(operation, args):
    assert not Draft202012Validator(validation.request_schema()).is_valid({"operation": operation, "args": args})
    with pytest.raises(ToolError): validation.validate(operation, args)
