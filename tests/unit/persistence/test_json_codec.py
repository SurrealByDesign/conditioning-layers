from __future__ import annotations

from dataclasses import replace
import json
import math
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities import evaluate_prediction_mixing
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
)
from conditioning_layers.persistence import (
    PROTOTYPE_FORMAT_ID,
    DocumentEncodeError,
    decode_document,
    encode_document,
)


SHA256 = "a" * 64


def make_layer(
    layer_id: str,
    *,
    visible: bool = True,
    strength: float = 1.0,
    path: str | None = None,
    checksum: str | None = SHA256,
) -> PromptLayer:
    field = (
        None
        if path is None
        else InfluenceFieldAssetReference(relative_path=path, checksum=checksum)
    )
    return PromptLayer(
        layer_id=layer_id,
        name=f"Layer {layer_id}",
        prompt_text=f"Prompt {layer_id}",
        visible=visible,
        strength=strength,
        influence_field=field,
    )


def make_document(
    *layers: PromptLayer,
    adapter_id: str | None = None,
    adapter_settings: object = None,
    base_prompt: str = "A coherent studio scene",
) -> ConditioningDocument:
    return ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="document-1",
        base_prompt=base_prompt,
        layers=layers,
        selected_adapter_id=adapter_id,
        adapter_settings={} if adapter_settings is None else adapter_settings,
    )


def persistence_codes(result: object) -> set[str]:
    return {
        finding.code
        for finding in result.persistence_findings  # type: ignore[attr-defined]
    }


def domain_codes(result: object) -> set[str]:
    return {finding.code for finding in result.domain_findings}  # type: ignore[attr-defined]


class RoundTripTests(unittest.TestCase):
    def assert_round_trip(self, document: ConditioningDocument) -> ConditioningDocument:
        result = decode_document(encode_document(document))
        self.assertTrue(result.ok, result.findings)
        self.assertIsNotNone(result.document)
        self.assertEqual(result.document, document)
        return result.document  # type: ignore[return-value]

    def test_empty_document_round_trip(self) -> None:
        self.assert_round_trip(make_document())

    def test_one_layer_round_trip(self) -> None:
        self.assert_round_trip(make_document(make_layer("one", path="fields/one.png")))

    def test_multiple_layers_preserve_exact_order_and_ids(self) -> None:
        document = make_document(
            make_layer("third", path="fields/third.png"),
            make_layer("first", path="fields/first.png"),
            make_layer("second", path="fields/second.png"),
        )

        loaded = self.assert_round_trip(document)

        self.assertEqual(
            [layer.layer_id for layer in loaded.layers],
            ["third", "first", "second"],
        )

    def test_disabled_layer_strength_field_and_checksum_round_trip(self) -> None:
        layer = make_layer(
            "disabled",
            visible=False,
            strength=0.375,
            path="fields/disabled.png",
        )

        loaded = self.assert_round_trip(make_document(layer))

        self.assertFalse(loaded.layers[0].visible)
        self.assertEqual(loaded.layers[0].strength, 0.375)
        self.assertEqual(loaded.layers[0].influence_field.checksum, SHA256)  # type: ignore[union-attr]

    def test_unicode_prompts_are_not_ascii_escaped(self) -> None:
        layer = replace(
            make_layer("unicode", path="fields/unicode.png"),
            name="Café layer",
            prompt_text="青い花 — lumière",
        )
        document = make_document(layer, base_prompt="静かな café scene")

        encoded = encode_document(document)
        loaded = self.assert_round_trip(document)

        self.assertIn("青い花", encoded)
        self.assertEqual(loaded.layers[0].prompt_text, "青い花 — lumière")

    def test_adapter_absent_round_trip(self) -> None:
        loaded = self.assert_round_trip(make_document())

        self.assertIsNone(loaded.selected_adapter_id)
        self.assertEqual(dict(loaded.adapter_settings), {})

    def test_null_influence_field_round_trip(self) -> None:
        loaded = self.assert_round_trip(make_document(make_layer("draft")))

        self.assertIsNone(loaded.layers[0].influence_field)

    def test_adapter_nested_json_settings_round_trip(self) -> None:
        settings = {
            "nested": {
                "values": [1, 0.5, True, False, None, "text"],
                "object": {"mode": "prototype"},
            }
        }
        document = make_document(
            make_layer("one", path="fields/one.png"),
            adapter_id=PREDICTION_MIXING_ADAPTER_ID,
            adapter_settings=settings,
        )

        loaded = self.assert_round_trip(document)

        self.assertEqual(dict(loaded.adapter_settings), settings)


class CanonicalOutputTests(unittest.TestCase):
    def test_repeated_encoding_is_deterministic_and_has_one_final_newline(self) -> None:
        document = make_document(make_layer("one", path="fields/one.png"))

        first = encode_document(document)
        second = encode_document(document)

        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        self.assertFalse(first.endswith("\n\n"))

    def test_empty_document_has_stable_readable_sorted_output(self) -> None:
        encoded = encode_document(make_document())

        expected = f'''{{
  "document": {{
    "adapter": {{
      "id": null,
      "settings": {{}}
    }},
    "base_prompt": "A coherent studio scene",
    "id": "document-1",
    "layers": [],
    "version": {{
      "major": 1,
      "minor": 0
    }}
  }},
  "format": "{PROTOTYPE_FORMAT_ID}",
  "format_version": {{
    "major": 1,
    "minor": 0
  }}
}}
'''
        self.assertEqual(encoded, expected)

    def test_visibility_is_json_boolean_and_strength_is_numeric(self) -> None:
        encoded = encode_document(
            make_document(
                make_layer(
                    "disabled",
                    visible=False,
                    strength=0.25,
                    path="fields/disabled.png",
                )
            )
        )
        payload = json.loads(encoded)
        layer = payload["document"]["layers"][0]

        self.assertIs(layer["visible"], False)
        self.assertEqual(layer["strength"], 0.25)
        self.assertIsInstance(layer["strength"], float)

    def test_backslash_reference_is_encoded_in_canonical_relative_form(self) -> None:
        document = make_document(
            make_layer("one", path=r"fields\nested\one.png")
        )

        payload = json.loads(encode_document(document))

        self.assertEqual(
            payload["document"]["layers"][0]["influence_field"]["path"],
            "fields/nested/one.png",
        )
        self.assertEqual(document.layers[0].influence_field.relative_path, r"fields\nested\one.png")  # type: ignore[union-attr]

    def test_non_finite_strength_is_rejected_before_json_encoding(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(DocumentEncodeError):
                    encode_document(
                        make_document(make_layer("bad", strength=value, path="fields/bad.png"))
                    )

    def test_non_finite_adapter_setting_is_rejected(self) -> None:
        document = make_document(adapter_settings={"bad": math.nan})

        with self.assertRaises(DocumentEncodeError) as raised:
            encode_document(document)

        self.assertIn(
            "adapter_settings.non_finite",
            {finding.code for finding in raised.exception.findings},
        )

    def test_unsupported_adapter_setting_type_is_rejected(self) -> None:
        document = make_document(adapter_settings={"bad": (1, 2)})

        with self.assertRaises(DocumentEncodeError) as raised:
            encode_document(document)

        self.assertIn(
            "adapter_settings.unsupported_type",
            {finding.code for finding in raised.exception.findings},
        )

    def test_nested_non_string_adapter_setting_key_is_rejected(self) -> None:
        document = make_document(adapter_settings={"nested": {1: "bad"}})

        with self.assertRaises(DocumentEncodeError) as raised:
            encode_document(document)

        self.assertIn(
            "adapter_settings.non_string_key",
            {finding.code for finding in raised.exception.findings},
        )

    def test_adapter_setting_depth_limit_is_enforced(self) -> None:
        nested: object = "leaf"
        for _ in range(34):
            nested = {"child": nested}
        document = make_document(adapter_settings={"nested": nested})

        with self.assertRaises(DocumentEncodeError) as raised:
            encode_document(document)

        self.assertIn(
            "adapter_settings.depth_exceeded",
            {finding.code for finding in raised.exception.findings},
        )


class InvalidInputTests(unittest.TestCase):
    def payload(self, document: ConditioningDocument | None = None) -> dict[str, object]:
        return json.loads(encode_document(document or make_document()))

    def decode_payload(self, payload: object, **kwargs: object) -> object:
        return decode_document(json.dumps(payload, ensure_ascii=False), **kwargs)

    def test_malformed_json_returns_syntax_finding(self) -> None:
        result = decode_document('{"format":')

        self.assertIsNone(result.document)
        self.assertIn("json.syntax.invalid", persistence_codes(result))

    def test_deep_non_document_json_returns_structured_finding(self) -> None:
        result = decode_document("[" * 2000 + "]" * 2000)

        self.assertIsNone(result.document)
        self.assertTrue(result.persistence_findings)

    def test_duplicate_keys_are_rejected(self) -> None:
        result = decode_document('{"format": "a", "format": "b"}')

        self.assertIn("json.duplicate_key", persistence_codes(result))

    def test_missing_required_field_is_reported(self) -> None:
        payload = self.payload()
        del payload["document"]["id"]  # type: ignore[index]

        result = self.decode_payload(payload)

        self.assertIsNone(result.document)
        self.assertIn("json.field.missing", persistence_codes(result))

    def test_wrong_field_type_is_reported(self) -> None:
        payload = self.payload()
        payload["document"]["layers"] = {}  # type: ignore[index]

        result = self.decode_payload(payload)

        self.assertIsNone(result.document)
        self.assertIn("json.field.wrong_type", persistence_codes(result))

    def test_unsupported_format_identifier_is_reported(self) -> None:
        payload = self.payload()
        payload["format"] = "another.format"

        result = self.decode_payload(payload)

        self.assertIn("format.identifier.unsupported", persistence_codes(result))

    def test_older_and_newer_format_versions_are_distinguished(self) -> None:
        for version, expected in (
            ({"major": 0, "minor": 9}, "format.version.unsupported_older"),
            ({"major": 1, "minor": 1}, "format.version.unsupported_newer"),
        ):
            with self.subTest(version=version):
                payload = self.payload()
                payload["format_version"] = version

                result = self.decode_payload(payload)

                self.assertIn(expected, persistence_codes(result))

    def test_unsupported_domain_version_is_a_domain_finding(self) -> None:
        payload = self.payload()
        payload["document"]["version"] = {"major": 3, "minor": 0}  # type: ignore[index]

        result = self.decode_payload(payload)

        self.assertIsNotNone(result.document)
        self.assertIn("document.version.unsupported_major", domain_codes(result))
        self.assertFalse(result.ok)

    def test_duplicate_layer_ids_are_domain_findings(self) -> None:
        payload = self.payload(
            make_document(
                make_layer("a", path="fields/a.png"),
                make_layer("b", path="fields/b.png"),
            )
        )
        payload["document"]["layers"][1]["id"] = "a"  # type: ignore[index]

        result = self.decode_payload(payload)

        self.assertIn("layer.id.duplicate", domain_codes(result))

    def test_malformed_checksum_is_a_domain_finding(self) -> None:
        payload = self.payload(
            make_document(make_layer("a", path="fields/a.png"))
        )
        payload["document"]["layers"][0]["influence_field"]["sha256"] = "bad"  # type: ignore[index]

        result = self.decode_payload(payload)

        self.assertIn("influence_field.checksum.invalid_format", domain_codes(result))

    def test_out_of_range_strength_is_a_domain_finding(self) -> None:
        payload = self.payload(
            make_document(make_layer("a", path="fields/a.png"))
        )
        payload["document"]["layers"][0]["strength"] = 1.5  # type: ignore[index]

        result = self.decode_payload(payload)

        self.assertIn("layer.strength.out_of_range", domain_codes(result))

    def test_empty_required_text_is_a_domain_finding(self) -> None:
        payload = self.payload()
        payload["document"]["base_prompt"] = ""  # type: ignore[index]

        result = self.decode_payload(payload)

        self.assertIsNotNone(result.document)
        self.assertIn("document.base_prompt.empty", domain_codes(result))

    def test_non_finite_json_number_is_rejected(self) -> None:
        text = encode_document(
            make_document(make_layer("a", path="fields/a.png"))
        ).replace('"strength": 1.0', '"strength": NaN')

        result = decode_document(text)

        self.assertIn("json.number.non_finite", persistence_codes(result))

    def test_unsafe_asset_path_is_rejected_before_domain_creation(self) -> None:
        payload = self.payload(
            make_document(make_layer("a", path="fields/a.png"))
        )
        payload["document"]["layers"][0]["influence_field"]["path"] = "../a.png"  # type: ignore[index]

        result = self.decode_payload(payload)

        self.assertIsNone(result.document)
        self.assertIn("asset.path.traversal", persistence_codes(result))

    def test_unknown_neutral_fields_warn_and_are_discarded(self) -> None:
        payload = self.payload(
            make_document(make_layer("a", path="fields/a.png"))
        )
        payload["future_top"] = True
        payload["document"]["future_document"] = {"value": 1}  # type: ignore[index]
        payload["document"]["layers"][0]["future_layer"] = "value"  # type: ignore[index]

        result = self.decode_payload(payload)

        warnings = [
            finding
            for finding in result.persistence_findings
            if finding.code == "json.unknown_field"
        ]
        self.assertEqual(len(warnings), 3)
        self.assertEqual(warnings[-1].layer_id, "a")
        self.assertTrue(result.ok)
        reencoded = encode_document(result.document)  # type: ignore[arg-type]
        self.assertNotIn("future_top", reencoded)
        self.assertNotIn("future_document", reencoded)
        self.assertNotIn("future_layer", reencoded)

    def test_unknown_adapter_settings_are_preserved_without_unknown_field_warning(self) -> None:
        payload = self.payload()
        payload["document"]["adapter"]["settings"] = {  # type: ignore[index]
            "future": {"nested": [1, True, None]}
        }

        result = self.decode_payload(payload)

        self.assertTrue(result.ok)
        self.assertEqual(
            dict(result.document.adapter_settings),  # type: ignore[union-attr]
            {"future": {"nested": [1, True, None]}},
        )
        self.assertNotIn("json.unknown_field", persistence_codes(result))

    def test_capability_findings_are_separately_opt_in(self) -> None:
        document = make_document(
            make_layer("a", path="fields/a.png"),
            make_layer("b", path="fields/b.png"),
            make_layer("c", path="fields/c.png"),
            adapter_id=PREDICTION_MIXING_ADAPTER_ID,
        )
        encoded = encode_document(document)

        default = decode_document(encoded)
        with patch(
            "conditioning_layers.persistence.json_codec.evaluate_prediction_mixing",
            wraps=evaluate_prediction_mixing,
        ) as authority:
            requested = decode_document(
                encoded,
                include_adapter_capability_findings=True,
            )

        self.assertEqual(default.capability_findings, ())
        authority.assert_called_once_with(requested.document)
        self.assertIn(
            "capability.active_layer_limit",
            {finding.code for finding in requested.capability_findings},
        )


if __name__ == "__main__":
    unittest.main()
