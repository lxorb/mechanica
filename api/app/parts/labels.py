"""The 30 classes of AswinG5/moto-parts-30cls and the manual query each one maps to."""

from typing import Literal, get_args

Label = Literal[
    "cylinder_head",
    "alternator",
    "clutch_plate",
    "chain_sprocket",
    "cylinder_block",
    "piston",
    "crankshaft",
    "camshaft",
    "spark_plug",
    "air_fin",
    "radiator",
    "motorcycle_frame",
    "forks",
    "swingarm",
    "shock_absorbers",
    "gear_box",
    "chain",
    "disc",
    "handlebar",
    "brake_clutch_lever",
    "brake_clutch_cable",
    "brake_pad",
    "battery_terminal",
    "fuse_box",
    "brake_light_switch",
    "gear_lever",
    "brake_pedal",
    "carburetor",
    "fuel_tank",
    "brake_oil_reservoir",
]

LABELS: list[str] = list(get_args(Label))

QUERY: dict[str, str] = {
    "cylinder_head": "cylinder head",
    "alternator": "alternator",
    "clutch_plate": "clutch",
    "chain_sprocket": "sprocket wear",
    "cylinder_block": "cylinder",
    "piston": "piston",
    "crankshaft": "crankshaft",
    "camshaft": "camshaft",
    "spark_plug": "spark plug",
    "air_fin": "engine cooling fins",
    "radiator": "coolant level",
    "motorcycle_frame": "frame number",
    "forks": "fork oil",
    "swingarm": "swingarm",
    "shock_absorbers": "rear shock preload",
    "gear_box": "gearbox oil",
    "chain": "chain tension",
    "disc": "brake disc",
    "handlebar": "handlebar",
    "brake_clutch_lever": "lever adjustment",
    "brake_clutch_cable": "clutch cable play",
    "brake_pad": "brake pads",
    "battery_terminal": "battery",
    "fuse_box": "fuses",
    "brake_light_switch": "brake light",
    "gear_lever": "gear lever",
    "brake_pedal": "rear brake pedal",
    "carburetor": "carburetor",
    "fuel_tank": "fuel tank",
    "brake_oil_reservoir": "brake fluid level",
}

ALIASES: dict[str, str] = {
    "chain_sprocket": "chain and sprocket",
    "air_fin": "air cooling fin",
    "disc": "brake disc / rotor",
    "brake_clutch_lever": "brake or clutch hand lever",
    "brake_clutch_cable": "brake or clutch cable",
    "brake_oil_reservoir": "brake fluid reservoir",
    "gear_box": "gearbox / transmission",
    "motorcycle_frame": "bare frame / chassis",
    "battery_terminal": "battery and its terminals",
    "forks": "front forks",
}


def query(label: str) -> str:
    return QUERY.get(label, label.replace("_", " "))


def described() -> str:
    return "\n".join(f"- {l}" + (f" ({ALIASES[l]})" if l in ALIASES else "") for l in LABELS)
