# T Release Sync

This repo scrapes the T release calendar with Playwright and sends normalized rows to a webhook that updates the  release schedule sheet.

## Files

- `TRCS.py`
- `requirements.txt`
- `.github/workflows/TRS.yml`

## Required GitHub Secrets

- `TOPPS_SYNC_WEBHOOK_URL`
- `TOPPS_SYNC_WEBHOOK_TOKEN`

## Local run

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
TOPPS_SYNC_DRY_RUN=true python3 TRCS.py
```

## Workflow behavior

- Runs on schedule
- Scrapes `https://www.topps.com/release-calendar`
- Parses release rows
- Posts them to your release schedule webhook
