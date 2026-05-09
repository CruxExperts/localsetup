# Agent Q transport client – API examples

## Python: read framework version

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("_localsetup/tools/agentq_transport_client")))
sys.path.insert(0, "_localsetup")
from agentq_transport_client.version_util import read_framework_version, read_framework_hash

print(read_framework_version())
print(read_framework_hash())
```

## Python: stamp PRD

```python
from pathlib import Path
# After sys.path setup as above
from agentq_transport_client.prd_stamp import ensure_prd_stamp
ensure_prd_stamp(Path(".agent/queue/my.prd.md"), add_hash=True)
```

## CLI equivalents

```bash
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py version
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py stamp-prd .agent/queue/my.prd.md --hash
```
