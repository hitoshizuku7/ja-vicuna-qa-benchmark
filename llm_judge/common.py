"""
Common data structures and utilities.
"""
import ast
import dataclasses
import glob
import json
import logging
import os
import re
import time
import openai
from dotenv import load_dotenv

from model_adapter import get_conversation_template

logger = logging.getLogger(__name__)

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")
openai.organization = os.getenv("OPENAI_ORGANIZATION")

# API setting constants
API_MAX_RETRY = 16
API_RETRY_SLEEP = 10
API_ERROR_OUTPUT = "$ERROR$"

TIE_DELTA = 0.1

# Categories that need reference answers
NEED_REF_CATS = ["math", "reasoning", "coding"]
# NEED_REF_CATS = []

# Extract scores from judgments
two_score_pattern = re.compile("\[\[(\d+\.?\d*),\s?(\d+\.?\d*)\]\]")
two_score_pattern_backup = re.compile("\[(\d+\.?\d*),\s?(\d+\.?\d*)\]")
one_score_pattern = re.compile("\[\[(\d+\.?\d*)\]\]")
one_score_pattern_another_format = re.compile("\[\[rating:(\d+)\]\]")
one_score_pattern_another_format2 = re.compile("\[\[rating: (\d+)\]\]")

reverse_model_map = {
    "model_1": "model_2",
    "model_2": "model_1",
}


@dataclasses.dataclass
class Judge:
    model_name: str
    prompt_template: dict
    ref_based: bool = False
    multi_turn: bool = False


@dataclasses.dataclass
class MatchSingle:
    question: dict
    model: str
    answer: dict
    judge: Judge
    ref_answer: dict = None
    multi_turn: bool = False


@dataclasses.dataclass
class MatchPair:
    question: dict
    model_1: str
    model_2: str
    answer_1: dict
    answer_2: dict
    judge: Judge
    ref_answer: dict = None
    multi_turn: bool = False


def load_questions(question_file: str) -> list[dict]:
    """Load questions from a file."""
    with open(question_file, "r") as fin:
        return [json.loads(line) for line in fin]


def load_model_answers(answer_dir: str):
    """Load model answers.

    The return value is a python dict of type:
    Dict[model_name: str -> Dict[question_id: int -> answer: dict]]
    """
    filenames = glob.glob(os.path.join(answer_dir, "*.jsonl"))
    model_answers = {}
    for filename in sorted(filenames):
        logger.debug(f"Loading model answers from {filename}")
        model_name, _ = os.path.splitext(os.path.basename(filename))
        answer = {}
        with open(filename, "r") as fin:
            for line in fin:
                line = json.loads(line)
                answer[line["question_id"]] = line
        model_answers[model_name] = answer
    return model_answers


def load_judge_prompts(prompt_file: str):
    """Load judge prompts.

    The return value is a python dict of type:
    Dict[judge_name: str -> dict]
    """
    prompts = {}
    with open(prompt_file) as fin:
        for line in fin:
            line = json.loads(line)
            prompts[line["name"]] = line
    return prompts


def run_judge_single(question, answer, judge, ref_answer, multi_turn=False):
    model = judge.model_name
    if model not in {"gpt-3.5-turbo", "gpt-4"}:
        raise ValueError(f"Invalid judge model name: {model}")

    if judge.prompt_template["output_format"] != "[[rating]]":
        raise ValueError(
            f"Invalid output format: {judge.prompt_template['output_format']}"
        )

    kwargs = {}
    if ref_answer is not None:
        kwargs["ref_answer_1"] = ref_answer["choices"][0]["turns"][0]

    if multi_turn:
        user_prompt = judge.prompt_template["prompt_template"].format(
            question_1=question["turns"][0],
            question_2=question["turns"][1],
            answer_1=answer["choices"][0]["turns"][0],
            answer_2=answer["choices"][0]["turns"][1],
            **kwargs,
        )
    else:
        user_prompt = judge.prompt_template["prompt_template"].format(
            question=question["turns"][0],
            answer=answer["choices"][0]["turns"][0],
            **kwargs,
        )

    system_prompt = judge.prompt_template["system_prompt"]
    conv = get_conversation_template(model)
    conv.system = system_prompt
    conv.append_message(conv.roles[0], user_prompt)
    conv.append_message(conv.roles[1], None)

    judgment = chat_compeletion_openai(model, conv, temperature=0, max_tokens=2048)

    match = (
        re.search(one_score_pattern, judgment)
        or re.search(one_score_pattern_another_format, judgment)
        or re.search(one_score_pattern_another_format2, judgment)
    )

    if match:
        rating = ast.literal_eval(match.groups()[0])
    else:
        rating = -1

    return rating, user_prompt, judgment


def play_a_match_single(match: MatchSingle, output_file: str):
    if match.judge.prompt_template["type"] != "single":
        raise ValueError(f"invalid judge type: {match.judge.prompt_template['type']}")

    question, model, answer, judge, ref_answer, multi_turn = (
        match.question,
        match.model,
        match.answer,
        match.judge,
        match.ref_answer,
        match.multi_turn,
    )

    score, user_prompt, judgment = run_judge_single(
        question, answer, judge, ref_answer, multi_turn=multi_turn
    )

    question_id = question["question_id"]
    turn = 1 if not multi_turn else 2
    result = {
        "question_id": question_id,
        "model": model,
        "judge": (judge.model_name, judge.prompt_template["name"]),
        "user_prompt": user_prompt,
        "judgment": judgment,
        "score": score,
        "turn": turn,
        "tstamp": time.time(),
    }
    logger.info(
        f"question: {question_id}, turn: {turn}, model: {model}, "
        f"score: {score}, "
        f"judge: {(judge.model_name, judge.prompt_template['name'])}"
    )

    if output_file:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "a") as fout:
            fout.write(json.dumps(result, ensure_ascii=False) + "\n")

    return result


def run_judge_pair(question, answer_a, answer_b, judge, ref_answer, multi_turn=False):
    model = judge.model_name
    if model not in {"gpt-3.5-turbo", "gpt-4"}:
        raise ValueError(f"Invalid judge model name: {model}")

    if judge.prompt_template["output_format"] not in {"[[A]]", "[[rating_a,rating_b]]"}:
        raise ValueError(
            f"Invalid output format: {judge.prompt_template['output_format']}"
        )

    kwargs = {}
    if ref_answer is not None:
        kwargs["ref_answer_1"] = ref_answer["choices"][0]["turns"][0]
        kwargs["ref_answer_2"] = ref_answer["choices"][0]["turns"][1]

    if multi_turn:
        system_prompt = judge.prompt_template["system_prompt"]
        user_prompt = judge.prompt_template["prompt_template"].format(
            question_1=question["turns"][0],
            question_2=question["turns"][1],
            answer_a_1=answer_a["choices"][0]["turns"][0],
            answer_b_1=answer_b["choices"][0]["turns"][0],
            answer_a_2=answer_a["choices"][0]["turns"][1],
            answer_b_2=answer_b["choices"][0]["turns"][1],
            **kwargs,
        )
    else:
        system_prompt = judge.prompt_template["system_prompt"]
        user_prompt = judge.prompt_template["prompt_template"].format(
            question=question["turns"][0],
            answer_a=answer_a["choices"][0]["turns"][0],
            answer_b=answer_b["choices"][0]["turns"][0],
            **kwargs,
        )

    conv = get_conversation_template(model)
    conv.append_message(conv.roles[0], user_prompt)
    conv.append_message(conv.roles[1], None)

    conv.system = system_prompt
    judgment = chat_compeletion_openai(model, conv, temperature=0, max_tokens=2048)

    if judge.prompt_template["output_format"] == "[[A]]":
        if "[[A]]" in judgment:
            winner = "A"
        elif "[[B]]" in judgment:
            winner = "B"
        elif "[[C]]" in judgment:
            winner = "tie"
        else:
            winner = "error"
    else:  # judge.prompt_template["output_format"] == "[[rating_a,rating_b]]"
        match = re.search(two_score_pattern, judgment)
        if not match:
            match = re.search(two_score_pattern_backup, judgment)
        if match:
            scores = [ast.literal_eval(s.strip()) for s in match.groups()]
            if abs(scores[0] - scores[1]) <= TIE_DELTA:
                winner = "tie"
            elif scores[0] > scores[1]:
                winner = "A"
            else:
                winner = "B"
        else:
            winner = "error"

    return winner, user_prompt, judgment


def play_a_match_pair(match: MatchPair, output_file: str):
    if match.judge.prompt_template["type"] not in {"pairwise", "single"}:
        raise ValueError(f"invalid judge type: {match.judge.prompt_template['type']}")

    question, model_1, model_2, answer_1, answer_2, judge, ref_answer, multi_turn = (
        match.question,
        match.model_1,
        match.model_2,
        match.answer_1,
        match.answer_2,
        match.judge,
        match.ref_answer,
        match.multi_turn,
    )

    if judge.prompt_template["type"] == "pairwise":
        g1_winner, g1_user_prompt, g1_judgment = run_judge_pair(
            question, answer_1, answer_2, judge, ref_answer, multi_turn=multi_turn
        )
        g2_winner, g2_user_prompt, g2_judgment = run_judge_pair(
            question, answer_2, answer_1, judge, ref_answer, multi_turn=multi_turn
        )

        g1_map = {"A": "model_1", "B": "model_2"}
        g2_map = {"A": "model_2", "B": "model_1"}
        g1_winner = g1_map.get(g1_winner, g1_winner)
        g2_winner = g2_map.get(g2_winner, g2_winner)
        question_id = question["question_id"]
        turn = 1 if not multi_turn else 2

        result = {
            "question_id": question_id,
            "model_1": model_1,
            "model_2": model_2,
            "g1_winner": g1_winner,
            "g2_winner": g2_winner,
            "judge": (judge.model_name, judge.prompt_template["name"]),
            "g1_user_prompt": g1_user_prompt,
            "g1_judgment": g1_judgment,
            "g2_user_prompt": g2_user_prompt,
            "g2_judgment": g2_judgment,
            "turn": turn,
            "tstamp": time.time(),
        }

        logger.info(
            f"question: {question_id}, turn: {turn}, model_1: {model_1}, model_2: {model_2}, "
            f"g1_winner: {g1_winner}, g2_winner: {g2_winner}, "
            f"judge: {(judge.model_name, judge.prompt_template['name'])}"
        )
    else:  # judge.prompt_template["type"] == "single"
        m1_score, m1_user_prompt, m1_judgment = run_judge_single(
            question, answer_1, judge, ref_answer
        )
        m2_score, m2_user_prompt, m2_judgment = run_judge_single(
            question, answer_2, judge, ref_answer
        )

        if abs(m1_score - m2_score) <= TIE_DELTA:
            winner = "tie"
        elif m1_score > m2_score:
            winner = "model_1"
        else:
            winner = "model_2"

        question_id = question["question_id"]
        result = {
            "question_id": question_id,
            "model_1": model_1,
            "model_2": model_2,
            "g1_winner": winner,
            "g2_winner": winner,
            "judge": (judge.model_name, judge.prompt_template["name"]),
            "g1_user_prompt": m1_user_prompt,
            "g1_judgment": m1_judgment,
            "g2_user_prompt": m2_user_prompt,
            "g2_judgment": m2_judgment,
            "m1_score": m1_score,
            "m2_score": m2_score,
            "tstamp": time.time(),
        }
        logger.info(
            f"question: {question_id}, model_1: {model_1}, model_2: {model_2}, "
            f"winner: {winner}, m1_score: {m1_score}, m2_score: {m2_score}, "
            f"judge: {(judge.model_name, judge.prompt_template['name'])}"
        )

    if output_file:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "a") as fout:
            fout.write(json.dumps(result, ensure_ascii=False) + "\n")

    return result


def chat_compeletion_openai(model, conv, temperature, max_tokens):
    output = API_ERROR_OUTPUT
    for _ in range(API_MAX_RETRY):
        try:
            messages = conv.to_openai_api_messages()
            response = openai.ChatCompletion.create(
                model=model,
                messages=messages,
                n=1,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            output = response["choices"][0]["message"]["content"]
            break
        except openai.error.OpenAIError as e:
            logger.warning(e)
            time.sleep(API_RETRY_SLEEP)

    return output


def normalize_game_key_single(gamekey, result):
    """Make the model names sorted in a game key."""
    qid, model_1, model_2 = gamekey
    if model_1 < model_2:
        return gamekey, result
    else:
        new_gamekey = (qid, model_2, model_1)
        new_result = {
            "winners": tuple(reverse_model_map.get(x, x) for x in result["winners"]),
            "g1_judgment": result["g2_judgment"],
            "g2_judgment": result["g1_judgment"],
        }
        return new_gamekey, new_result


def normalize_game_key_dict(judgment_dict):
    """Make the model names sorted in the game keys."""
    ret = {}
    for key, value in judgment_dict.items():
        new_key, new_value = normalize_game_key_single(key, value)
        ret[new_key] = new_value
    return ret


def load_pairwise_model_judgments(filename: str):
    """Load model judgments.

    The return value is a dict of type:
    Dict[judge: Tuple -> Dict[game_key: tuple -> game_result: dict]
    """
    judge_dict = {}

    for line in open(filename):
        obj = json.loads(line)
        judge = tuple(obj["judge"])
        qid, model_1, model_2 = obj["question_id"], obj["model_1"], obj["model_2"]

        if judge not in judge_dict:
            judge_dict[judge] = {}

        if "winner" in obj:
            winner = obj["winner"]
        elif "g1_winner" in obj and "g2_winner" in obj:
            g1_winner, g2_winner = obj["g1_winner"], obj["g2_winner"]
            if g1_winner == g2_winner:
                winner = g1_winner
            else:
                winner = "inconsistent"
        else:
            raise ValueError(f"Invalid keys: {list(obj.keys())}")

        gamekey = (qid, model_1, model_2)
        winners = (winner,)

        judge_dict[judge][gamekey] = {
            "winners": winners,
            "g1_judgment": obj["g1_judgment"],
            "g2_judgment": obj["g2_judgment"],
        }

    # Make the model names sorted in the game keys
    normalized = {}
    for judge, value in judge_dict.items():
        normalized[judge] = normalize_game_key_dict(value)
    return normalized


def load_single_model_judgments(filename: str):
    """Load model judgments.

    The return value is a dict of type:
    Dict[judge: Tuple -> Dict[game_key: tuple -> game_result: dict]
    """
    judge_dict = {}

    for line in open(filename):
        obj = json.loads(line)
        judge = tuple(obj["judge"])
        qid, model = obj["question_id"], obj["model"]

        if judge not in judge_dict:
            judge_dict[judge] = {}

        gamekey = (qid, model)

        judge_dict[judge][gamekey] = {
            "score": obj["score"],
            "judgment": obj["judgment"],
        }
    return judge_dict


def resolve_pairwise_judgment_dict(
    question, model_judgments_normal, model_judgments_math, multi_turn=False
):
    """Return the correct pairwise judge."""
    if multi_turn:
        if question["category"] in NEED_REF_CATS:
            return model_judgments_math[("gpt-4", "pair-math-v1-multi-turn")]
        return model_judgments_normal[("gpt-4", "pair-v2-multi-turn")]

    if question["category"] in NEED_REF_CATS:
        return model_judgments_math[("gpt-4", "pair-math-v1")]
    else:
        return model_judgments_normal[("gpt-4", "pair-v2")]


def resolve_single_judgment_dict(
    question, model_judgments_normal, model_judgments_math, multi_turn=False
):
    """Return the correct single answer grading judge."""
    if multi_turn:
        if question["category"] in NEED_REF_CATS:
            return model_judgments_math[("gpt-4", "single-math-v1-multi-turn")]
        return model_judgments_normal[("gpt-4", "single-v1-multi-turn")]

    if question["category"] in NEED_REF_CATS:
        return model_judgments_math[("gpt-4", "single-math-v1")]
    else:
        return model_judgments_normal[("gpt-4", "single-v1")]


def get_pairwise_judge_explanation(gamekey, judgment_dict):
    """Get model judge explanation."""
    try:
        qid, model_1, model_2 = gamekey
        if model_1 < model_2:
            res = judgment_dict[gamekey]
            g1_judgment, g2_judgment = res["g1_judgment"], res["g2_judgment"]
        else:
            new_gamekey = (qid, model_2, model_1)
            res = judgment_dict[new_gamekey]

            model_1, model_2 = model_1, model_2
            g1_judgment, g2_judgment = res["g2_judgment"], res["g1_judgment"]

        return (
            f"**Game 1**. **A**: {model_1}, **B**: {model_2}\n\n"
            f"**Judgment**: {g1_judgment}"
            + "\n\n`--------------------------`\n\n"
            + f"**Game 2**. **A**: {model_2}, **B**: {model_1}\n\n"
            f"**Judgment**: {g2_judgment}"
        )
    except KeyError:
        return "N/A"


def get_single_judge_explanation(gamekey, judgment_dict):
    """Get model judge explanation."""
    try:
        qid, model = gamekey

        res = judgment_dict[gamekey]

        g1_judgment = res["judgment"]
        g1_score = res["score"]

        return (
            f"**Game 1**. **A**: {model}, **Score**: {g1_score}\n\n"
            f"**Judgment**: {g1_judgment}"
        )
    except KeyError:
        return "N/A"


def check_data(questions, model_answers, ref_answers, models, judges):
    # check model answers
    for m in models:
        assert m in model_answers, f"Missing model answer for {m}"
        m_answer = model_answers[m]
        for q in questions:
            assert (
                q["question_id"] in m_answer
            ), f"Missing model {m}'s answer to Question {q['question_id']}"
    # check ref answers
    for jg in judges.values():
        if not jg.ref_based:
            continue
        for q in questions:
            if q["category"] not in NEED_REF_CATS:
                continue
            assert (
                int(q["question_id"]) in ref_answers[jg.model_name]
            ), f"Missing reference answer to Question {q['question_id']} for judge {jg.model_name}"


def get_model_list(answer_dir):
    file_paths = glob.glob(f"{answer_dir}/*.jsonl")
    file_names = [os.path.splitext(os.path.basename(f))[0] for f in file_paths]
    return file_names
