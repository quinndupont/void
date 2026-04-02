# void: Lipogram Translation Benchmark

`void` is a reproducible benchmark for constrained literary translation.  
It tests whether language models can translate passages from Georges Perec's *La Disparition* into English while preserving a hard lipogram rule: **no letter `e` (upper- or lowercase) may appear in model output**.

The repository includes:
- a data pipeline for extraction, translation, scoring, and language-quality checks
- machine-readable benchmark outputs
- an interactive reader for paragraph-level inspection

- Repository: [https://github.com/quinndupont/void](https://github.com/quinndupont/void)
- Live site: [https://quinndupont.github.io/void/](https://quinndupont.github.io/void/)
- Source text scan: [https://archive.org/details/B-001-004-120](https://archive.org/details/B-001-004-120)

## Research Objective

The project evaluates a specific failure mode in modern LLMs: inability to jointly optimize **semantic translation quality** and a **strict symbolic constraint** over long-form generation.

The benchmark is intentionally difficult:
- literary prose with stylistic variation
- many paragraphs requiring lexical reformulation
- global character-level ban (`e`) that conflicts with normal English frequency

## Evaluation Protocol

### Core Metrics

- `total_e_count`: total number of forbidden characters in scored output (lower is better)
- `pass_rate`: share of scored paragraphs with zero forbidden characters (higher is better)
- `failures`: paragraphs detected as non-English (French included), used as a reliability penalty
- `failure_rate`: failures divided by total judged paragraphs

### Ranking Policy

Models are ranked with a strong reliability penalty:
1. lowest `failure_rate`
2. lowest `failures`
3. lowest `total_e_count`
4. highest `pass_rate`

This prevents systems from ranking highly by copying source text or otherwise bypassing the English-translation requirement.

## Current Results

Derived from `data/scores.json` and `site/data.json`.

| Rank | Model | Failures | Failure rate | Total `e` | Pass rate | E-free / total |
|---:|---|---:|---:|---:|---:|---:|
| 1 | gemini-2.5-pro | 0 | 0.00% | 713 | 9.49% | 15 / 158 |
| 2 | claude-opus | 0 | 0.00% | 902 | 3.16% | 5 / 158 |
| 3 | gpt-5.4 | 0 | 0.00% | 2795 | 0.63% | 1 / 158 |
| 4 | phi3-14b | 1 | 0.63% | 22785 | 4.43% | 7 / 158 |
| 5 | llama3.1-70b | 1 | 0.63% | 24155 | 1.27% | 2 / 158 |
| 6 | claude-sonnet | 2 | 1.26% | 4360 | 1.90% | 3 / 158 |
| 7 | mistral-large | 3 | 1.89% | 9541 | 0.00% | 0 / 158 |
| 8 | amazon-nova-pro | 6 | 3.77% | 498 | 13.92% | 22 / 158 |
| 9 | claude-haiku | 12 | 7.55% | 16119 | 7.59% | 12 / 158 |
| 10 | mistral-7b | 12 | 7.55% | 27254 | 1.90% | 3 / 158 |
| 11 | gemma2-9b | 15 | 9.55% | 24735 | 4.49% | 7 / 156 |
| 12 | llama3.1-8b | 47 | 29.56% | 19938 | 0.63% | 1 / 158 |
| 13 | qwen2.5-7b | 64 | 40.25% | 14316 | 18.35% | 29 / 158 |

## Repository Layout

- `scripts/` - end-to-end benchmark pipeline
- `data/translations/` - per-model translation outputs
- `data/language_eval/` - language-detection artifacts and summaries
- `data/scores.json` - aggregate ranking inputs
- `site/` - static benchmark reader and visualization
- `config.yaml` - model/provider configuration

## Reproducibility

### Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set provider credentials as needed:
- `OPENAI_API_KEY`
- `GEMINI_API_KEY` or `GOOGLE_API_KEY`

For AWS Bedrock models:

```bash
aws configure
```

### Pipeline

```bash
python scripts/01_fetch_pdf.py
python scripts/02_extract_text.py
python scripts/03_cleanup.py
python scripts/03b_tag_main_boundaries.py
python scripts/04_translate.py
python scripts/06_detect_language.py
python scripts/05_score.py
```

Quick smoke test:

```bash
python scripts/04_translate.py --test --test-limit 1
```

## Public Site

GitHub Pages deploys from `site/` using `.github/workflows/deploy-pages.yml`.

Site URL:
- [https://quinndupont.github.io/void/](https://quinndupont.github.io/void/)

The interface supports:
- model cards with ranking and failure diagnostics
- paragraph-level model switching
- failure viewer mode for targeted review of non-English outputs

## Limitations

- Constraint compliance (`e` count) is objective, but literary quality is not automatically scored.
- Language detection is probabilistic and may be unstable on very short snippets.
- Source OCR and paragraph segmentation can propagate boundary noise into downstream scoring.

## Rights and Responsible Use

This project is for research, criticism, and evaluation. *La Disparition* is copyrighted; downstream reuse should include clear rights notices and jurisdiction-appropriate handling of source excerpts.
