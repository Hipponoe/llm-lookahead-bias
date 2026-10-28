# Server project snapshot

Source: `/home/admin` on `14.103.25.113`.

This directory contains the project's Python scripts, dependency list, and the three CSV files that fit the repository's individual-file limit. The repository already contains the project's research notes and papers, so this snapshot is kept under `server-files/` to avoid replacing them.

## Credentials

Hard-coded `OPENAI_API_KEY` values were removed from `news_analyzer.py`, `news_collector.py`, and `test.py` in this snapshot. Set the `OPENAI_API_KEY` environment variable before running those scripts.

## Files saved separately

The 207 MB `news_database.csv` and 181 MB `cron.log` exceed GitHub's 100 MB per-file limit. Runtime output `nohup.out` is also saved locally. These files are stored in the user's requested OneDrive folder under `server-14.103.25.113/`.
