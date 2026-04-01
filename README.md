# void: Lipogram Translation Benchmark

`void` evaluates whether contemporary language models can produce English translations of Georges Perec's *La Disparition* while obeying a strict lipogram constraint: **no letter `e` or `E` may appear in output text**.

The project includes a reproducible scoring pipeline and a public browser interface for paragraph-level comparison across models.

- Repository: [github.com/quinndupont/void](https://github.com/quinndupont/void)
- Live benchmark viewer (GitHub Pages): [quinndupont.github.io/void](https://quinndupont.github.io/void/)
- Source text: [archive.org/details/B-001-004-120](https://archive.org/details/B-001-004-120)

## Benchmark Method

- **Task:** Translate French paragraphs into English under a hard lipogram constraint.
- **Primary metric:** `total_e_count` (lower is better).
- **Secondary metric:** `pass_rate` = proportion of paragraphs with zero `e` characters.
- **Unit of analysis:** paragraph-level outputs in `data/translations/*.json`.

## Current Results (from `data/scores.json`)

Ranking is ordered by the primary metric (`total_e_count`, ascending).

| Rank | Model | Total `e` count | Pass rate | E-free paragraphs | Total paragraphs |
|---:|---|---:|---:|---:|---:|
| 1 | amazon-nova-pro | 498 | 13.92% | 22 | 158 |
| 2 | gemini-2.5-pro | 713 | 8.92% | 14 | 157 |
| 3 | claude-opus | 902 | 3.16% | 5 | 158 |
| 4 | gpt-5.4 | 2785 | 0.64% | 1 | 157 |
| 5 | claude-sonnet | 4360 | 1.90% | 3 | 158 |
| 6 | mistral-large | 9541 | 0.00% | 0 | 158 |
| 7 | qwen2.5-7b | 14316 | 18.35% | 29 | 158 |
| 8 | claude-haiku | 16119 | 7.59% | 12 | 158 |
| 9 | llama3.1-8b | 19938 | 0.63% | 1 | 158 |
| 10 | phi3-14b | 22785 | 4.43% | 7 | 158 |
| 11 | llama3.1-70b | 24155 | 1.27% | 2 | 158 |
| 12 | gemma2-9b | 24735 | 4.49% | 7 | 156 |
| 13 | mistral-7b | 27254 | 1.90% | 3 | 158 |

## Reproducible Setup

### 1) Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set credentials in `.env` as needed:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)

For Bedrock-backed models, configure AWS CLI credentials:

```bash
aws configure
```

### 2) Run Pipeline

```bash
python scripts/01_fetch_pdf.py
python scripts/02_extract_text.py
python scripts/03_cleanup.py
python scripts/03b_tag_main_boundaries.py
python scripts/04_translate.py
python scripts/05_score.py
python scripts/06_detect_language.py
```

For a smoke test:

```bash
python scripts/04_translate.py --test --test-limit 1
```

## GitHub Pages Deployment

This repository includes `.github/workflows/deploy-pages.yml`, which deploys the `site/` directory to GitHub Pages on every push to `main`.

To enable Pages:

1. Open repository **Settings → Pages**
2. Ensure **Build and deployment** is set to **GitHub Actions**
3. Push to `main` and wait for the workflow to complete

Your site will publish at:

- [https://quinndupont.github.io/void/](https://quinndupont.github.io/void/)

## Research and Rights Notice

This benchmark is intended for research, criticism, and model evaluation. *La Disparition* is a copyrighted literary work; use source excerpts and outputs responsibly, and include appropriate rights notices in downstream publications.
