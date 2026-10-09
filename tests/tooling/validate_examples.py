"""Validate the Conditioning Layers examples offline with the retained host dependency lane.

Run with pinned host Python, -X utf8 -B -W error. No models, host imports,
network, subprocesses, sampling or generation. Brush and codec checks are in
validate_examples.mjs.
"""
from contextlib import ExitStack
import importlib
import itertools
import json
from pathlib import Path
import re
import struct
import sys
from unittest.mock import patch

from offline_regressions import FENCES, fence

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "examples/conditioning-layers"
P = "ConditioningLayers"
EXPECTED = {  # layers, Painted Fields, required field node types
    "01_one_influence_field": (2, 0, {"EllipseField", "SolidField"}),
    "02_two_fixed_regions": (2, 0, {"RectangleField"}),
    "03_blended_gradients": (3, 0, {"LinearGradientField", "RadialGradientField"}),
    "04_transform_repeat_fade_remap": (2, 0, {"RectangleField", "FieldRepeat", "FieldTransform", "FieldFade", "FieldRemap", "FieldBlur", "SolidField"}),
    "05_patterns_and_templates": (5, 1, {"PatternField", "InvertField", "PresetField", "FieldTransform", "PaintedField"}),
    "06a_painted_field_start": (2, 1, {"PaintedField", "SolidField"}),
    "06b_painted_field_completed": (2, 1, {"PaintedField", "SolidField"}),
    "07_advanced_brushes": (6, 5, {"PaintedField", "SolidField"}),
    "08_multi_field_painting": (5, 4, {"PaintedField", "SolidField"}),
    "09_nine_layer_showcase": (9, 4, {"RectangleField", "RadialGradientField", "LinearGradientField", "FieldFade", "NoiseField",
                                      "FieldRemap", "PatternField", "FieldRepeat", "InvertField", "FieldTransform", "PaintedField"}),
}
MIN_NOTES = {'01_one_influence_field': 6, '02_two_fixed_regions': 6, '03_blended_gradients': 6, '04_transform_repeat_fade_remap': 6, '05_patterns_and_templates': 9, '06a_painted_field_start': 7, '06b_painted_field_completed': 7, '07_advanced_brushes': 13, '08_multi_field_painting': 12, '09_nine_layer_showcase': 15}
MODULES = ("influence_field_sources", "pattern_field_source", "preset_field_source",
           "procedural_field_sources", "field_transform", "field_repeat", "field_fade",
           "field_blur", "field_remap", "painted_field_source", "prediction_mixing.layer_nodes.nodes")
BUILTINS = {"UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "EmptyLatentImage",
            "KSampler", "VAEDecode", "SaveImage", "Note"}
NOTE_KINDS = {"WHAT THIS SHOWS", "TRY THIS", "IMPORTANT"}
PLACEHOLDERS = {"SELECT_KREA_2_MODEL.safetensors", "SELECT_KREA_2_TEXT_ENCODER.safetensors", "SELECT_COMPATIBLE_VAE.safetensors"}
# Static style vocabulary for the prompt-diversity checks; tags, not language understanding.
STYLES = {"oil painting": r"\boil (painting|portrait)|old master|impasto", "watercolor": r"watercolou?r",
          "charcoal": r"charcoal", "photograph": r"photograph|photoreal|film still|product.photo",
          "airbrush": r"airbrush", "advertising": r"advertis", "poster": r"poster", "vector": r"\bvector\b",
          "neon": r"\bneon\b", "ceramic": r"ceramic|pottery|glazed", "chrome": r"\bchrome\b",
          "clay": r"stop-motion|plasticine|\bclay\b", "halftone print": r"halftone|print collage",
          "cartoon": r"cartoon|storybook", "mosaic": r"mosaic", "illustration": r"illustration",
          "dreamlike": r"dreamlike", "starlight": r"starlight|constellation", "hand-painted": r"hand-painted",
          "enamel": r"enamel"}
STOP = {"and", "the", "with", "into", "from", "like", "its", "each", "for", "one", "out"}


def require(value, message):
    if not value:
        raise ValueError(message)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)


def private_check(value, *, workflow=True):
    for text in strings(value):
        if text.startswith("data:image/png;base64,"):
            continue
        require(not re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\|/Users/|/home/|AppData|@|host-state-diagnostic", text, re.I),
                "Nonportable/private string")
        require(not re.search(r"showcase[ _-]*v[12]|examples[ _-]*v[12]", text, re.I), "Versioned example branding")
        if workflow:
            require(not re.search(r"e10b|e10c|simultaneous|transfer|balance|active.share|normalize.brush|redistribut|cross.field.stroke",
                                  text, re.I), "Unexpected session-operation marker in saved workflow")


def words(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in STOP}


def similarity(a, b):
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb)


def styles(text):
    return {tag for tag, pattern in STYLES.items() if re.search(pattern, text, re.I)}


def registry():
    result = {}
    for module in MODULES:
        imported = importlib.import_module("conditioning_layers.comfyui." + module)
        for name, cls in vars(imported).items():
            if name.startswith(P) and isinstance(cls, type) and hasattr(cls, "INPUT_TYPES"):
                result[name] = cls
    return result


def overlaps(a, b, gap=0):
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def validate(path, classes):
    from conditioning_layers.comfyui.prediction_mixing import DEFAULT_SUPPORTED_PROFILE
    from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code
    from conditioning_layers.comfyui.prediction_mixing.layer_nodes import compose_field_codes, LayerMode
    from conditioning_layers.comfyui.prediction_mixing.inventory import NODE_CONTRACTS
    data = json.loads(path.read_text(encoding="utf-8"))
    private_check(data)
    require(data["version"] == 0.4 and data["groups"], "Workflow format/groups")
    nodes = {n["id"]: n for n in data["nodes"]}
    links = {link[0]: link for link in data["links"]}
    require(len(nodes) == len(data["nodes"]) and len(links) == len(data["links"]), "Duplicate IDs")
    require(data["last_node_id"] == max(nodes) and data["last_link_id"] == max(links), "Last IDs")
    layer_count, painted_count, types = EXPECTED[path.stem]
    require({P + t for t in types} <= {n["type"] for n in nodes.values()}, "Feature types missing")
    layers = [n for n in nodes.values() if n["type"] == P + "Layer"]
    painted = [n for n in nodes.values() if n["type"] == P + "PaintedField"]
    require(len(layers) == layer_count and len(painted) == painted_count, "Layer/Painted Field count")

    # Notes: retain the teaching-note minimum for each official example.
    notes = [n for n in nodes.values() if n["type"] == "Note"]
    tag = path.stem.split("_")[0].upper()
    titles = [n for n in notes if n.get("title") == f"CONDITIONING LAYERS — EXAMPLE {tag}"]
    kinds = [n.get("title") for n in notes if n not in titles]
    require(len(titles) == 1 and set(kinds) <= NOTE_KINDS, "Note titles")
    require("WHAT THIS SHOWS" in kinds and "TRY THIS" in kinds, "WHAT THIS SHOWS / TRY THIS notes")
    require(all(n["widgets_values"][0].strip() and len(n["widgets_values"][0]) <= 420 for n in notes), "Empty or overlong note")
    require(any("SELECT" in n["widgets_values"][0] and "Krea 2" in n["widgets_values"][0] for n in notes), "Model note")
    require(len(notes) >= MIN_NOTES[path.stem], "Missing example teaching notes")

    arguments = {}
    for n in nodes.values():
        typ = n["type"]
        require(typ in classes or typ in BUILTINS, "Unknown node: " + typ)
        require(n["mode"] == 0 and not n["flags"].get("collapsed"), "Hidden/bypassed node")
        require(len(n["pos"]) == len(n["size"]) == 2 and min(n["size"]) > 0, "Layout")
        args = {}
        for slot, inp in enumerate(n["inputs"]):
            if inp["link"] is None:
                require(typ == P + "AddLayer" and inp["name"] == "layers", "Orphan input")
                continue
            link = links[inp["link"]]
            require(link[3:5] == [n["id"], slot], "Target link mismatch")
            origin = nodes[link[1]]["outputs"][link[2]]
            require(link[0] in origin["links"] and origin["type"] == inp["type"] == link[5], "Socket type/link mismatch")
            args[inp["name"]] = (link[1], link[2])
        for output in n["outputs"]:
            for lid in output["links"]:
                require(links[lid][1] == n["id"], "Output back reference")
        if typ in classes:
            spec = classes[typ].INPUT_TYPES()
            widgets = iter(n["widgets_values"])
            for name, entry in spec["required"].items():
                t = entry[0]
                options = entry[1] if len(entry) > 1 else {}
                if isinstance(t, list) or t in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                    value = next(widgets)
                    if isinstance(t, list):
                        require(value in t, "Invalid combo")
                    elif t in ("INT", "FLOAT"):
                        require(type(value) is (int if t == "INT" else float), "Numeric widget type")
                        require(options.get("min", value) <= value <= options.get("max", value), "Widget range")
                    args[name] = value
                else:
                    require(name in args, "Required socket")
            require(next(widgets, None) is None, "Extra widgets")
        elif typ in NODE_CONTRACTS:
            require(set(args) == NODE_CONTRACTS[typ].link_inputs, "Built-in required sockets")
        arguments[n["id"]] = args
    loaders = [n["widgets_values"][0] for n in nodes.values() if n["type"] in ("UNETLoader", "CLIPLoader", "VAELoader")]
    require(sorted(loaders) == sorted(PLACEHOLDERS), "Portable loader placeholders")

    # Layout: no two node boxes (title bar included) or groups overlap; every executable node sits in a group.
    boxes = {n["id"]: (n["pos"][0], n["pos"][1] - 30, n["pos"][0] + n["size"][0], n["pos"][1] + n["size"][1]) for n in nodes.values()}
    for a, b in itertools.combinations(boxes, 2):
        require(not overlaps(boxes[a], boxes[b], 8), f"Overlapping node boxes {a}/{b}")
    groups = [(g["bounding"][0], g["bounding"][1], g["bounding"][0] + g["bounding"][2], g["bounding"][1] + g["bounding"][3])
              for g in data["groups"]]
    for a, b in itertools.combinations(groups, 2):
        require(not overlaps(a, b), "Overlapping groups")
    for nid, box in boxes.items():
        if nodes[nid]["type"] != "Note":
            require(any(g[0] <= box[0] and g[1] <= box[1] and box[2] <= g[2] and box[3] <= g[3] for g in groups), f"Ungrouped node {nid}")

    compositions = [n for n in nodes.values() if n["type"] == P + "Compose"]
    require(len(compositions) == 1, "Exactly one composition")
    stack = arguments[compositions[0]["id"]]["layers"][0]
    chain = []
    visited = set()
    while stack:
        require(stack not in visited and nodes[stack]["type"] == P + "AddLayer", "Invalid stack")
        visited.add(stack)
        chain.append(arguments[stack]["layer"][0])
        stack = arguments[stack].get("layers", (None,))[0]
    chain.reverse()
    require(len(set(chain)) == layer_count and set(chain) == {n["id"] for n in layers}, "Disconnected/duplicate layer")
    samplers = [n for n in nodes.values() if n["type"] == "KSampler"]
    require(len(samplers) == 1 and arguments[samplers[0]["id"]]["positive"][0] == compositions[0]["id"], "Composition path")
    inventory = DEFAULT_SUPPORTED_PROFILE.inventory
    require(samplers[0]["widgets_values"][1:] == ["fixed", inventory.steps, inventory.cfg,
            inventory.sampler_name, inventory.scheduler_name, inventory.denoise], "Retained sampler defaults")
    outputs = [n for n in nodes.values() if n["type"] == "SaveImage"]
    require(len(outputs) == 1 and outputs[0]["widgets_values"] == ["ConditioningLayers/" + path.stem], "Output prefix")

    evaluated = {}
    active = set()

    def field(node_id):
        if node_id in evaluated:
            return evaluated[node_id]
        require(node_id not in active, "Field cycle")
        active.add(node_id)
        n = nodes[node_id]
        cls = classes[n["type"]]
        require(cls.RETURN_TYPES == ("MASK",), "Unexpected field output")
        kwargs = {key: field(v[0]) if isinstance(v, tuple) else v for key, v in arguments[node_id].items()}
        result = getattr(cls(), cls.FUNCTION)(**kwargs)[0]
        require(tuple(result.shape) == (1, 128, 128), "Field shape")
        evaluated[node_id] = result
        active.remove(node_id)
        return result

    planes, modes, strengths = [], [], []
    for lid in chain:
        args = arguments[lid]
        require(args["enabled"] is True, "Example layer disabled")
        planes.append(tuple(recover_sample_code(v) for v in field(args["mask"][0]).reshape(-1).tolist()))
        modes.append(LayerMode(args["mode"]))
        strengths.append(args["strength"])
    weights = [[struct.unpack("!f", struct.pack("!I", v))[0] for v in layer]
               for layer in compose_field_codes(planes, strengths, modes)]
    for values in zip(*weights):
        total = sum(values)
        # Coverage rule: every sample receives a prompt (no uncovered gaps), and shares are normalized.
        require(abs(total - 1) < 1e-6, "Uncovered or unnormalized sample")
    for j, w in enumerate(weights):
        # Every layer is the strongest layer somewhere, so each concept can visibly appear.
        require(any(v > max(o[i] for k, o in enumerate(weights) if k != j) for i, v in enumerate(w)), f"Layer {j + 1} never leads")
    if path.stem.startswith("03"):
        require(all(m is LayerMode.BLENDED for m in modes), "03 is BLENDED only")
        require(any(sum(v > 0 for v in sample) >= 2 for sample in zip(*weights)), "No blended overlap")
    if path.stem.startswith("02"):
        require(all(m is LayerMode.FIXED for m in modes), "02 is FIXED only")
    if path.stem.startswith("09"):
        require({LayerMode.FIXED, LayerMode.BLENDED} <= set(modes), "09 mixes FIXED and BLENDED")
        editors = [n["properties"]["fieldEditor"] for n in painted]
        require(any(s.get("shape") == "custom" for s in editors), "09 custom tip")
        require(any(s.get("procedural_particle_shape") == "hotdog" for s in editors), "09 Hotdog")
        require(any(s.get("pressure_enabled") is True for s in editors), "09 pressure-compatible painting")
    reached = set()

    def ancestors(nid):
        if nid in reached:
            return
        reached.add(nid)
        for inp in nodes[nid]["inputs"]:
            if inp["link"] is not None:
                ancestors(links[inp["link"]][1])
    ancestors(outputs[0]["id"])
    require(reached == {n["id"] for n in nodes.values() if n["type"] != "Note"}, "Disconnected executable node")

    prompt_of = {lid: nodes[arguments[lid]["conditioning"][0]]["widgets_values"][0] for lid in chain}
    hotdog = [n for n in painted if n["properties"]["fieldEditor"].get("procedural_particle_shape") == "hotdog"]
    for n in hotdog:  # Hotdog stamps are wired into a contributing layer whose prompt is about hotdogs.
        user = next(lid for lid in chain if arguments[lid]["mask"][0] == n["id"])
        require("hotdog" in prompt_of[user].lower(), "Hotdog layer prompt")
    print(f"PASS {path.name}: {len(nodes)} nodes, {layer_count} layers, {painted_count} Painted Fields, {len(notes)} notes; "
          "full coverage; every layer leads somewhere")
    return {"stem": path.stem, "prompts": [prompt_of[lid] for lid in chain], "modes": [m.value for m in modes],
            "title": titles[0]["widgets_values"][0].split("\n")[0], "hotdog": bool(hotdog), "notes": len(notes)}


def prompt_checks(results):
    by = {r["stem"]: r for r in results}
    every = [(r["stem"], p) for r in results for p in r["prompts"]]
    for _, text in every:
        require(not re.search(r"botanical|observatory|architectural diorama|terracotta", text, re.I), "Unrelated scene vocabulary")
        require(styles(text), "Prompt without a recognisable style")
    for (sa, a), (sb, b) in itertools.combinations(every, 2):
        if sa != sb and sa[:2] == sb[:2]:
            continue  # 06a/06b are one example: start and completed states share their prompts.
        require(similarity(a, b) < (0.5 if sa == sb else 0.4), f"Recycled prompt: {sa} / {sb}")
    premises = [r["title"].split(" — ", 1)[1] for r in results if r["stem"] != "06b_painted_field_completed"]
    require(len(set(premises)) == len(premises), "Repeated visual premise")
    l1, l2 = by["02_two_fixed_regions"]["prompts"]
    require(styles(l1).isdisjoint(styles(l2)) and similarity(l1, l2) < 0.1, "02 regions must differ in subject and style")
    c1, c2 = by["03_blended_gradients"]["prompts"][:2]
    require(styles(c1).isdisjoint(styles(c2)) and similarity(c1, c2) < 0.15, "03 blend endpoints must differ")
    require(sum("hotdog" in p.lower() for p in by["07_advanced_brushes"]["prompts"]) >= 3, "07 Hotdog prompts")
    flagship = by["09_nine_layer_showcase"]["prompts"]
    require(len(set().union(*map(styles, flagship))) >= 6, "09 needs several distinct styles")
    contrast = []
    for r in results:
        pairs = [(a, b) for (a, ma), (b, mb) in itertools.combinations(zip(r["prompts"], r["modes"]), 2) if "FIXED" in (ma, mb)]
        if any(styles(a).isdisjoint(styles(b)) and similarity(a, b) < 0.15 for a, b in pairs):
            contrast.append(r["stem"][:3].rstrip("_"))
    require(len(contrast) >= 3, "Fewer than three FIXED style/subject contrasts")
    hotdogs = [r["stem"][:2] for r in results if r["hotdog"]]
    require(len(hotdogs) >= 2, "Hotdog workflows")
    print(f"PASS prompt diversity: {len(every)} prompts, none recycled; FIXED contrast in {', '.join(contrast)}; "
          f"Hotdog in {', '.join(hotdogs)}; {sum(r['notes'] for r in results)} notes")


def main():
    require(sys.version_info[:3] == (3, 12, 11), "Use the pinned host-dependent Python 3.12.11 lane")
    sys.path.insert(0, str(ROOT / "src"))
    with ExitStack() as stack:
        for target in FENCES:
            stack.enter_context(patch(target, side_effect=fence, create=True))
        classes = registry()
        require({p.stem for p in PACK.glob("*.json")} == set(EXPECTED), "Workflow inventory")
        results = [validate(PACK / (stem + ".json"), classes) for stem in EXPECTED]
        prompt_checks(results)
        presets = sorted(p.name for p in (PACK / "presets").glob("*.json"))
        require(presets == ["hotdog_meteor_shower.brush.json", "sparkle_glints.brush.json"], "Preset inventory")
        for name in presets:
            private_check(json.loads((PACK / "presets" / name).read_text(encoding="utf-8")))
        private_check((PACK / "README.md").read_text(encoding="utf-8"), workflow=False)


if __name__ == "__main__":
    main()
