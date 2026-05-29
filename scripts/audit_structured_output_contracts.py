#!/usr/bin/env python3
"""Audit Structured Output Contract Registry.

Validates all registered contracts for completeness and consistency.
Does not require ES, LLM, or any external service.

Usage:
    python scripts/audit_structured_output_contracts.py
    python scripts/audit_structured_output_contracts.py --json
    python scripts/audit_structured_output_contracts.py --agent trade_decision
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ibkr_show_backend"))

from app.agents.structured_output.registry import (
    StructuredOutputContractSpec,
    get_contract_spec_by_name,
    get_structured_output_contract_specs,
)


def audit(*, agent_filter: str | None = None, output_json: bool = False) -> int:
    specs = get_structured_output_contract_specs()
    if agent_filter:
        specs = [s for s in specs if agent_filter in s.agent_name or agent_filter in s.owner]

    errors: list[str] = []
    seen_names: set[str] = set()

    for spec in specs:
        if spec.name in seen_names:
            errors.append(f"DUPLICATE name: {spec.name}")
        seen_names.add(spec.name)

        if not spec.agent_name:
            errors.append(f"{spec.name}: agent_name is empty")
        if not spec.node_name:
            errors.append(f"{spec.name}: node_name is empty")
        if not spec.output_model_name:
            errors.append(f"{spec.name}: output_model_name is empty")
        if not spec.description:
            errors.append(f"{spec.name}: description is empty")
        if spec.examples_count < 1:
            errors.append(f"{spec.name}: examples_count={spec.examples_count} (must be >= 1)")
        if not spec.schema_hint_available:
            errors.append(f"{spec.name}: schema_hint_available=False (must be True)")
        if spec.max_repair_attempts < 0:
            errors.append(f"{spec.name}: max_repair_attempts={spec.max_repair_attempts} (must be >= 0)")

    if output_json:
        report = {
            "total": len(specs),
            "errors": errors,
            "passed": len(errors) == 0,
            "specs": [
                {
                    "name": s.name,
                    "agent_name": s.agent_name,
                    "node_name": s.node_name,
                    "output_model_name": s.output_model_name,
                    "max_repair_attempts": s.max_repair_attempts,
                    "examples_count": s.examples_count,
                    "repair_enabled": s.repair_enabled,
                    "fallback_enabled": s.fallback_enabled,
                    "dynamic_fallback": s.dynamic_fallback,
                    "owner": s.owner,
                }
                for s in specs
            ],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        header = f"{'name':<45} {'agent':<25} {'node':<25} {'model':<35} {'repair':>6} {'ex':>3} {'rep':>3} {'fb':>3} {'dyn':>3}"
        print(header)
        print("-" * len(header))
        for s in specs:
            print(
                f"{s.name:<45} {s.agent_name:<25} {s.node_name:<25} {s.output_model_name:<35} "
                f"{s.max_repair_attempts:>6} {s.examples_count:>3} "
                f"{'Y' if s.repair_enabled else 'N':>3} {'Y' if s.fallback_enabled else 'N':>3} "
                f"{'Y' if s.dynamic_fallback else 'N':>3}"
            )
        print()
        if errors:
            print("FAIL:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("PASS")
        print(f"\nTotal: {len(specs)} contracts, {len(errors)} errors")

    return 1 if errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Structured Output Contract Registry")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--agent", type=str, default=None, help="Filter by agent name")
    args = parser.parse_args()
    sys.exit(audit(agent_filter=args.agent, output_json=args.json))


if __name__ == "__main__":
    main()
