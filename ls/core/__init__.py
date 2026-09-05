"""LocalSetup core package with a lazy CLI compatibility export."""

__all__ = ["main"]


def __getattr__(name: str):
    if name == "main":
        from .cli import main

        globals()[name] = main
        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
