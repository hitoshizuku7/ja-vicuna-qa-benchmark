# Japanese Vicuna QA Benchmark

We released Japanese Vicuna QA Benchmark for measuring comprehensive capabilities of Japanese LLMs, which consists of 80 diverse questions in 10 categories (generic, coding, roleplay, writing, etc.)
You can leverage this package to evaluate the answers of your Japanese LLM models in a reference-free manner with LLM-as-a-judge.
To automate the evaluation process, we prompt strong LLMs like GPT-4 to act as judges and assess the quality of the models' responses.

To be clarified, such zero-shot QA-style evaluation might be more suitable for those LLMs that have been fine-tuned with instructions. The 80 questions are manually translated from the English Vicuna benchmark.

## Contents
- [Install](#install)
- [Evaluate a model with Japanese Vicuna QA Benchmark](#evaluate-a-model-with-japanese-vicuna-qa-benchmark)
- [Sample Outputs](#sample-outputs)
- [An Example of pairwise win-rate of three Japanese LLMs](#pairwise-win-rate-of-three-japanese-llms)
- [Supported baseline Models](#supported-baseline-models)

## Install
```
git clone https://github.com/hitoshizuku7/LLM_Judge_ku.git
cd LLM_Judge_ku
pip install -e .
```

## Evaluate a model with Japanese Vicuna QA Benchmark

#### Step 1. Generate model answers to Japanese Vicuna QA questions (noted as jp-bench).

```
python llm_judge/gen_model_answer.py --config <CONFIG-PATH>
```

Arguments & Options:
  - `<CONFIG-PATH>` is the path to a configuration file. Examples are in `configs/`.

For example:

```
python gen_model_answer.py --config configs/rinna--japanese-gpt-neox-3.6b-instruction-ppo.json
```

The answers will be saved to `data/jp_bench/model_answer`.

#### Step 2. Generate GPT-4 judgments

There are several options to use GPT-4 as a judge, such as pairwise win-rate and single-answer grading.
We show an example of the pairwise win-rate evaluation of instruction fine-tuned models (rinna-3.6b-sft-v2, rinna-3.6b-ppo, and japanese-alpaca-lora-7b) at the bottom.

```
OPENAI_API_KEY=<YOUR-KEY> python gen_judgment.py \
    --mode {single|pairwise-baseline|pairwise-all} \
    [--model-list <LIST-OF-MODEL-IDS>]
```

Arguments & Options:
- `--mode {single|pairwise-baseline|pairwise-all}` is the mode of judgment.
    - `single`: run score-based single-model grading.
    - `pairwise-baseline`: run pairwise comparison against a baseline model.
    - `pairwise-all`: run pairwise comparison between all model pairs.
- `--model-list <LIST-OF-MODEL-IDS>` is a list of model IDs to be evaluated. If not specified, all models in `data/jp_bench/model_answer` will be evaluated.

For example:

```
OPENAI_API_KEY=<YOUR-KEY> python gen_judgment.py \
    --mode pairwise-all \
    --model-list rinna-3.6b-sft-v2 rinna-3.6b-ppo japanese-alpaca-lora-7b
```

The judgments will be saved to `data/jp_bench/model_judgment/gpt-4_pair.jsonl`

#### Step 3. Show jp-bench scores

Show the scores for selected models.

```
python show_result.py \
    --mode pairwise-all \
    --model-list rinna-3.6b-sft-v2 rinna-3.6b-ppo japanese-alpaca-lora-7b
```

---

#### Pairwise comparison against a baseline (default: gpt-3.5-turbo)

The `pairwise-baseline` mode runs pairwise comparison against a baseline model.

Generate GPT-4 judgments:

```
OPENAI_API_KEY=<YOUR-KEY> python gen_judgment.py \
  --mode pairwise-baseline \
  [--model-list <LIST-OF-MODEL-IDS>] \
  [--baseline-model <name-of-baseline-model>]
```

The judgments will be saved to `data/jp_bench/model_judgment/gpt-4_pair.jsonl`

Show results:

```
python show_result.py \
  --bench-name "jp_bench" \
  --mode pairwise-baseline \
  [--model-list <LIST-OF-MODEL-IDS>]
```

#### Run GPT-4 judge with the single model

The `single` mode grades models by asking GPT-4 to grade and give a score to model's answer directly without pairwise comparison.

Generate GPT-4 judgments:

```
OPENAI_API_KEY=<YOUR-KEY> python gen_judgment.py \
  --mode single \
  [--model-list <LIST-OF-MODEL-IDS>]
```

The judgments will be saved to `data/jp_bench/model_judgment/gpt-4_single.jsonl`

Show results:

```
python show_result.py \
  --bench-name "jp_bench" \
  --mode single \
  [--model-list <LIST-OF-MODEL-IDS>]
```

## Sample Outputs

#### Question:
> 植物性タンパク源と動物性タンパク源の違いは何ですか？
#### Answer of rinna-3.6b:
> 栄養素の含有量に大きな違いがあります。
#### Answer of rinna-3.6b-sft-v2:
> 植物性タンパク源は肉や魚など、いくつかの種類の食品を指します。一方、動物性タンパク源には卵、乳製品、大豆、ナッツ、種などが含まれます。
#### Answer of rinna-3.6b-ppo:
> 植物性タンパク源とは、主に大豆や豆腐などの大豆製品を生産する植物によって作られるタンパク質で、卵、牛乳、肉などの動物性タンパク源よりも栄養価が高く、低カロリーです。一方、動物性タンパク源には、牛肉、豚肉、鶏肉などが含まれます。
#### Answer of japanese-alpaca-lora-7b:
> 動物タンポク源（ATP）は、動物によって生産されるエネルギー源である。ATPは、細胞におけるATP認識システムの活性化により生成されています。動物のATP源は、遺伝的に組み込まれたATP生成機構であり、これは、ATPを生成するために使用され、経験的にATPの量を増加させることができる。

[//]: # (## Comparison )

[//]: # (![Comparison]&#40;./comparison.png&#41;  )

## Pairwise win-rate of three Japanese LLMs
| Model                   | win | loss | tie |  win_rate | loss_rate | win_rate_adjusted |
|:------------------------|----:|-----:|----:|----------:|----------:|------------------:|
| rinna-3.6b-ppo          |  87 |   25 |  52 |  0.530488 |  0.152439 |          0.689024 |
| rinna-3.6b-sft-v2       |  70 |   35 |  58 |  0.429448 |  0.214724 |          0.607362 |
| japanese-alpaca-lora-7b |  15 |  112 |  38 |  0.090909 |  0.678788 |          0.206061 |

The GPT4 judgments is placed in `data/jp_bench/model_judgment/gpt-4_pair.jsonl`.

To be noticed, `pairwise-all` might become very inefficient when evaluating more LLMs, as it evaluates combinations of each two of them. In such cases, we recommend using the `pairwise-baseline` mode, allowing all models to be compared against a fixed baseline such as ChatGPT.

## Supported baseline Models
To make it more convenient for users to utilize pairwise comparisons with existing Japanese LLMs, we offer the prediction of the following four baselines in `fastchat/llm_judge/data/jp_bench/model_answer`.

- [Rinna-3.6B](https://huggingface.co/rinna/japanese-gpt-neox-3.6b)
- [Rinna-3.6B-sft-v2](https://huggingface.co/rinna/japanese-gpt-neox-3.6b-instruction-sft-v2)
- [Rinna-3.6B-ppo](https://huggingface.co/rinna/japanese-gpt-neox-3.6b-instruction-ppo)
- [Japanese-Alpaca-Lora](https://huggingface.co/kunishou)

We will regularly include latest LLM baselines.

## Questions
If you have any questions and feedback, please feel free to leave questions in the `Issues' list.
