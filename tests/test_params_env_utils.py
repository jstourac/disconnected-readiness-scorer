"""Direct unit tests for params_env_utils extraction functions."""

from rules.params_env_utils import (
    PROBE_SENTINEL,
    extract_all_images,
    extract_configmap_key_refs,
    extract_env_configmap_mappings,
    extract_kustomize_replacement_keys,
    parse_params_env,
)


class TestExtractAllImages:
    def test_finds_tagged_image(self):
        rendered = (
            "---\nkind: Deployment\nmetadata:\n  name: app\nspec:\n  image: quay.io/org/img:v1\n"
        )
        result = extract_all_images(rendered, [])
        assert "quay.io/org/img:v1" in result

    def test_finds_digest_image(self):
        rendered = "image: registry.io/app/svc@sha256:" + "a" * 64 + "\n"
        result = extract_all_images(rendered, [])
        assert any("@sha256:" in img for img in result)

    def test_excludes_pattern(self):
        rendered = "image: quay.io/org/excluded:v1\nimage: quay.io/org/kept:v2\n"
        result = extract_all_images(rendered, ["quay.io/org/excluded:*"])
        assert "quay.io/org/excluded:v1" not in result
        assert "quay.io/org/kept:v2" in result

    def test_probe_sentinel_detected_but_filtered_by_caller(self):
        rendered = f"image: {PROBE_SENTINEL}\n"
        result = extract_all_images(rendered, [])
        assert PROBE_SENTINEL in result

    def test_tracks_resource_location(self):
        rendered = (
            "---\nkind: Deployment\nmetadata:\n  name: myapp\nspec:\n  image: quay.io/org/img:v1\n"
        )
        result = extract_all_images(rendered, [])
        assert result.get("quay.io/org/img:v1") == ["Deployment/myapp"]

    def test_configmap_data_key_in_location(self):
        rendered = (
            "---\nkind: ConfigMap\nmetadata:\n  name: inferenceservice-config\n"
            "data:\n"
            "  _example: |-\n"
            "    image: kserve/storage-initializer:latest\n"
            "  storageInitializer: |-\n"
            "    image: quay.io/org/real:v1\n"
        )
        result = extract_all_images(rendered, [])
        locs_example = result.get("kserve/storage-initializer:latest", [])
        assert any("{key:_example}" in loc for loc in locs_example)
        locs_real = result.get("quay.io/org/real:v1", [])
        assert any("{key:storageInitializer}" in loc for loc in locs_real)

    def test_non_configmap_has_no_key_suffix(self):
        rendered = (
            "---\nkind: Deployment\nmetadata:\n  name: myapp\n"
            "data:\n  somekey: quay.io/org/img:v1\n"
        )
        result = extract_all_images(rendered, [])
        locs = result.get("quay.io/org/img:v1", [])
        assert all("[key=" not in loc for loc in locs)


class TestExtractConfigmapKeyRefs:
    def test_finds_key_refs(self):
        rendered = (
            "        configMapKeyRef:\n"
            "          key: odh-model-controller\n"
            "          name: params\n"
        )
        assert extract_configmap_key_refs(rendered) == {"odh-model-controller"}

    def test_multiple_refs(self):
        rendered = (
            "        configMapKeyRef:\n"
            "          key: KEY_A\n"
            "          name: params\n"
            "---\n"
            "        configMapKeyRef:\n"
            "          key: KEY_B\n"
            "          name: other\n"
        )
        assert extract_configmap_key_refs(rendered) == {"KEY_A", "KEY_B"}

    def test_no_refs(self):
        assert extract_configmap_key_refs("kind: ConfigMap\n") == set()

    def test_reversed_name_before_key(self):
        rendered = "        configMapKeyRef:\n          name: params\n          key: my-component\n"
        assert extract_configmap_key_refs(rendered) == {"my-component"}


class TestExtractKustomizeReplacementKeys:
    def test_finds_field_path_keys(self, tmp_path):
        kust = tmp_path / "kustomization.yaml"
        kust.write_text(
            "replacements:\n"
            "  - source:\n"
            "      fieldPath: data.odh-model-controller\n"
            "  - source:\n"
            "      fieldPath: data.kserve-controller\n"
        )
        result = extract_kustomize_replacement_keys(tmp_path)
        assert result == {"odh-model-controller", "kserve-controller"}

    def test_no_replacements(self, tmp_path):
        kust = tmp_path / "kustomization.yaml"
        kust.write_text("resources: []\n")
        assert extract_kustomize_replacement_keys(tmp_path) == set()


class TestExtractEnvConfigmapMappings:
    def test_finds_env_mapping(self):
        rendered = (
            "    - name: RELATED_IMAGE_FOO\n"
            "      valueFrom:\n"
            "        configMapKeyRef:\n"
            "          key: my-image-key\n"
            "          name: params\n"
        )
        result = extract_env_configmap_mappings(rendered)
        assert len(result) == 1
        assert result[0] == ("RELATED_IMAGE_FOO", "my-image-key", "params")

    def test_no_mappings(self):
        assert extract_env_configmap_mappings("kind: Service\n") == []

    def test_reversed_name_before_key(self):
        rendered = (
            "    - name: RELATED_IMAGE_BAR\n"
            "      valueFrom:\n"
            "        configMapKeyRef:\n"
            "          name: params\n"
            "          key: bar-image-key\n"
        )
        result = extract_env_configmap_mappings(rendered)
        assert len(result) == 1
        assert result[0] == ("RELATED_IMAGE_BAR", "bar-image-key", "params")


class TestParseParamsEnv:
    def test_registryless_image_with_tag(self, tmp_path):
        pf = tmp_path / "params.env"
        pf.write_text("IMG=nginx:1.19\n")
        result = parse_params_env(pf)
        assert result == {"IMG": "nginx:1.19"}

    def test_registryless_image_with_digest(self, tmp_path):
        pf = tmp_path / "params.env"
        pf.write_text("IMG=ubuntu@sha256:" + "a" * 64 + "\n")
        result = parse_params_env(pf)
        assert "IMG" in result

    def test_plain_string_without_separator_skipped(self, tmp_path):
        pf = tmp_path / "params.env"
        pf.write_text("FOO=some-value\n")
        result = parse_params_env(pf)
        assert result == {}

    def test_fully_qualified_image_still_works(self, tmp_path):
        pf = tmp_path / "params.env"
        pf.write_text("IMG=quay.io/org/img:v1\n")
        result = parse_params_env(pf)
        assert result == {"IMG": "quay.io/org/img:v1"}
