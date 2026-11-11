"""Reconstruct observed stage changes from a mapped CSV export."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class Observation:
    stage: str
    time: datetime
    row: int
    line: int
    order: int = 0


def parse_time(value, time_format):
    timestamp = (
        datetime.strptime(value, time_format)
        if time_format else datetime.fromisoformat(value)
    )
    if timestamp.utcoffset() is not None:
        try:
            return timestamp.astimezone(timezone.utc)
        except OverflowError as error:
            raise ValueError("timestamp is outside the supported UTC range") from error
    if time_format:
        return timestamp
    raise ValueError("an ISO timestamp needs a UTC offset")


def read_cases(stream, case_column, stage_column, time_column, time_format=None,
               order_column=None):
    reader = csv.reader(stream, strict=True)
    headers = next(reader, [])
    columns = (case_column, stage_column, time_column)
    mapped = (*columns, order_column) if order_column else columns
    if len(set(headers)) != len(headers) or len(set(mapped)) != len(mapped):
        raise ValueError("CSV headers and mapped columns must be distinct")
    if missing := set(mapped) - set(headers):
        raise ValueError(f"missing mapped columns: {', '.join(sorted(missing))}")

    case_index, stage_index, time_index = (headers.index(column) for column in columns)
    order_index = headers.index(order_column) if order_column else None
    cases = defaultdict(list)
    index = 1
    previous_line = reader.line_num
    for row in reader:
        line = previous_line + 1
        previous_line = reader.line_num
        if not row:
            continue
        index += 1
        if len(row) != len(headers):
            raise ValueError(f"CSV line {line}: missing field or extra values")
        case, stage, timestamp = (row[i].strip() for i in (case_index, stage_index, time_index))
        if not case or not stage or not timestamp:
            raise ValueError(f"CSV line {line}: missing field or extra values")
        try:
            time = parse_time(timestamp, time_format)
        except ValueError as error:
            raise ValueError(f"CSV line {line}: invalid timestamp ({error})") from error
        try:
            order = int(row[order_index]) if order_index is not None else 0
        except ValueError as error:
            raise ValueError(f"CSV line {line}: invalid integer order") from error
        cases[case].append(Observation(stage, time, index, line, order))
    return cases


def reconstruct(cases, inspect_case=None, unknown_stages=(), *, include_examples=False):
    transitions = defaultdict(list)
    examples = {}
    returns = Counter()
    ambiguous_cases = 0
    unknown_stage_cases = 0
    cases_with_returns = 0
    report = {}
    for case_id, observations in cases.items():
        ordered = sorted(observations, key=lambda entry: (entry.time, entry.order))
        if any(entry.stage in unknown_stages for entry in ordered):
            unknown_stage_cases += 1
            if case_id == inspect_case:
                report["case"] = {
                    "id": case_id,
                    "status": "unknown stage",
                    "observations": [evidence(entry) for entry in ordered],
                }
            continue
        ambiguous = any(
            first.time == second.time and first.order == second.order
            and first.stage != second.stage
            for first, second in zip(ordered, ordered[1:])
        )
        if ambiguous:
            ambiguous_cases += 1
            if case_id == inspect_case:
                report["case"] = {
                    "id": case_id,
                    "status": "conflicting stages at the same timestamp",
                    "observations": [evidence(entry) for entry in ordered],
                }
            continue

        changes = [ordered[0]]
        for entry in ordered[1:]:
            if entry.stage != changes[-1].stage:
                changes.append(entry)

        seen = {changes[0].stage}
        had_return = False
        for first, second in zip(changes, changes[1:]):
            gap = (second.time - first.time).total_seconds()
            edge = (first.stage, second.stage)
            transitions[edge].append(gap)
            if include_examples and (edge not in examples or gap > examples[edge][0]):
                examples[edge] = (gap, case_id, first, second)
            if second.stage in seen:
                returns[second.stage] += 1
                had_return = True
            seen.add(second.stage)
        cases_with_returns += had_return

        if case_id == inspect_case:
            report["case"] = {
                "id": case_id,
                "status": "ordered",
                "stage_changes": [evidence(entry) for entry in changes],
            }

    report.update(
        records=sum(map(len, cases.values())),
        cases=len(cases),
        ambiguous_cases=ambiguous_cases,
        unknown_stage_cases=unknown_stage_cases,
        analyzed_cases=len(cases) - ambiguous_cases - unknown_stage_cases,
        cases_with_stage_returns=cases_with_returns,
        stage_returns=dict(returns.most_common()),
        transitions=[
            {"from": first, "to": second, "count": len(gaps),
             "median_elapsed_seconds": median(gaps)}
            for (first, second), gaps in sorted(
                transitions.items(), key=lambda item: (-len(item[1]), item[0])
            )
        ],
    )
    if include_examples:
        for transition in report["transitions"]:
            gap, case_id, first, second = examples[transition["from"], transition["to"]]
            transition["example"] = {
                "case": case_id,
                "elapsed_seconds": gap,
                "records": [evidence(first), evidence(second)],
            }
    return report


def evidence(entry):
    return {"stage": entry.stage, "time": entry.time.isoformat(),
            "record": entry.row, "line": entry.line}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--case-column", default="case")
    parser.add_argument("--stage-column", default="stage")
    parser.add_argument("--time-column", default="timestamp")
    parser.add_argument("--time-format", help="Explicit strptime format for legacy timestamps")
    parser.add_argument("--order-column", help="Integer source sequence used to break timestamp ties")
    parser.add_argument("--unknown-stage", action="append", default=[],
                        help="Exclude cases containing this unmapped stage value. Repeatable.")
    parser.add_argument("--inspect", help="Include source record numbers for this case ID")
    args = parser.parse_args()

    try:
        with args.csv_path.open(encoding="utf-8-sig", newline="") as stream:
            cases = read_cases(
                stream, args.case_column, args.stage_column, args.time_column,
                args.time_format, args.order_column
            )
        if args.inspect is not None and args.inspect not in cases:
            raise ValueError("requested case ID is absent")
        result = reconstruct(cases, args.inspect, args.unknown_stage)
    except (OSError, ValueError, csv.Error) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
