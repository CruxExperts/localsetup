"""Generate SDK response contracts for independently installed storage skills."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXCLUDED = {"Body", "SSEKMSKeyId", "SSEKMSEncryptionContext", "BucketKeyEnabled"}
REQUIRED = {"ListBuckets": "Buckets", "PutObject": "ETag", "CreateMultipartUpload": "UploadId", "UploadPart": "ETag", "UploadPartCopy": "CopyPartResult", "CopyObject": "CopyObjectResult", "CompleteMultipartUpload": "ETag", "HeadObject": "ContentLength"}


def _shape(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    if value.type_name == "structure":
        properties = {name: _shape(member) for name, member in value.members.items() if name not in EXCLUDED}
        return {"type": "object", "additionalProperties": False, "properties": properties, "required": [name for name in value.required_members if name in properties]}
    if value.type_name == "list":
        return {"type": "array", "items": _shape(value.member)}
    if value.type_name == "map":
        return {"type": "object", "additionalProperties": _shape(value.value)}
    return {"type": {"integer": "integer", "long": "integer", "boolean": "boolean", "float": "number", "double": "number"}.get(value.type_name, "string")}


def render(operations: list[str]) -> bytes:
    import botocore.session
    model = botocore.session.get_session().get_service_model("s3")
    values = {}
    for name in operations:
        if name not in model.operation_names:
            continue
        value = _shape(model.operation_model(name).output_shape)
        value["properties"]["ResponseMetadata"] = {"type": "object", "additionalProperties": False, "properties": {"HTTPStatusCode": {"type": "integer"}, "RequestId": {"type": "string"}, "RetryAttempts": {"type": "integer"}}}
        if name in REQUIRED:
            value["required"] = sorted(set(value.get("required", [])) | {REQUIRED[name]})
        values[name] = value
    return (json.dumps({"schema_version": 1, "source": "locked botocore S3 output model; excludes bodies, KMS, bucket keys and raw HTTP headers", "operations": values}, sort_keys=True, separators=(",", ":")) + "\n").encode()


def update(root: Path, *, check: bool = False) -> None:
    import subprocess
    import sys
    for provider in ("backblaze", "garage"):
        base = root / "ls" / "skills" / ("ls-" + provider) / "scripts"
        entry = base / (provider + ".py")
        if not entry.exists():
            continue
        result = subprocess.run([sys.executable, str(entry), "--capabilities"], check=True, capture_output=True, text=True)
        operations = json.loads(result.stdout)["operations"]["s3"]
        destination = base / "lib" / ("ls_" + provider) / "s3-result-shapes.json"
        expected = render(operations)
        if check:
            if destination.read_bytes() != expected:
                raise ValueError(f"SDK result contract drift: {destination}")
        else:
            if destination.is_symlink():
                raise ValueError("refusing symlink SDK result contract")
            destination.write_bytes(expected)
