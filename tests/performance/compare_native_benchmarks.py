"""Alternate native Release benchmarks and compare outputs; no game is started."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pairs", type=int, default=9)
    parser.add_argument("--build-description", default="Unspecified; see build configuration")
    parser.add_argument("--test-function", default="measured_scan")
    parser.add_argument("--report-env", default="BUGG_SCAN_REPORT")
    parser.add_argument("--time-field", default="scanMs")
    parser.add_argument("--scenario-fields", default="instances,indexes,indexBytes")
    parser.add_argument("--extra-metrics", default="")
    parser.add_argument("--timing-description", default="GameRuntime.refresh_instances through instances_changed, including GUI delivery")
    args = parser.parse_args()
    if args.pairs < 3:
        parser.error("Use at least three paired samples")
    args.output.mkdir(parents=True, exist_ok=True)
    scenarios = {}
    for iteration in range(args.pairs):
        variants = [("before", args.before), ("after", args.after)]
        if iteration % 2:
            variants.reverse()
        for variant, binary in variants:
            prefix = args.output / f"{iteration}-{variant}"
            environment = dict(os.environ)
            environment[args.report_env] = str(prefix.resolve())
            result = subprocess.run(
                [str(binary.resolve()), args.test_function, "-o", str(prefix) + ".txt,txt"],
                env=environment, timeout=120, check=False)
            if result.returncode:
                raise RuntimeError(f"{variant} failed: see {prefix}.txt")
            for path in sorted(args.output.glob(prefix.name + "-*.json")):
                sample = json.loads(path.read_text(encoding="utf-8"))
                fields = {key: sample[key] for key in args.scenario_fields.split(',') if key}
                scenario = scenarios.setdefault(sample["scenario"], {
                    **fields, "beforeMs": [], "afterMs": [], "metrics": {}})
                if any(scenario[key] != value for key, value in fields.items()):
                    raise AssertionError("Fixture changed between builds")
                expected = scenario.setdefault("outputHash", sample["outputHash"])
                if expected != sample["outputHash"]:
                    raise AssertionError("Production results differ")
                scenario[variant + "Ms"].append(sample[args.time_field])
                for key in args.extra_metrics.split(','):
                    if key:
                        scenario["metrics"].setdefault(key, {"before": [], "after": []})[variant].append(sample[key])
        print(f"Paired sample {iteration + 1}/{args.pairs}", flush=True)
    for name, scenario in scenarios.items():
        for variant in ("before", "after"):
            samples = scenario[variant + "Ms"]
            if len(samples) != args.pairs:
                raise AssertionError("Missing benchmark samples")
            scenario[variant + "MedianMs"] = statistics.median(samples)
            scenario[variant + "RangeMs"] = [min(samples), max(samples)]
        scenario["timeReductionPercent"] = 100 * (
            1 - scenario["afterMedianMs"] / scenario["beforeMedianMs"])
        print(f"{name}: {scenario['beforeMedianMs']:.3f} -> "
              f"{scenario['afterMedianMs']:.3f} ms "
              f"({scenario['timeReductionPercent']:.2f}% less time)")
    report = {
        "system": platform.platform(), "architecture": platform.machine(),
        "processor": platform.processor(), "logicalProcessors": os.cpu_count(),
        "pairs": args.pairs,
        "build": args.build_description,
        "cache": "Warm OS file cache, one warm-up per process, alternating build order",
        "timing": args.timing_description,
        "binaries": {name: {"path": str(path.resolve()),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                     for name, path in [("before", args.before), ("after", args.after)]},
        "scenarios": scenarios}
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
