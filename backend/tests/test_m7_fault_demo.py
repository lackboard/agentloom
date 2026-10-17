import importlib.util
import sys
from pathlib import Path


def _load_demo_module():
    path = Path(__file__).parents[1] / "labs" / "m7_fault_demo.py"
    spec = importlib.util.spec_from_file_location("m7_fault_demo", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fault_demo_reports_failures_without_violating_invariants(tmp_path) -> None:
    module = _load_demo_module()
    output = tmp_path / "report.json"

    report = module.run_demo(output)

    assert report["mode"] == "deterministic_fault_injection_fake"
    assert report["passed"] is True
    assert [item["name"] for item in report["scenarios"]] == [
        "model_stream_failure",
        "uncertain_write_recovery",
        "coder_validation_failure",
    ]
    assert all(item["passed"] for item in report["scenarios"])
    assert output.is_file()
    assert output.with_suffix(".md").is_file()
