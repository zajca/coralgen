"""Resolve PrusaSlicer system presets from a vendor bundle into one loadable config.

A vendor bundle (e.g. ~/.config/PrusaSlicer/vendor/PrusaResearch.ini) stores presets as sections
`[print:NAME]`, `[printer:NAME]`, `[filament:NAME]` that inherit from each other through
`inherits = A; B`. Parents are applied left to right, then the section's own keys. The merged
print + printer + filament config can be passed to the PrusaSlicer CLI with --load.
"""
from __future__ import annotations

import pathlib

# Keys that describe the preset itself, not slicing settings
_META_KEYS = {"inherits", "renamed_from", "compatible_printers", "compatible_printers_condition",
              "compatible_prints", "compatible_prints_condition", "alias", "visible"}


class ProfileError(ValueError):
    pass


def parse_bundle(path: pathlib.Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("[") and line.endswith("]"):
                current = sections.setdefault(line[1:-1], {})
            elif current is not None and " = " in line and not line.startswith("#"):
                key, val = line.split(" = ", 1)
                current[key.strip()] = val
            elif current is not None and line.endswith(" =") and not line.startswith("#"):
                current[line[:-2].strip()] = ""
    return sections


def resolve(sections: dict[str, dict[str, str]], kind: str, name: str,
            _stack: tuple[str, ...] = ()) -> dict[str, str]:
    key = f"{kind}:{name}"
    if key not in sections:
        raise ProfileError(f"preset [{key}] not found in the vendor bundle")
    if key in _stack:
        raise ProfileError(f"inheritance cycle: {' -> '.join(_stack + (key,))}")
    own = sections[key]
    merged: dict[str, str] = {}
    for parent in filter(None, (p.strip() for p in own.get("inherits", "").split(";"))):
        merged.update(resolve(sections, kind, parent, _stack + (key,)))
    merged.update(own)
    return merged


def merged_config(bundle: pathlib.Path, print_preset: str, printer_preset: str,
                  filament_preset: str) -> dict[str, str]:
    sections = parse_bundle(bundle)
    out: dict[str, str] = {}
    for kind, name in (("printer", printer_preset), ("print", print_preset), ("filament", filament_preset)):
        out.update(resolve(sections, kind, name))
    return {k: v for k, v in out.items() if k not in _META_KEYS}


def write_ini(cfg: dict[str, str], path: pathlib.Path) -> None:
    path.write_text("".join(f"{k} = {v}\n" for k, v in sorted(cfg.items())), encoding="utf-8")


def bed_center(cfg: dict[str, str]) -> tuple[float, float]:
    """Centre of the bounding box of `bed_shape` (e.g. '0x0,180x0,180x180,0x180')."""
    if "bed_shape" not in cfg:
        raise ProfileError("resolved printer preset has no bed_shape")
    pts = [tuple(float(c) for c in p.split("x")) for p in cfg["bed_shape"].split(",")]
    xs, ys = zip(*pts)
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
