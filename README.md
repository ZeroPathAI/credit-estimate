# credit-estimate

Estimate the cost of an initial ZeroPath full scan for a repository. Runs locally; nothing is uploaded.

## Run it

```bash
python3 zeropath_scan_cost_estimator.py /path/to/your/repo
```

Requires Python 3.9+ (already installed on macOS and most Linux).

## Options

```bash
# Only specific sub-projects
python3 zeropath_scan_cost_estimator.py . --include services/api --include packages/core

# Specific file types
python3 zeropath_scan_cost_estimator.py . --extensions py,ts,go

# JSON output
python3 zeropath_scan_cost_estimator.py . --json
```

Run with `--help` for all options.
