"""Convert saved GitHub pull-request and review metadata into stage observations."""

import argparse
import csv
import json
import sys
from pathlib import Path

from reconstruct import parse_time


def write_observations(pulls, stream):
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("case", "stage", "timestamp", "source"))
    for pull in pulls:
        number, url = pull["number"], pull["url"]
        if pull["draft"]:
            continue
        writer.writerow((number, "Opened", pull["created_at"], url))
        ended_at = pull["merged_at"] or pull["closed_at"]
        end = parse_time(ended_at, None) if ended_at else None
        reviews = sorted(
            ((parse_time(review["submitted_at"], None), review)
             for review in pull["reviews"]
             if review["submitted_at"] and review["state"] != "PENDING"),
            key=lambda entry: entry[0],
        )
        for index, (submitted, review) in enumerate(reviews):
            if end is not None and submitted > end:
                break
            state = review["state"]
            if index > 0 and state not in {"APPROVED", "CHANGES_REQUESTED"}:
                continue
            writer.writerow((
                number, f"Review: {state}", review["submitted_at"],
                f'{url}#pullrequestreview-{review["id"]}',
            ))
        if ended_at:
            writer.writerow((number, "Merged" if pull["merged_at"] else "Closed", ended_at, url))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args()
    write_observations(json.loads(args.json_path.read_text(encoding="utf-8-sig")), sys.stdout)
