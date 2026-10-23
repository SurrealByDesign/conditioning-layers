"""Offline feature examples: graph links, exact grouped weights and MOSS UI/API parity.

No host, GPU, model or private evidence is used. The MOSS check preserves the
accepted example structurally; it does not establish new model compatibility.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
from unittest.mock import patch

from offline_regressions import FENCES, fence
from validate_examples import private_check, require, registry, overlaps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def graph(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    private_check(data, workflow=False)
    require(data["version"] == 0.4, "Workflow version")
    nodes = {n["id"]: n for n in data["nodes"]}
    links = {l[0]: l for l in data["links"]}
    require(len(nodes) == len(data["nodes"]) and len(links) == len(data["links"]), "Duplicate IDs")
    for n in nodes.values():
        require(n.get("mode", 0) == 0, "Bypassed node")
        for slot, inp in enumerate(n.get("inputs", [])):
            if inp.get("link") is None:
                continue
            link = links[inp["link"]]
            require(link[3:5] == [n["id"], slot], "Target link")
            output = nodes[link[1]]["outputs"][link[2]]
            require(output["type"] == link[5] and output["type"] in inp["type"].split(","), "Socket type")
            require(link[0] in output["links"], "Output back reference")
        for slot, output in enumerate(n.get("outputs", [])):
            for lid in output.get("links") or []:
                require(links[lid][1:3] == [n["id"], slot], "Source link")
    require(data["last_node_id"] == max(nodes) and data["last_link_id"] == max(links), "Last IDs")
    return data, nodes, links


def upstream(nodes, links, node, name):
    inputs = [i for i in node["inputs"] if i["name"] == name]
    require(len(inputs) == 1 and inputs[0]["link"] in links, "Required link: " + name)
    return nodes[links[inputs[0]["link"]][1]]


def grouped():
    from conditioning_layers.assets.field_png import decode_field_data_url
    from conditioning_layers.comfyui.prediction_mixing.layer_nodes import LayerMode, compose_field_codes
    from conditioning_layers.comfyui.prediction_mixing.layer_nodes.grouped_composition import compose_grouped_field_codes
    from conditioning_layers.integrations.composition_preview import preview_composition
    data, nodes, links = graph(ROOT / "examples/blend-groups/grouped_contribution.json")
    classes = registry()
    for n in nodes.values():
        if n["type"] not in classes:
            continue
        spec = classes[n["type"]].INPUT_TYPES()
        widgets = iter(n["widgets_values"])
        for section in ("required", "optional"):
            for name, entry in spec.get(section, {}).items():
                kind = entry[0]
                if isinstance(kind, list) or kind in ("STRING", "FLOAT", "INT", "BOOLEAN"):
                    value = next(widgets)
                    if isinstance(kind, list):
                        require(value in kind, "Invalid enum")
                elif section == "required":
                    upstream(nodes, links, n, name)
        require(next(widgets, None) is None, "Extra widget")
    compose = [n for n in nodes.values() if n["type"] == "ConditioningLayersComposeGroups"]
    require(len(compose) == 1, "Grouped Compose")
    chain, visited = [], set()
    add = upstream(nodes, links, compose[0], "layers")
    while True:
        require(add["type"] == "ConditioningLayersAddLayer" and add["id"] not in visited, "Stack cycle/type")
        visited.add(add["id"])
        chain.append(upstream(nodes, links, add, "layer"))
        if next(i for i in add["inputs"] if i["name"] == "layers")["link"] is None:
            break
        add = upstream(nodes, links, add, "layers")
    chain.reverse()
    require(len(chain) == 4 and len({n["id"] for n in chain}) == 4, "Four distinct layers")
    planes, strengths, modes, groups, payload = [], [], [], [], []
    for n in chain:
        require(n["type"] == "ConditioningLayersLayer", "Layer type")
        field = upstream(nodes, links, n, "mask")
        require(field["type"] == "ConditioningLayersPaintedField", "Direct Painted Field required")
        codes = tuple(decode_field_data_url(field["widgets_values"][0]))
        strength, mode, enabled, group = n["widgets_values"]
        require(enabled is True and strength == 1.0, "Tutorial starting state")
        planes.append(codes); strengths.append(strength); modes.append(LayerMode(mode)); groups.append(group)
        payload.append(dict(id=str(n["id"]), codes=list(codes), strength=strength, mode=mode, enabled=enabled, group=group))
    require(groups == ["materials", "materials", "environment", "materials"], "Tutorial groups")
    require(modes == [LayerMode.BLENDED] * 3 + [LayerMode.FIXED], "Global FIXED example")
    prepared = compose_grouped_field_codes(planes, strengths, modes, groups)
    flat = compose_field_codes(planes, strengths, modes)
    for i in range(16384):
        expected = (0, 0, 0, 0x3f800000) if planes[-1][i] else (0x3e800000, 0x3e800000, 0x3f000000, 0)
        require(tuple(row[i] for row in prepared) == expected, "Grouped share/FIXED ownership")
        if planes[-1][i]:
            require(tuple(row[i] for row in flat) == expected, "Legacy FIXED preservation")
    for n, bits in zip(chain, prepared):
        result = preview_composition(dict(compose="ConditioningLayersComposeGroups", layers=payload, selected=str(n["id"])))
        require(result["status"] == "ready" and tuple(result["bits"]) == bits, "Preview equivalence")
    sampler = next(n for n in nodes.values() if n["type"] == "KSampler")
    require(upstream(nodes, links, sampler, "positive") == compose[0], "Sampler positive route")
    require(sampler["widgets_values"][1:] == ["fixed", 8, 1, "euler", "simple", 1], "Turbo defaults")
    reachable = set()
    def visit(node):
        require(node["id"] not in active, "Graph cycle")
        if node["id"] in reachable: return
        active.add(node["id"])
        for inp in node.get("inputs", []):
            if inp.get("link") is not None: visit(nodes[links[inp["link"]][1]])
        active.remove(node["id"]); reachable.add(node["id"])
    active = set(); visit(next(n for n in nodes.values() if n["type"] == "SaveImage"))
    require(reachable == {n["id"] for n in nodes.values() if n["type"] != "Note"}, "Disconnected executable node")
    boxes = [(n["pos"][0], n["pos"][1]-30, n["pos"][0]+n["size"][0], n["pos"][1]+n["size"][1]) for n in nodes.values()]
    for i, box in enumerate(boxes):
        require(not any(overlaps(box, other, 8) for other in boxes[i+1:]), "Overlapping example nodes")
    require(json.loads(json.dumps(data)) == data, "JSON round trip")
    print("PASS grouped tutorial: graph/serialization, four direct fields, exact shares, global FIXED, all-layer preview equivalence")


def moss():
    _, nodes, links = graph(ROOT / "examples/moss-experimental/moss_experimental_fixed.json")
    api = json.loads((ROOT / "examples/moss-experimental/moss_experimental_fixed_api.json").read_text(encoding="utf-8"))
    private_check(api, workflow=False)
    require({str(n["id"]) for n in nodes.values() if n["type"] != "Note"} == set(api), "MOSS UI/API IDs")
    for key, entry in api.items():
        node = nodes[int(key)]
        require(node["type"] == entry["class_type"], "MOSS node type")
        for name, val in entry["inputs"].items():
            if isinstance(val, list) and len(val) == 2 and str(val[0]) in api:
                inp = next(i for i in node["inputs"] if i["name"] == name)
                link = links[inp["link"]]
                require([str(link[1]), link[2]] == val, "MOSS UI/API connection")
            elif node["type"] == "CreateBoundingBoxes" and name in {"editor_state", "last_incoming"}:
                # Native UI empty custom widgets export wrapped empty objects.
                index = 2 if name == "editor_state" else 3
                require(node["widgets_values"][index] == [] and val == {"__value__": {}}, "MOSS empty editor state")
            else:
                require(val in node.get("widgets_values", []), "MOSS UI/API literal: " + name)
    layers = [n for n in api.values() if n["class_type"] == "ConditioningLayersLayer"]
    require(len(layers) == 2 and all(n["inputs"]["mode"] == "FIXED" for n in layers), "MOSS FIXED scope")
    latent = next(n for n in api.values() if n["class_type"] == "EmptyFlux2LatentImage")["inputs"]
    require(latent["width"] == latent["height"] == 1024, "Qualified MOSS resolution")
    require(not any(n["class_type"] == "ConditioningLayersComposeGroups" for n in api.values()), "No MOSS grouped claim")
    print("PASS MOSS accepted UI/API structure and literals; 1024x1024 FIXED-only scope (no model execution)")


if __name__ == "__main__":
    with ExitStack() as stack:
        for target in FENCES:
            stack.enter_context(patch(target, side_effect=fence, create=True))
        grouped()
        moss()
