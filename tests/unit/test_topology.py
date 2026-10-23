"""Unit tests for the multi-tier (Edge/Fog/Cloud) topology support.

Node Docker, Mininet or sudo needed: ``IotaNetwork`` is driven against a fake experiment that mimics
the exact Fogbed API it consumes (``add_virtual_instance`` / ``add_docker`` / ``add_link``), and the
end-to-end verifier is driven with a scripted command executor.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fogbed_iota import multitier_check as mc
from fogbed_iota import network as network_mod
from fogbed_iota.topology import (
    LinkProfile,
    Tier,
    TopologyError,
    TopologySpec,
    TopologyValidationError,
    three_tier_topology,
    tier_name,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeInstance:
    counter = 0

    def __init__(self, label):
        FakeInstance.counter += 1
        self.label = label
        self.switch = f"s{FakeInstance.counter}"


class FakeExp:
    """Mimics the subset of ``fogbed.FogbedExperiment`` used by IotaNetwork."""

    def __init__(self, running=False):
        FakeInstance.counter = 0
        self.instances = {}
        self.docker = []   # (container, instance_label)
        self.links = []    # (label_a, label_b, params)
        self.net = SimpleNamespace(is_running=running)

    def get_virtual_instance(self, name):
        if name not in self.instances:
            raise KeyError(name)
        return self.instances[name]

    def add_virtual_instance(self, name, resource_model=None):
        self.instances[name] = FakeInstance(name)
        return self.instances[name]

    def add_docker(self, container, datacenter):
        self.docker.append((container, datacenter.label, dict(container.link_params)))

    def add_link(self, a, b, **params):
        self.links.append((a.label, b.label, params))


class FakeNode:
    """Stands in for IotaNode (whose base is the real Fogbed Container)."""

    def __init__(self, name, ip, role="validator", port_offset=0, image="x", port_bindings=None,
                 link_params=None, **kwargs):
        self.name, self.ip, self.role = name, ip, role
        self.link_params = dict(link_params or {})


class FakeClient:
    def __init__(self, name="client", ip="10.0.0.100", link_params=None):
        self.name, self.ip = name, ip
        self.link_params = dict(link_params or {})


def make_net(exp=None, tmp=None, **kwargs):
    exp = exp or FakeExp()
    net = network_mod.IotaNetwork(
        experiment=exp, auto_cleanup=False,
        workspace_root=Path(tmp or tempfile.mkdtemp(prefix="mt_test_")), **kwargs,
    )
    return net, exp


def build_three_tier(net, **topo_kwargs):
    net.use_three_tier_topology(**topo_kwargs)
    for i in range(1, 5):
        net.add_validator(f"iota{i}", f"10.0.0.{i}", tier=Tier.CLOUD)
    net.add_gateway("gateway", "10.0.0.5", tier="fog")
    net.set_client(FakeClient(), tier="edge")


class _PatchedNode(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(network_mod, "IotaNode", FakeNode)
        p.start()
        self.addCleanup(p.stop)


# ---------------------------------------------------------------------------
# Pure model
# ---------------------------------------------------------------------------
class LinkProfileTests(unittest.TestCase):
    def test_valid_profile_to_params_only_includes_set_fields(self):
        p = LinkProfile(delay="20ms", bw=50, loss=1.5)
        self.assertEqual(p.to_params(), {"delay": "20ms", "bw": 50, "loss": 1.5})
        self.assertEqual(LinkProfile().to_params(), {})
        self.assertFalse(LinkProfile().is_shaped)

    def test_rejects_invalid_values(self):
        for bad in (
            {"delay": "fast"}, {"delay": "20"}, {"bw": 0}, {"bw": 1001}, {"bw": -5},
            {"loss": -1}, {"loss": 100.1}, {"max_queue_size": 0}, {"jitter": "5ms"},  # jitter w/o delay
        ):
            with self.subTest(bad=bad), self.assertRaises(TopologyError):
                LinkProfile(**bad)

    def test_from_params_rejects_typos(self):
        with self.assertRaises(TopologyError) as ctx:
            LinkProfile.from_params({"latency": "10ms"})
        self.assertIn("latency", str(ctx.exception))

    def test_merge_override_is_field_by_field(self):
        base = LinkProfile(delay="10ms", bw=100)
        merged = LinkProfile(delay="30ms", loss=2).merged_over(base)
        self.assertEqual(merged.to_params(), {"delay": "30ms", "bw": 100, "loss": 2})

    def test_delay_units(self):
        self.assertEqual(LinkProfile(delay="1s").delay_ms, 1000.0)
        self.assertAlmostEqual(LinkProfile(delay="500us").delay_ms, 0.5)

    def test_tier_name_normalisation(self):
        self.assertEqual(tier_name(Tier.EDGE), "edge")
        self.assertEqual(tier_name("fog"), "fog")
        self.assertIsNone(tier_name(None))
        with self.assertRaises(TopologyError):
            tier_name("1bad name")


class TopologySpecTests(unittest.TestCase):
    def test_three_tier_is_a_chain_and_valid(self):
        t = three_tier_topology()
        self.assertEqual(list(t.tiers), ["edge", "fog", "cloud"])
        self.assertEqual([(l.a, l.b) for l in t.links], [("edge", "fog"), ("fog", "cloud")])

    def test_path_and_expected_rtt(self):
        t = three_tier_topology(edge_fog={"delay": "20ms"}, fog_cloud={"delay": "50ms"})
        self.assertEqual([(l.a, l.b) for l in t.path("edge", "cloud")], [("edge", "fog"), ("fog", "cloud")])
        self.assertEqual(t.path("fog", "fog"), [])
        self.assertEqual(t.expected_rtt_ms("edge", "fog"), 40.0)       # 2 x 20
        self.assertEqual(t.expected_rtt_ms("edge", "cloud"), 140.0)    # 2 x (20 + 50)
        self.assertEqual(t.expected_rtt_ms("cloud", "edge"), 140.0)    # symmetric
        self.assertEqual(t.expected_rtt_ms("cloud", "cloud"), 0.0)

    def test_access_links_are_part_of_the_rtt(self):
        t = three_tier_topology(edge_fog={"delay": "20ms"}, fog_cloud={"delay": "50ms"})
        rtt = t.expected_rtt_ms("edge", "cloud", src_access=LinkProfile(delay="5ms"), dst_access=LinkProfile(delay="1ms"))
        self.assertEqual(rtt, 2 * (5 + 20 + 50 + 1))

    def test_cycle_is_rejected(self):
        t = TopologySpec()
        for n in "abc":
            t.add_tier(n)
        t.connect("a", "b")
        t.connect("b", "c")
        t.connect("c", "a")
        with self.assertRaises(TopologyError) as ctx:
            t.validate()
        self.assertIn("loop", str(ctx.exception))

    def test_parallel_link_counts_as_a_loop(self):
        t = TopologySpec()
        t.add_tier("a")
        t.add_tier("b")
        t.connect("a", "b")
        t.connect("a", "b")
        with self.assertRaises(TopologyError):
            t.validate()

    def test_disconnected_undeclared_and_self_links(self):
        t = TopologySpec()
        t.add_tier("a")
        t.add_tier("b")
        with self.assertRaises(TopologyError) as ctx:
            t.validate()
        self.assertIn("not all connected", str(ctx.exception))

        u = TopologySpec()
        u.add_tier("a")
        u.connect("a", "zzz")
        with self.assertRaises(TopologyError):
            u.validate()

        s = TopologySpec()
        s.add_tier("a")
        s.connect("a", "a")
        with self.assertRaises(TopologyError):
            s.validate()

    def test_duplicate_tier(self):
        t = TopologySpec()
        t.add_tier("a")
        with self.assertRaises(TopologyError):
            t.add_tier("a")


# ---------------------------------------------------------------------------
# IotaNetwork wiring
# ---------------------------------------------------------------------------
class NetworkAttachTests(_PatchedNode):
    def test_three_switches_chained_with_heterogeneous_links(self):
        net, exp = make_net()
        build_three_tier(
            net,
            edge_fog={"delay": "20ms", "bw": 50, "loss": 1},
            fog_cloud={"delay": "50ms", "bw": 100, "loss": 0.1},
        )
        net.attach_to_experiment()

        # one switch per tier
        self.assertEqual(set(exp.instances), {"edge", "fog", "cloud"})
        self.assertEqual(len({i.switch for i in exp.instances.values()}), 3)
        self.assertEqual(net.tier_switches, {n: i.switch for n, i in exp.instances.items()})

        # nodes sit on the right tier switch and keep their EXACT static IPs
        placed = {c.name: (label, c.ip) for c, label, _ in exp.docker}
        for i in range(1, 5):
            self.assertEqual(placed[f"iota{i}"], ("cloud", f"10.0.0.{i}"))
        self.assertEqual(placed["gateway"], ("fog", "10.0.0.5"))
        self.assertEqual(placed["client"], ("edge", "10.0.0.100"))

        # inter-tier links carry their own delay/bw/loss
        self.assertEqual(
            exp.links,
            [
                ("edge", "fog", {"delay": "20ms", "bw": 50, "loss": 1}),
                ("fog", "cloud", {"delay": "50ms", "bw": 100, "loss": 0.1}),
            ],
        )

    def test_access_link_precedence_node_over_tier(self):
        net, exp = make_net()
        net.use_three_tier_topology(cloud_access={"delay": "1ms", "bw": 1000})
        net.add_validator("v1", "10.0.0.1", tier="cloud")                                   # tier default
        net.add_validator("v2", "10.0.0.2", tier="cloud", link_params={"delay": "9ms"})     # override delay only
        net.add_gateway("gw", "10.0.0.5", tier="fog", link_params={"loss": 2})
        net.set_client(FakeClient(), tier="edge", link_params={"bw": 10})
        net.attach_to_experiment()

        applied = {c.name: params for c, _l, params in exp.docker}
        self.assertEqual(applied["v1"], {"delay": "1ms", "bw": 1000})
        self.assertEqual(applied["v2"], {"delay": "9ms", "bw": 1000})
        self.assertEqual(applied["gw"], {"loss": 2})
        self.assertEqual(applied["client"], {"bw": 10})
        self.assertEqual(net.effective_access_profile("v2").delay, "9ms")

    def test_client_constructor_link_params_are_preserved(self):
        net, exp = make_net()
        net.use_three_tier_topology()
        net.add_validator("v1", "10.0.0.1", tier="cloud")
        net.add_gateway("gw", "10.0.0.5", tier="fog")
        net.set_client(FakeClient(link_params={"delay": "3ms"}), tier="edge")
        net.attach_to_experiment()
        self.assertEqual({c.name: p for c, _l, p in exp.docker}["client"], {"delay": "3ms"})

    def test_backward_compatible_single_switch(self):
        net, exp = make_net()
        net.add_validator("v1", "10.0.0.1")
        net.add_gateway("gw", "10.0.0.5")
        net.set_client(FakeClient())
        net.attach_to_experiment("cloud")
        self.assertEqual(set(exp.instances), {"cloud"})
        self.assertEqual({label for _c, label, _p in exp.docker}, {"cloud"})
        self.assertEqual(exp.links, [])
        self.assertEqual(net.describe_topology()["mode"], "single-switch")

    def test_tier_without_declared_topology_is_an_error(self):
        net, _ = make_net()
        net.add_validator("v1", "10.0.0.1", tier="cloud")
        with self.assertRaises(TopologyError) as ctx:
            net.attach_to_experiment()
        self.assertIn("none is declared", str(ctx.exception))

    def test_node_without_tier_or_unknown_tier_is_an_error(self):
        net, _ = make_net()
        net.use_three_tier_topology()
        net.add_validator("v1", "10.0.0.1")  # no tier
        with self.assertRaises(TopologyError):
            net.attach_to_experiment()

        net2, _ = make_net()
        net2.use_three_tier_topology()
        net2.add_validator("v1", "10.0.0.1", tier="mars")
        with self.assertRaises(TopologyError) as ctx:
            net2.attach_to_experiment()
        self.assertIn("mars", str(ctx.exception))

    def test_loop_in_tier_graph_is_rejected_before_creating_anything(self):
        net, exp = make_net()
        for n in ("a", "b", "c"):
            net.add_tier(n)
        net.connect_tiers("a", "b", delay="1ms")
        net.connect_tiers("b", "c", delay="1ms")
        net.connect_tiers("c", "a", delay="1ms")
        net.add_validator("v1", "10.0.0.1", tier="a")
        with self.assertRaises(TopologyError):
            net.attach_to_experiment()
        self.assertEqual(exp.instances, {})
        self.assertEqual(exp.docker, [])

    def test_refuses_to_attach_to_a_running_mininet(self):
        net, exp = make_net(FakeExp(running=True))
        build_three_tier(net)
        with self.assertRaises(TopologyError) as ctx:
            net.attach_to_experiment()
        self.assertIn("BEFORE exp.start", str(ctx.exception))

    def test_duplicate_and_invalid_endpoints(self):
        net, _ = make_net()
        net.add_validator("v1", "10.0.0.1")
        with self.assertRaises(TopologyError):
            net.add_validator("v1", "10.0.0.2")          # duplicate name
        with self.assertRaises(TopologyError):
            net.add_validator("v2", "10.0.0.1")          # duplicate IP
        with self.assertRaises(TopologyError):
            net.add_validator("v3", "not-an-ip")
        with self.assertRaises(TopologyError):
            net.add_gateway("gw", "10.0.0.9", link_params={"delay": "x"})
        with self.assertRaises(TopologyError):
            net.add_validator("v4", "10.0.0.4", link_params={"bandwidth": 5})
        self.assertEqual(list(net.node_specs), ["v1"])   # failed registrations leave no residue
        net.set_client(FakeClient(ip="10.0.0.100"))
        with self.assertRaises(TopologyError):
            net.add_validator("v5", "10.0.0.100")        # clashes with the client

    def test_describe_topology(self):
        net, _ = make_net()
        build_three_tier(net)
        net.attach_to_experiment()
        d = net.describe_topology()
        self.assertEqual(d["mode"], "multi-tier")
        self.assertEqual(set(d["tiers"]), {"edge", "fog", "cloud"})
        self.assertEqual({n["name"] for n in d["tiers"]["cloud"]["nodes"]}, {"iota1", "iota2", "iota3", "iota4"})
        self.assertEqual(d["tiers"]["edge"]["nodes"][0]["role"], "client")
        self.assertEqual(len(d["links"]), 2)

    def test_readiness_timeout_scales_with_topology(self):
        net, _ = make_net()
        self.assertIsNone(net.readiness_timeout)
        net2, _ = make_net(readiness_timeout=77)
        self.assertEqual(net2.readiness_timeout, 77)


# ---------------------------------------------------------------------------
# Client provisioning
# ---------------------------------------------------------------------------
KEYSTORE = {
    "version": 2,
    "keys": [
        {"alias": "a", "address": "0x" + "aa" * 32, "key": {"type": "key_pair", "value": "iotaprivkey1x"}},
        {"alias": "b", "address": "0x" + "bb" * 32, "key": {"type": "key_pair", "value": "iotaprivkey1y"}},
    ],
}


class ClientProvisionTests(_PatchedNode):
    def test_keystore_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            ks = Path(tmp) / "iota.keystore"
            ks.write_text(json.dumps(KEYSTORE))
            self.assertEqual(network_mod.IotaNetwork._keystore_addresses(ks), ["0x" + "aa" * 32, "0x" + "bb" * 32])
            ks.write_text("not json")
            self.assertEqual(network_mod.IotaNetwork._keystore_addresses(ks), [])
            self.assertEqual(network_mod.IotaNetwork._keystore_addresses(Path(tmp) / "missing"), [])

    def test_provision_client_installs_gateway_config_and_funded_keystore(self):
        import yaml

        with tempfile.TemporaryDirectory() as tmp:
            ks = Path(tmp) / "iota.keystore"
            ks.write_text(json.dumps(KEYSTORE))
            net, _ = make_net(tmp=Path(tmp) / "ws")
            build_three_tier(net)
            net.genesis_artifacts = SimpleNamespace(iota_keystore=ks, nodes={})

            calls = []

            def fake_run(cmd, **kw):
                calls.append(list(cmd))
                return SimpleNamespace(stdout="", returncode=0)   # printenv empty -> image default dir

            with mock.patch.object(network_mod.subprocess, "run", side_effect=fake_run):
                self.assertTrue(net.provision_client())

            copies = {c[-1]: c[-2] for c in calls if c[:2] == ["docker", "cp"]}
            self.assertIn("mn.client:/iota/config/iota.keystore", copies)      # default CLI dir ($IOTA_CONFIG_DIR)
            self.assertIn("mn.client:/iota/config/client.yaml", copies)
            self.assertIn("mn.client:/app/config/client.yaml", copies)         # IotaCLI default path
            cfg = yaml.safe_load(Path(copies["mn.client:/iota/config/client.yaml"]).read_text())
            self.assertEqual(cfg["envs"][0]["rpc"], "http://10.0.0.5:9000")    # gateway on the FOG tier
            self.assertEqual(cfg["active_env"], "fogbed")
            self.assertEqual(cfg["active_address"], "0x" + "aa" * 32)
            self.assertEqual(cfg["keystore"], {"File": "/iota/config/iota.keystore"})
            self.assertEqual(net.client_recipient, "0x" + "bb" * 32)
            self.assertTrue(net.client_provisioned)
            self.assertEqual(net.client_config_path, "/iota/config/client.yaml")

    def test_provision_without_keystore_or_client_is_a_noop(self):
        net, _ = make_net()
        self.assertFalse(net.provision_client())                      # no client
        build_three_tier(net)
        net.genesis_artifacts = SimpleNamespace(iota_keystore=None, nodes={})
        self.assertFalse(net.provision_client())                      # no funded keystore
        self.assertFalse(net.client_provisioned)


# ---------------------------------------------------------------------------
# Verifier: parsing helpers
# ---------------------------------------------------------------------------
class ParsingTests(unittest.TestCase):
    def test_ping_parsing(self):
        linux = "6 packets transmitted, 6 received, 0% packet loss, time 1004ms\nrtt min/avg/max/mdev = 40.1/42.5/45.0/1.2 ms"
        busy = "round-trip min/avg/max = 1.0/2.0/3.0 ms"
        self.assertEqual(mc.parse_ping_avg_ms(linux), 42.5)
        self.assertEqual(mc.parse_ping_avg_ms(busy), 2.0)
        self.assertEqual(mc.parse_ping_received(linux), 6)
        self.assertIsNone(mc.parse_ping_avg_ms("100% packet loss"))
        self.assertEqual(mc.parse_ping_received("0 packets received"), 0)

    def test_rtt_window(self):
        low, high = mc.rtt_window(0)
        self.assertEqual((low, high), (0.0, 25.0))
        low, high = mc.rtt_window(140)
        self.assertTrue(low < 140 < high)
        self.assertGreater(low, 100)       # an unshaped 0.4 ms RTT must be rejected
        self.assertLess(high, 260)

    def test_jsonrpc_and_checkpoint_parsing(self):
        ok = 'noise {"jsonrpc":"2.0","result":"4c78adac","id":1}'
        err = '{"jsonrpc":"2.0","error":{"code":-32601,"message":"nope"},"id":1}'
        self.assertEqual(mc.parse_jsonrpc_result(ok), "4c78adac")
        self.assertIsNone(mc.parse_jsonrpc_result(err))
        self.assertIsNone(mc.parse_jsonrpc_result(""))
        self.assertIsNone(mc.parse_jsonrpc_result("curl: (7) Failed to connect"))
        self.assertEqual(mc.parse_checkpoint_seq('{"result":"790"}'), 790)
        self.assertEqual(mc.parse_checkpoint_seq('{"result":790}'), 790)
        self.assertIsNone(mc.parse_checkpoint_seq('{"result":"abc"}'))

    def test_port_parsing(self):
        self.assertEqual(mc.multiaddr_port("/ip4/0.0.0.0/tcp/8080/http", "tcp"), 8080)
        self.assertEqual(mc.multiaddr_port("/ip4/10.0.0.1/udp/8084/quic", "udp"), 8084)
        self.assertIsNone(mc.multiaddr_port("/ip4/10.0.0.1", "tcp"))
        self.assertEqual(mc.hostport_port("0.0.0.0:9184"), 9184)
        self.assertIsNone(mc.hostport_port("nonsense"))

    def test_jsonrpc_curl_is_shell_safe(self):
        cmd = mc.jsonrpc_curl("10.0.0.5", 9000, "iota_getChainIdentifier")
        self.assertIn("http://10.0.0.5:9000", cmd)
        self.assertIn("-m 10", cmd)


# ---------------------------------------------------------------------------
# Verifier: scripted end-to-end
# ---------------------------------------------------------------------------
class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def write_node_yaml(dirpath, name, gateway=False):
    cfg = {
        "network-address": "/ip4/0.0.0.0/tcp/8080/http",
        "p2p-config": {"listen-address": "0.0.0.0:8084"},
        "metrics-address": "0.0.0.0:9184",
    }
    if gateway:
        cfg["json-rpc-address"] = "0.0.0.0:9000"
    import yaml

    p = Path(dirpath) / f"{name}.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


class VerifierTests(_PatchedNode):
    def _net(self, tmp, **topo):
        net, _ = make_net(tmp=tmp)
        build_three_tier(net, edge_fog={"delay": "20ms", "bw": 50}, fog_cloud={"delay": "50ms", "bw": 100}, **topo)
        net.attach_to_experiment()
        arts = {n: SimpleNamespace(validator_yaml=write_node_yaml(tmp, n, gateway=(n == "gateway")))
                for n in net.node_specs}
        net.genesis_artifacts = SimpleNamespace(nodes=arts, iota_keystore=None)
        return net

    def _exec(self, net, *, rtt=None, rpc_ok=True, advancing=True, tcp_ok=True):
        ips = {n: s.ip for n, s in net.node_specs.items()}
        ips["client"] = net.client_container.ip
        by_ip = {v: k for k, v in ips.items()}
        seq = {"n": 100}
        tier_of = {n: s.tier for n, s in net.node_specs.items()}
        tier_of["client"] = net.client_tier

        def exec_fn(container, command, timeout):
            if command.startswith("ip -4 -o addr show"):
                return 0, f"2: eth0    inet {ips[container]}/8 scope global eth0"
            if command.startswith("tc qdisc show"):
                return 0, "qdisc netem 8001: root refcnt 2 limit 1000 delay 2ms loss 1%\nqdisc htb 5: root"
            if command.startswith("ping"):
                dst = by_ip[command.split()[-1]]
                expected = net.topology.expected_rtt_ms(
                    tier_of[container], tier_of[dst],
                    src_access=net.effective_access_profile(container),
                    dst_access=net.effective_access_profile(dst),
                )
                avg = (expected + 3) if rtt is None else rtt
                return 0, f"6 packets transmitted, 6 received, 0% packet loss\nrtt min/avg/max/mdev = {avg-1:.3f}/{avg:.3f}/{avg+1:.3f}/0.5 ms"
            if "iota_getChainIdentifier" in command:
                return (0, '{"jsonrpc":"2.0","result":"4c78adac","id":1}') if rpc_ok else (7, "curl: (7) Failed to connect")
            if "/metrics" in command:
                return 0, "# HELP iota_x demo\n# TYPE iota_x counter\n"
            if "/dev/tcp/" in command:
                return (0, "") if tcp_ok else (1, "")
            if command.startswith("ss -uln"):
                return 0, "UNCONN 0 0 0.0.0.0:8084 0.0.0.0:*"
            if "iota_getLatestCheckpointSequenceNumber" in command:
                if advancing:
                    seq["n"] += 5
                return 0, json.dumps({"jsonrpc": "2.0", "result": str(seq["n"]), "id": 1})
            raise AssertionError(f"unscripted command on {container}: {command}")

        return exec_fn

    def _run(self, net, exec_fn, **kw):
        clock = FakeClock()
        return mc.validate_topology(net, exec_fn=exec_fn, sleep=clock.sleep, clock=clock,
                                    send_transaction=False, progress_timeout=9, **kw)

    def test_happy_path_passes_every_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = self._net(tmp, edge_access={"delay": "2ms"})
            rep = self._run(net, self._exec(net))
            self.assertTrue(rep.ok, rep.format())
            names = [r.name for r in rep.results]
            for expected in (
                "ip:client", "ip:gateway", "ip:iota1",
                "rtt:client->gateway", "rtt:client->iota4",
                "rpc:client->gateway:9000", "metrics:client->gateway:9184",
                "tcp:client->iota1:8080", "tcp:gateway->iota1:8080",
                "udp:iota1:8084", "consensus", "tc:client",
            ):
                self.assertIn(expected, names)
            rep.raise_for_failure()  # must not raise

    def test_cross_tier_rtt_reflects_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = self._net(tmp)  # no access links
            # edge->fog = 2*20 = 40 ; edge->cloud = 2*(20+50) = 140
            self.assertEqual(net.topology.expected_rtt_ms("edge", "fog"), 40)
            self.assertEqual(net.topology.expected_rtt_ms("edge", "cloud"), 140)
            rep = self._run(net, self._exec(net))
            detail = {r.name: r.detail for r in rep.results}
            self.assertIn("expected≈40ms", detail["rtt:client->gateway"])
            self.assertIn("expected≈140ms", detail["rtt:client->iota1"])

    def test_unshaped_links_are_detected_by_rtt(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = self._net(tmp)
            rep = self._run(net, self._exec(net, rtt=0.4))   # shaping silently not applied
            self.assertFalse(rep.ok)
            self.assertTrue(all(f.name.startswith("rtt:") for f in rep.failures), rep.format())
            with self.assertRaises(TopologyValidationError):
                rep.raise_for_failure()

    def test_unreachable_gateway_rpc_fails_and_terminates(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = self._net(tmp)
            rep = self._run(net, self._exec(net, rpc_ok=False))
            self.assertFalse(rep.ok)
            self.assertIn("rpc:client->gateway:9000", [f.name for f in rep.failures])

    def test_stalled_consensus_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = self._net(tmp)
            rep = self._run(net, self._exec(net, advancing=False))
            self.assertIn("consensus", [f.name for f in rep.failures])

    def test_blocked_validator_tcp_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = self._net(tmp)
            rep = self._run(net, self._exec(net, tcp_ok=False))
            self.assertTrue(any(f.name.startswith("tcp:") for f in rep.failures))

    def test_tx_check_requires_a_provisioned_funded_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            net = self._net(tmp)
            clock = FakeClock()
            rep = mc.validate_topology(net, exec_fn=self._exec(net), sleep=clock.sleep, clock=clock,
                                       send_transaction=True, progress_timeout=9)
            tx = [r for r in rep.results if r.name == "tx:pay-iota"][0]
            self.assertFalse(tx.ok)
            self.assertIn("not provisioned", tx.detail)

    def test_needs_gateway_and_validator(self):
        net, _ = make_net()
        net.add_validator("v1", "10.0.0.1")
        rep = mc.validate_topology(net, exec_fn=lambda *a: (0, ""))
        self.assertFalse(rep.ok)
        self.assertEqual(rep.results[0].name, "preconditions")

    def test_optional_failures_do_not_fail_the_report(self):
        rep = mc.TopologyReport()
        rep.add("a", True)
        rep.add("tc:x", False, "diag", optional=True)
        self.assertTrue(rep.ok)
        rep.add("b", False)
        self.assertFalse(rep.ok)
        self.assertEqual([f.name for f in rep.failures], ["b"])


if __name__ == "__main__":
    unittest.main()
