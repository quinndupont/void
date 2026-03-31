# void — La Disparition AI Translation Benchmark

Benchmark: translate Georges Perec’s *La Disparition* (lipogram: no letter “e”) into English under the same constraint. Hard metric: count of `e`/`E` in model output.

**Source:** [archive.org/details/B-001-004-120](https://archive.org/details/B-001-004-120)

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) (for local models)
- [AWS CLI](https://aws.amazon.com/cli/) v2 with Bedrock access (`aws bedrock list-foundation-models` works in your region)
- Optional: Tesseract + `fra` language data if the PDF is image-only

## Setup

```bash
cd /Users/quinn/dev/void   # this project root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure AWS (Bedrock invocations use the **AWS CLI**, not boto3):

```bash
aws configure
# Ensure your IAM user/role can bedrock:InvokeModel on the model ARNs you use
```

Verify Bedrock models in `config.yaml` match your region:

```bash
aws bedrock list-foundation-models --region us-east-1 --query 'modelSummaries[?contains(modelId, `claude`)].modelId' --output text
```

## Pipeline

1. `python scripts/01_fetch_pdf.py` — download PDF to `data/raw/la_disparition.pdf`
2. `python scripts/02_extract_text.py` — PDF → `data/pages/page_NNN.txt`
3. `python scripts/03_cleanup.py` — `data/french_clean.json` (+ `e_errors_review.json` if needed)
4. `python scripts/03b_tag_main_boundaries.py` — tag `pre_text` + `main_start`/`main_end` in `data/french_clean.json`
5. `python scripts/04_translate.py` — per-model JSON under `data/translations/` (checkpointed)
6. `python scripts/05_score.py` — `data/scores.json` and `site/data.json`
7. Open `site/index.html` (or serve `site/` statically)

`04_translate.py` now defaults to `translate.scope: main_only` and excludes pre-text boundaries (`p0001`, `p0156`, `p0157`) unless tags in `data/french_clean.json` explicitly set `main_start`/`main_end`. To translate everything, set `translate.scope: all` in `config.yaml`.
For a quick smoke test run, use `python scripts/04_translate.py --test` (or `--test --test-limit 1`) to translate only a small number of pending paragraphs per model.

Start small: trim to a few pages/models before a full run (see plan notes in the repo history or project brief).

## Copyright / ethics

French text is Perec’s *La Disparition* (Denoël, 1969). This repo is for research and criticism. A public deployment may warrant excerpting chapters and a clear rights notice. Gilbert Adair’s *A Void* is the canonical human lipogram translation but is **not** included here (copyright).

## Git

```bash
git init
git add .
git commit -m "Initial void benchmark scaffold"
```
