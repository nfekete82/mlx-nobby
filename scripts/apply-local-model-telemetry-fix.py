from pathlib import Path

obs_path = Path("backend/observability.py")
provider_path = Path("agent/model_provider.py")
obs_test_path = Path("tests/test_observability.py")
provider_test_path = Path("tests/test_model_provider.py")
helper_path = Path(__file__)

obs = obs_path.read_text()

old = 'def safe_model_metadata(model=None, role=None, alias=None, backend=None):\n'
new = 'def safe_model_metadata(model=None, role=None, alias=None, backend=None, local=None):\n'
if old not in obs:
    raise SystemExit("safe_model_metadata signature anchor not found")
obs = obs.replace(old, new, 1)

old = '''    if value:\n        is_local = value.startswith(("/", "~"))\n        metadata["local"] = is_local\n        metadata["identifier"] = Path(value).name if is_local else value\n        metadata["identifier_hash"] = hashlib.sha256(\n            value.encode("utf-8")\n        ).hexdigest()[:16]\n'''
new = '''    if value:\n        path_local = value.startswith(("/", "~"))\n        metadata["local"] = path_local if local is None else bool(local)\n        metadata["identifier"] = Path(value).name if path_local else value\n        metadata["identifier_hash"] = hashlib.sha256(\n            value.encode("utf-8")\n        ).hexdigest()[:16]\n'''
if old not in obs:
    raise SystemExit("safe_model_metadata body anchor not found")
obs = obs.replace(old, new, 1)

old = '''        alias=None,\n        backend=None,\n        messages=None,\n'''
new = '''        alias=None,\n        backend=None,\n        local=None,\n        messages=None,\n'''
if old not in obs:
    raise SystemExit("ModelCallMetrics init signature anchor not found")
obs = obs.replace(old, new, 1)

old = '''                alias=alias,\n                backend=backend,\n            ),\n'''
new = '''                alias=alias,\n                backend=backend,\n                local=local,\n            ),\n'''
if old not in obs:
    raise SystemExit("ModelCallMetrics init metadata anchor not found")
obs = obs.replace(old, new, 1)

old = '    def set_model(self, model=None, role=None, alias=None, backend=None):\n'
new = '    def set_model(self, model=None, role=None, alias=None, backend=None, local=None):\n'
if old not in obs:
    raise SystemExit("set_model signature anchor not found")
obs = obs.replace(old, new, 1)

old = '''                alias=alias,\n                backend=backend,\n            )\n\n    def set_upstream_connect'''
new = '''                alias=alias,\n                backend=backend,\n                local=local,\n            )\n\n    def set_upstream_connect'''
if old not in obs:
    raise SystemExit("set_model metadata anchor not found")
obs = obs.replace(old, new, 1)

obs_path.write_text(obs)

provider = provider_path.read_text()
old = '''        metrics.set_model(\n            model=model, role=request.role,\n            alias=role.get("alias"), backend=role.get("backend"),\n        )\n'''
new = '''        metrics.set_model(\n            model=model, role=request.role,\n            alias=role.get("alias"), backend=role.get("backend"),\n            local=True,\n        )\n'''
if old not in provider:
    raise SystemExit("MLXProvider metrics anchor not found")
provider = provider.replace(old, new, 1)
provider_path.write_text(provider)

obs_tests = obs_test_path.read_text()
anchor = '''    def test_call_counter_remains_exact_when_details_are_bounded(self):\n'''
insert = '''    def test_explicit_local_flag_keeps_repo_identifier_and_marks_local(self):\n        metadata = observability.safe_model_metadata(\n            model="mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",\n            role="coding",\n            local=True,\n        )\n\n        self.assertTrue(metadata["local"])\n        self.assertEqual(\n            metadata["identifier"],\n            "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",\n        )\n\n    def test_repo_identifier_is_not_local_without_explicit_transport_hint(self):\n        metadata = observability.safe_model_metadata(\n            model="mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",\n            role="coding",\n        )\n\n        self.assertFalse(metadata["local"])\n\n'''
if anchor not in obs_tests:
    raise SystemExit("observability test anchor not found")
obs_tests = obs_tests.replace(anchor, insert + anchor, 1)
obs_test_path.write_text(obs_tests)

provider_tests = provider_test_path.read_text()
old = '''                self.assertEqual(metric["usage"], response.usage)\n                self.assertEqual(metric["status"], "completed")\n                self.assertIsNotNone(metric["timings_ms"]["queue_wait"])\n'''
new = '''                self.assertEqual(metric["usage"], response.usage)\n                self.assertEqual(metric["status"], "completed")\n                self.assertTrue(metric["model"]["local"])\n                self.assertEqual(metric["model"]["identifier"], "local/model")\n                self.assertIsNotNone(metric["timings_ms"]["queue_wait"])\n'''
if old not in provider_tests:
    raise SystemExit("model provider test anchor not found")
provider_tests = provider_tests.replace(old, new, 1)
provider_test_path.write_text(provider_tests)

helper_path.unlink()
print("Applied local model telemetry fix and removed one-shot helper.")
