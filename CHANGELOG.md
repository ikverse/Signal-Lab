# Changelog

Every release has a section here. The release workflow publishes the section for its version
as the GitHub release notes, and the phone shows them before you install.

## 0.2.0

First version that runs on the phone.

- Live engine: checks every closed 1h, 4h and daily candle, opens a paper trade for each new
  signal and closes it at its target, stop or time limit.
- Price watch every 3 minutes for sudden moves.
- Phone notifications and spoken alerts (daily and 4h signals by default; 1h is logged only).
- The landscape app: chart, scorecard, Learn pages, alerts and settings.
- Updates itself from GitHub releases: download, self-test, install, roll back.
- Coins are picked by 30-day average volume, coins younger than 180 days are left out, and
  stablecoins are recognised by their price rather than their name.
- New variant `fade1h_hold24_1h`, judged on live paper trades only.

## 0.1.0

Phase 1 on the PC: engine, scorecard, backtest since 2019, repaint check and signal docs.
