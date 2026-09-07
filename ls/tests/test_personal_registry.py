import pytest
from ls.core.registry import upsert_target, remove_target, load_registry, package_has_other_refs


def test_personal_refs_survive_repository_removal_and_reselection(tmp_path):
    registry = tmp_path / "registry.json";target = tmp_path / "repo"
    packages = [tmp_path / "packages" / name for name in ("ls-one", "ls-two")]
    for package in packages:package.mkdir(parents=True)
    owner = {"scope": "personal", "root": str(tmp_path), "client": "fixture"}
    def apply(names, owners):
        return upsert_target(registry, target_root=target, source_commit="fixture", package_paths=packages,
                             adapter_targets=[{"path": str(tmp_path / "skills"), "owners": owners, "packages": names}])
    value = apply(["ls-one"], [owner, owner])
    assert len(value["personal_owners"]) == 1
    assert package_has_other_refs(value, "ls-one", target_root=target)
    assert not package_has_other_refs(value, "ls-two", target_root=target)
    value = apply(["ls-two"], [owner])
    assert not package_has_other_refs(value, "ls-one", target_root=target)
    assert package_has_other_refs(value, "ls-two", target_root=target)
    value = remove_target(registry, target_root=target)
    assert not value["targets"] and set(value["packages"]) == {"ls-two"}
    assert len(value["personal_owners"]) == 1
    # A repository-only update does not implicitly detach personal ownership.
    value = apply([], [])
    assert package_has_other_refs(value, "ls-two", target_root=target)
    before = registry.read_bytes()
    with pytest.raises(ValueError):apply(["ls-missing"], [owner])
    assert registry.read_bytes() == before


def test_empty_personal_owner_and_distinct_clients_survive(tmp_path):
    registry = tmp_path / "registry.json";target = tmp_path / "repo"
    owners = [{"scope": "personal", "root": str(tmp_path), "client": client} for client in ("one", "two")]
    value = upsert_target(registry, target_root=target, source_commit="fixture", package_paths=[],
                          adapter_targets=[{"path": str(tmp_path / "skills"), "owners": owners, "packages": []}])
    assert len(value["personal_owners"]) == 2
    remove_target(registry, target_root=target)
    assert len(load_registry(registry)["personal_owners"]) == 2
