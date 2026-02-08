"""AI 出题：分析材料、流式生成题目。使用与 llm_service 相同的 OpenAI 兼容客户端（阿里云百炼）。"""
import json
import logging
import re
import uuid
from typing import Any, Iterator

from app.services.llm_service import get_openai_client

logger = logging.getLogger(__name__)


def _normalize_usage(raw: Any) -> dict[str, int] | None:
    """将 OpenAI/百炼返回的 usage 转为统一格式：inputTokens, outputTokens, totalTokens。"""
    if raw is None:
        return None
    inp = getattr(raw, "input_tokens", None) or getattr(raw, "prompt_tokens", None)
    out = getattr(raw, "output_tokens", None) or getattr(raw, "completion_tokens", None)
    total = getattr(raw, "total_tokens", None)
    if inp is None and out is None and total is None:
        return None
    if total is None and (inp is not None or out is not None):
        try:
            total = (inp or 0) + (out or 0)
        except Exception:
            total = None
    return {
        "inputTokens": int(inp) if inp is not None else 0,
        "outputTokens": int(out) if out is not None else 0,
        "totalTokens": int(total) if total is not None else 0,
    }


QUESTION_TYPE_LABELS = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "judgment": "判断题",
    "fill_blank": "填空题",
    "short_answer": "简答题",
}
DIFFICULTY_LABELS = {"easy": "简单", "medium": "中等", "hard": "困难"}


def analyze_material(
    content: str,
    question_type: str,
    difficulty: str,
    count: int,
) -> tuple[list[str], dict[str, int] | None]:
    """
    分析材料，结合题型、难度、数量提炼出题要点。
    返回 (keyPoints 列表, usage 或 None)。usage 为 { inputTokens, outputTokens, totalTokens }。
    """
    if not (content or "").strip():
        return [], None

    type_cn = QUESTION_TYPE_LABELS.get(question_type, question_type)
    diff_cn = DIFFICULTY_LABELS.get(difficulty, difficulty)
    prompt = f"""请根据以下【材料】，针对【{type_cn}】【{diff_cn}】难度、计划出【{count}】道题，提炼出适合出题的知识要点。
只返回一个 JSON 数组，不要其他文字。例如：["要点1", "要点2", "要点3"]

材料：
"""
    prompt += (content.strip() or "")[:6000]

    client = get_openai_client()
    completion = client.chat.completions.create(
        model="MiniMax-M2.1",
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": True},
    )
    usage = _normalize_usage(getattr(completion, "usage", None))
    raw = (completion.choices[0].message.content or "").strip()
    raw = _strip_markdown_code(raw)
    try:
        arr = json.loads(raw)
        if isinstance(arr, list):
            return [str(x) for x in arr if x], usage
        return [], usage
    except json.JSONDecodeError:
        return [], usage


def _strip_markdown_code(text: str) -> str:
    if not text:
        return text
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            return "\n".join(lines[1:-1])
        return "\n".join(lines[1:])
    return text


_answer_re = re.compile(r"^\s*答案[：:]\s*(.+)$", re.IGNORECASE)


def _parse_questions_text(full_content: str) -> list[dict[str, Any]]:
    """
    从流式输出文本解析题目块。
    格式：题目之间空行分隔；题干行以题号开头；选项行 A. / B. / C. / D.；可选一行「答案：X」。
    返回 [{"stem": "题干", "options": [...], "correct": "A"}, ...]。
    """
    text = full_content.strip()
    # 去掉末尾可能被模型误输出的 exerciseId 行
    if text and "exerciseId" in text:
        lines = text.split("\n")
        while lines and lines[-1].strip().startswith("{") and "exerciseId" in lines[-1]:
            lines.pop()
        text = "\n".join(lines).strip()
    blocks_raw = re.split(r"\n\s*\n", text)
    items: list[dict[str, Any]] = []
    stem_re = re.compile(r"^\s*(?:#*\s*)?【?\d+】?\s*[.、．：:]\s*.+")
    opt_re = re.compile(r"^\s*[A-D][.、．]\s*.+", re.IGNORECASE)
    for block in blocks_raw:
        block = block.strip()
        if not block:
            continue
        stem = None
        options: list[str] = []
        correct = ""
        for line in block.split("\n"):
            line = line.rstrip()
            if not line:
                continue
            m = _answer_re.match(line)
            if m:
                correct = m.group(1).strip()
                continue
            if stem_re.match(line) or (not stem and re.match(r"^\s*【?\d+】?\s*.+", line)):
                if stem is not None:
                    break
                stem = line.strip()
            elif opt_re.match(line):
                options.append(line.strip())
        if stem:
            items.append({"stem": stem, "options": options, "correct": correct})
    return items


def stream_raw_and_collect(
    content: str,
    question_type: str,
    difficulty: str,
    count: int,
    rag_context: str | None = None,
) -> Iterator[str | dict[str, Any]]:
    """
    流式调用模型生成题目内容，逐个 yield 文本片段（仅 content，不含 reasoning）；
    结束时若拿到 usage 会 yield 一个 {"_usage": { inputTokens, outputTokens, totalTokens }}，调用方勿当正文下发。
    若传入 rag_context，会在 prompt 中先加入「知识库参考」再拼用户材料。
    调用方需收集完整响应后解析并落库。
    """
    prompt = _build_questions_prompt(content, question_type, difficulty, count, rag_context=rag_context)
    logger.info(
        "[第二次调大模型-完整提示词]\n%s\n%s\n%s",
        "=" * 60,
        prompt,
        "=" * 60,
    )
    client = get_openai_client()
    completion = client.chat.completions.create(
        model="MiniMax-M2.1",
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": True},
        stream=True,
        stream_options={"include_usage": True},
    )
    is_answering = False
    last_usage = None
    for chunk in completion:
        if getattr(chunk, "usage", None) is not None:
            last_usage = _normalize_usage(chunk.usage)
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            if not is_answering:
                is_answering = False  # 思考阶段不输出到题目流
            continue
        if hasattr(delta, "content") and delta.content:
            if not is_answering:
                is_answering = True
            yield delta.content
    if last_usage is not None:
        yield {"_usage": last_usage}


def _build_questions_prompt(
    content: str,
    question_type: str,
    difficulty: str,
    count: int,
    rag_context: str | None = None,
) -> str:
    type_cn = QUESTION_TYPE_LABELS.get(question_type, question_type)
    diff_cn = DIFFICULTY_LABELS.get(difficulty, difficulty)
    prompt = f"""请根据以下材料，生成 {count} 道{type_cn}（难度：{diff_cn}）。只输出题目正文，不要输出任何 JSON，不要输出 exerciseId。

【格式要求】
1. 题目之间用空行分隔（每道题之间至少一个空行）。
2. 题干行必须以题号开头，题号与题干之间必须有空格。例如：1. 题干内容  或  1、题干内容 或  【1】题干内容。
3. 单选题/多选题：题干下方每行一个选项，选项标记必须用大写字母 A、B、C、D，格式为 "A. 选项内容" 或 "A、选项内容"（只使用 A-D）。
4. 填空题/简答题：只有题干行，不要选项行。
5. 每道题在题干和选项之后，另起一行输出「答案：X」。单选题/多选题 X 为选项字母（如 A）；填空/简答 X 为正确答案文本。不需要输出解析。
6. 不要输出任何 JSON，不要输出 {{"exerciseId"}} 等。

【示例】
1. 以下哪项是 Python 的特点？
A. 解释型语言
B. 编译型语言
C. 汇编语言
D. 机器语言
答案：A

2. 请写出 Python 中用于创建空列表的语法：______
答案：[]

3. 请简述 Python 中 list 和 tuple 的区别。
答案：list 可变，tuple 不可变；list 用 []，tuple 用 ()。

"""
    if rag_context and (rag_context := rag_context.strip()):
        prompt += "【知识库参考】\n" + rag_context[:4000] + "\n\n【用户材料】\n"
    else:
        prompt += "材料：\n"
    prompt += (content.strip() or "")[:6000]
    return prompt


def parse_and_save_questions(
    full_content: str,
    exercise_id: str,
    question_type: str,
    db_session,
) -> None:
    """
    解析模型返回的流式文本（题干 + 选项 + 答案行），写入 questions 与 answers 表，并更新 exercise 状态。
    试卷标题由分析阶段提供，在创建 Exercise 时已写入，此处不处理。
    解析不填 analysis，保持 None。
    """
    from app.models.exercise import Exercise
    from app.models.question import Question
    from app.models.answer import Answer

    items = _parse_questions_text(full_content)
    logger.info("[parse_and_save_questions] exercise_id=%s 解析出题目数=%d", exercise_id, len(items))
    for item in items:
        if not isinstance(item, dict):
            continue
        stem = item.get("stem") or ""
        if not stem:
            continue
        options = item.get("options")
        if options is not None and not isinstance(options, list):
            options = []
        correct = (item.get("correct") or "").strip()

        qid = str(uuid.uuid4())
        question = Question(
            id=qid,
            exercise_id=exercise_id,
            type=question_type,
            stem=stem,
            options=options,
        )
        db_session.add(question)
        db_session.flush()  # 先写入 questions，再插 answers，避免外键约束报错

        aid = str(uuid.uuid4())
        answer = Answer(
            id=aid,
            question_id=qid,
            correct_answer=correct,
            analysis=None,
        )
        db_session.add(answer)

    exercise = db_session.query(Exercise).filter(Exercise.id == exercise_id).first()
    if exercise:
        exercise.status = "done"
        logger.info("[parse_and_save_questions] exercise_id=%s 状态已设为 done", exercise_id)
    db_session.commit()
