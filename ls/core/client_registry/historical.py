from __future__ import annotations


# Historical repo skill roots that Localsetup previously managed for supported
# clients. Keeping this alongside the canonical client registry prevents plan,
# repair, verification, and lock-recording transitions from drifting apart.
HISTORICAL_ADAPTERS: dict[str, tuple[dict[str, str], ...]] = {
    "codex": (
        {"id": "codex-skills-v1", "path": ".codex/skills", "replacement": ".agents/skills"},
    ),
    "openclaw": (
        {"id": "openclaw-skills-v1", "path": ".openclaw/skills", "replacement": ".agents/skills"},
    ),
}


def historical_adapter_paths() -> dict[str, list[str]]:
    return {
        platform_id: [str(item["path"]) for item in transitions]
        for platform_id, transitions in HISTORICAL_ADAPTERS.items()
    }
