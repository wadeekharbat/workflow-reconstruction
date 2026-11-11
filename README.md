# Workflow reconstruction

Use a CSV export to see where work spent time between recorded stages and which cases returned to an earlier stage. Each transition shows its frequency and median elapsed time. Select a transition to see the original CSV lines for its longest observed example.

## Use the local browser app

From this folder with Python 3.11 or newer, run the following command. The app uses the Python standard library and needs no package installation.

```powershell
python serve.py
```

Open the printed address, normally `http://127.0.0.1:8765`. Select **Open example**, or choose a comma-separated UTF-8 CSV up to 64 MiB and review its case ID, stage and timestamp mapping. Click a transition to see the case and the two source lines. The example duration and the aggregate median appear separately. The server binds to the local machine and processes uploads in memory. Stop it with Ctrl+C. If the default port is in use, try `python serve.py --port 8766`.

For the UCI export, map `number`, `incident_state` and `sys_updated_at`. Under **Timestamp and data options**, choose `sys_mod_count` for tie-break sequence, use `%d/%m/%Y %H:%M` as the timestamp format, and enter `-100` as the unknown stage value.

## Run an example

From this folder with Python 3.11 or newer:

```powershell
python reconstruct.py examples/ci.csv --case-column run_id --stage-column result --time-column recorded_at --inspect run-101
python -B -m unittest discover -v
```

The included CI example is synthetic. `run-101` returns to Queued after a failure and reaches Passed on its next attempt. The two Queued-to-Running intervals for this case are 20 and 5 minutes. Across both example runs, the median for that transition is 5 minutes.

## Real incident management

Amaral, Fantinato and Peres (2018), [Incident management process enriched event log](https://doi.org/10.24432/C57S4H), UCI Machine Learning Repository, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). UCI publishes an anonymized ServiceNow audit export with 141,712 records for 24,918 incidents. The prototype uses the incident ID, state, update timestamp and update counter. The original data stays external.

Download the [UCI archive](https://archive.ics.uci.edu/static/public/498/incident+management+process+enriched+event+log.zip) and extract it into a local folder. Replace the input path as needed.

```powershell
python reconstruct.py incident_event_log.csv --case-column number --stage-column incident_state --time-column sys_updated_at --time-format "%d/%m/%Y %H:%M" --order-column sys_mod_count --unknown-stage=-100 --inspect INC0000246
```

The run analyzed 24,916 incidents and excluded two with the unmapped state `-100`. There were 1,024 incidents with at least one return to a previous state. For the 4,657 direct Awaiting User Info → Resolved transitions, the median observed elapsed time was 4 days, 1 hour, 38 minutes. A separate SQLite window-function query reproduced this transition count and median. This is elapsed time between recorded state entries. The export does not establish when a user responded or how much time staff spent working.

Incident `INC0000246` illustrates the decision the report supports. It went New → Active → Awaiting User Info → Active → Resolved → Closed. The first wait-state observation and the return to Active were 48 hours, 15 minutes apart. Resolution was recorded six minutes later. Inspect CSV records 643, 645 and 647 to verify those boundaries. A support lead can now investigate the long interval with the ticket history.

The tested archive SHA-256 was `6294e29a311647306bfdfc85783f7df66517c197b9cd49aa5ee36ba9c525d1d6`.

## Real software review

The same analyzer processed 23 selected milestones from six public CPython pull requests, #1 through #6. In [CPython PR #2](https://github.com/python/cpython/pull/2), 1 hour, 49 minutes, 6 seconds elapsed from opening to the first formal review. The first recorded request for changes was followed by approval 8 minutes, 22 seconds later. Those are recorded milestones. They do not measure editing time. The six historical PRs test portability and are too small to estimate typical review latency.

To reproduce the sample, save the PR and review metadata from the [GitHub pull requests API](https://docs.github.com/en/rest/pulls/pulls) and [reviews API](https://docs.github.com/en/rest/pulls/reviews). This bounded sample had fewer than 100 reviews per PR.

```powershell
$base = 'https://api.github.com/repos/python/cpython'
$headers = @{ Accept = 'application/vnd.github+json'; 'User-Agent' = 'workflow-reconstruction-proof' }
$pulls = Invoke-RestMethod -Uri "$base/pulls?state=closed&per_page=6&sort=created&direction=asc" -Headers $headers
$sample = foreach ($pull in $pulls) {
    $reviews = Invoke-RestMethod -Uri "$base/pulls/$($pull.number)/reviews?per_page=100" -Headers $headers
    [pscustomobject]@{
        number = $pull.number; url = $pull.html_url; draft = $pull.draft
        created_at = $pull.created_at; merged_at = $pull.merged_at; closed_at = $pull.closed_at
        reviews = @($reviews | Select-Object id,state,submitted_at)
    }
}
ConvertTo-Json -InputObject @($sample) -Depth 5 | Set-Content -Encoding utf8 cpython.json
python github_reviews_to_csv.py cpython.json | Set-Content -Encoding utf8 cpython.csv
python reconstruct.py cpython.csv --inspect 2
```

The converter uses opening, the first submitted formal review, subsequent approvals and change requests, and merge or close. It excludes currently marked drafts and reviews posted after the terminal timestamp. Comments outside formal reviews, ready-for-review history and reopen history are outside this projection. The generated CSV includes review links in its `source` column.

## Use a different workflow

Map three columns from a CSV export: a stable case ID, stage or milestone name, and timestamp. The analyzer sorts within each case and collapses consecutive observations of the same stage. A return requires leaving a stage and later reaching it again. Repeating a stage can be expected, as with CI retries. Domain-specific meanings such as rework and waiting depend on the records and stage definitions. Use offset-bearing ISO timestamps where possible. A legacy format with no timezone measures elapsed wall-clock time. If different stages have equal timestamps, supply a reliable integer sequence or the analyzer will exclude the ambiguous case. Equal timestamps can still yield zero measured elapsed time at the source's precision.

Support for a tool comes from mapping its export to this input, or writing a small converter when needed. A snapshot of current statuses alone cannot show historical transitions. Analysis uses a single ordered timeline per case. Parallel branches or work spanning linked objects require explicit relationships beyond the CSV mapping. [OCEL 2.0](https://www.ocel-standard.org/) defines a format for such data.

## Contribute a workflow

Describe who uses it, what decision they need to make, and which records can answer it. Include a shareable anonymized or synthetic CSV, the column mapping, and one expected timeline and interval that a reviewer can reproduce. State what the export omits and attribute any external data. A new example can use the existing CSV input. Add a converter when the source cannot map directly. Keep private tickets, credentials, and customer data out of submissions.

## Existing tools

[DORA's value stream mapping guide](https://dora.dev/guides/value-stream-management/) describes measuring waits and handoffs in software delivery. [PM4Py](https://github.com/process-intelligence-solutions/pm4py) provides event-log process maps and performance analysis. This app focuses on tracing elapsed time from an existing CSV export to the original source lines.

## License

[MIT](LICENSE). Copyright 2026 Wadee Kharbat.
