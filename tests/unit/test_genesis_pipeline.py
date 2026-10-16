"""Tests for the two-step genesis pipeline (v1.33.1)."""

import tempfile
import unittest
from pathlib import Path

from fogbed_iota.genesis.committee import CommitteeSpec, prepare_committee
from fogbed_iota.genesis.builder import GenesisBuilder
from fogbed_iota.genesis.tools import ToolRunner
from fogbed_iota.genesis.release import load_release


class TestGenesisPipeline(unittest.TestCase):
    def test_release_metadata(self):
        rel = load_release()
        self.assertEqual(rel.tag, "v1.33.1")
        self.assertEqual(rel.commit_sha, "97b1057f8de0ff220a1d0478b78a384cb484b0ef")
        self.assertEqual(rel.protocol_version, 37)

    def test_pipeline_local_docker(self):
        tools = ToolRunner(image="iota-dev:latest")
        try:
            tools.verify()
        except Exception as e:
            self.skipTest(f"Docker image iota-dev:latest not verified: {e}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            spec = CommitteeSpec(
                network_name="test-committee",
                validators=[
                    ("v1", "10.0.0.1"),
                    ("v2", "10.0.0.2"),
                    ("v3", "10.0.0.3"),
                    ("v4", "10.0.0.4"),
                ],
                gateways=[("gw", "10.0.0.5")],
                subnet=None,
            )

            # Step 1
            committee = prepare_committee(base / "comm", spec, tools=tools, force=True)
            self.assertTrue(committee.genesis_config_path.is_file())
            self.assertEqual(len(committee.validators), 4)
            self.assertEqual(len(committee.gateways), 1)

            # Step 2
            builder = GenesisBuilder(tools=tools)
            artifacts = builder.build(committee, base / "out")

            self.assertTrue(artifacts.genesis_blob.is_file())
            self.assertGreater(artifacts.genesis_blob.stat().st_size, 0)
            self.assertEqual(len(artifacts.nodes), 5)

            # Check that every node received the identical genesis hash
            shared_hash = artifacts.genesis_blob_sha256
            for node_name, node_art in artifacts.nodes.items():
                self.assertEqual(node_art.genesis_blob_sha256, shared_hash)
                self.assertTrue(node_art.validator_yaml.is_file())


if __name__ == "__main__":
    unittest.main()
