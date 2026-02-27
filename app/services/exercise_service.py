"""AI 出题：分析材料、流式生成题目。使用与 llm_service 相同的 OpenAI 兼容客户端（阿里云百炼）。"""
import json
import logging
import re
import uuid
from typing import Any, AsyncIterator

from app.core.config import settings
from app.services.llm_service import get_openai_client
from sqlalchemy import select

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

# RAG 梳理时单次送入模型的最大字符，避免超长
RAG_ANALYZE_INPUT_MAX = 12000
RAG_ANALYZE_OUTPUT_MAX = 8000


async def analyze_rag_context(raw_rag_text: str) -> str:
    """
    对 RAG 召回后的原始片段做一次梳理：按主题/逻辑分块、去重合并、加小标题，便于作为知识库参考拼进出题提示词。
    尽量不丢失信息，只做整理。失败或空输入时返回原文本。
    """
    text = (raw_rag_text or "").strip()
    if not text or len(text) < 50:
        return raw_rag_text or ""

    input_text = text[:RAG_ANALYZE_INPUT_MAX]
    if len(text) > RAG_ANALYZE_INPUT_MAX:
        input_text += "\n\n[以上为截断后的内容，后续已省略]"

    prompt = f"""你是一个知识整理助手。下面是从知识库检索到的多段内容，可能重复、顺序混乱、话题交错。
请对以下内容进行梳理，要求：
1. 按主题或逻辑分成若干小节，每节可加简短小标题（如「## 主题名」或「【主题】」）。
2. 合并表述重复或高度相似的句子，保留一种说法即可；不同角度的内容都保留。
3. 顺序按逻辑或主题排列，便于阅读。
4. 不要删减实质性信息：概念、定义、公式、数据、结论等尽量全部保留，只做归纳与重组。
5. 直接输出梳理后的正文，不要输出 JSON、不要输出「梳理结果：」等前缀，不要输出 exerciseId。

【待梳理的知识库召回内容】
{input_text}
"""

    print("\n" + "=" * 60 + " [LLM 提示词] analyze_rag_context " + "=" * 60)
    print(prompt)
    print("=" * 60 + "\n")

    try:
        import time
        t0 = time.perf_counter()
        client = get_openai_client()
        completion = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"enable_thinking": True},
        )
        out = (completion.choices[0].message.content or "").strip()
        if out:
            result = out[:RAG_ANALYZE_OUTPUT_MAX]
            if len(out) > RAG_ANALYZE_OUTPUT_MAX:
                result += "\n\n[内容已截断]"
            logger.info(
                "[analyze_rag_context] 梳理完成 输入=%d 输出=%d 字符 耗时=%.2fs",
                len(text), len(result), time.perf_counter() - t0,
            )
            return result
    except Exception as e:
        logger.warning("[analyze_rag_context] 梳理失败，将使用原始 RAG 文本: %s", e)
    return raw_rag_text or ""


async def analyze_material(
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

    print("\n" + "=" * 60 + " [LLM 提示词] analyze_material " + "=" * 60)
    print(prompt)
    print("=" * 60 + "\n")

    client = get_openai_client()
    completion = await client.chat.completions.create(
        model=settings.llm_model,
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
_analysis_re = re.compile(r"^\s*解析[：:]\s*(.+)$", re.IGNORECASE)


def _parse_questions_text(full_content: str) -> list[dict[str, Any]]:
    """
    从流式输出文本解析题目块。
    按题号分块（题干与答案/解析之间可能有空行），每块内解析 stem/options/答案/解析。
    返回 [{"stem": "题干", "options": [...], "correct": "A", "analysis": "解析"}, ...]。
    """
    text = full_content.strip()
    # 去掉末尾可能被模型误输出的 exerciseId 行
    if text and "exerciseId" in text:
        lines = text.split("\n")
        while lines and lines[-1].strip().startswith("{") and "exerciseId" in lines[-1]:
            lines.pop()
        text = "\n".join(lines).strip()
    # 按“新题号”分块，避免题干与答案/解析之间的空行把一道题拆成多块
    blocks_raw = re.split(r"(?=\n\s*\d+[.、．：:]\s*)", text)
    blocks_raw = [b.strip() for b in blocks_raw if b.strip()]
    items: list[dict[str, Any]] = []
    stem_re = re.compile(r"^\s*(?:#*\s*)?【?\d+】?\s*[.、．：:]\s*.+")
    opt_re = re.compile(r"^\s*[A-D][.、．]\s*.+", re.IGNORECASE)
    for block in blocks_raw:
        stem = None
        options: list[str] = []
        correct = ""
        analysis = ""
        in_analysis = False
        for line in block.split("\n"):
            line_stripped = line.rstrip()
            if not line_stripped:
                in_analysis = False
                continue
            m_ans = _answer_re.match(line_stripped)
            if m_ans:
                correct = m_ans.group(1).strip()
                in_analysis = False
                continue
            m_ana = _analysis_re.match(line_stripped)
            if m_ana:
                analysis = m_ana.group(1).strip()
                in_analysis = True
                continue
            if in_analysis:
                analysis += "\n" + line_stripped
                continue
            if stem_re.match(line_stripped) or (not stem and re.match(r"^\s*【?\d+】?\s*.+", line_stripped)):
                if stem is not None:
                    break
                stem = line_stripped.strip()
            elif opt_re.match(line_stripped):
                options.append(line_stripped.strip())
        if stem:
            items.append({"stem": stem, "options": options, "correct": correct, "analysis": analysis})
    return items


async def stream_raw_and_collect(
    content: str,
    question_type: str,
    difficulty: str,
    count: int,
    rag_context: str | None = None,
    intent_context: str | None = None,
) -> AsyncIterator[str | dict[str, Any]]:
    """
    流式调用模型生成题目内容，逐个 yield 文本片段（仅 content，不含 reasoning）；
    结束时若拿到 usage 会 yield 一个 {"_usage": { inputTokens, outputTokens, totalTokens }}，调用方勿当正文下发。
    若传入 rag_context，会在 prompt 中先加入「知识库参考」再拼用户材料。
    调用方需收集完整响应后解析并落库。
    """
    prompt = _build_questions_prompt(
        content,
        question_type,
        difficulty,
        count,
        rag_context=rag_context,
        intent_context=intent_context,
    )
    print("\n" + "=" * 60 + " [LLM 提示词] stream_raw_and_collect（生成题目） " + "=" * 60)
    print(prompt)
    print("=" * 60 + "\n")
    logger.info(
        "[第二次调大模型-完整提示词]\n%s\n%s\n%s",
        "=" * 60,
        prompt,
        "=" * 60,
    )
    client = get_openai_client()
    completion = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": True},
        stream=True,
        stream_options={"include_usage": True},
    )
    is_answering = False
    last_usage = None
    async for chunk in completion:
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
    intent_context: str | None = None,
) -> str:
    type_cn = QUESTION_TYPE_LABELS.get(question_type, question_type)
    diff_cn = DIFFICULTY_LABELS.get(difficulty, difficulty)
    prompt = f"""你是出题助手。请严格以【用户意图】为主生成题目，知识库仅作参考；若知识库内容与用户意图不一致，请在生成时自行忽略知识库内容。
请根据材料生成 {count} 道{type_cn}（难度：{diff_cn}）。只输出题目正文，不要输出任何 JSON，不要输出 exerciseId。

【格式要求】
1. 题目之间用空行分隔（每道题之间至少一个空行）。
2. 题干行必须以题号开头，题号与题干之间必须有空格。例如：1. 题干内容  或  1、题干内容 或  【1】题干内容。
3. 单选题：题干下方每行一个选项，选项标记用大写字母 A、B、C、D，格式为 "A. 选项内容" 或 "A、选项内容"（只使用 A-D），答案填一个字母。
4. 多选题：同单选题格式，答案填多个字母如 "AB" 或 "ACD"，不要加顿号或空格。
5. 判断题：题干下方两行选项，格式为 "A. 正确" 与 "B. 错误"（或 A. 对 B. 错），答案填 A 或 B。
6. 填空题：只有题干行，题干中用下划线 ______ 表示填空处，不要选项行；答案填正确答案文本，多空用分号分隔如 "4；能量守恒"。
7. 简答题：只有题干行，不要选项行；答案填要点或完整短句。
8. 每道题在题干和选项（如有）之后，必须另起一行输出「答案：X」。答案不能为空。
9. 每道题在答案之后，必须另起一行输出「解析：……」，给出该题的简要解析，解析不能为空。
10. 不要输出任何 JSON，不要输出 {{"exerciseId"}} 等。
11. 数学符号用纯文本表示，不要使用 LaTeX 格式。

【示例：单选题】
1. 以下哪项是 Python 的特点？
A. 解释型语言
B. 编译型语言
C. 汇编语言
D. 机器语言
答案：A
解析：Python 是解释型语言，源代码由解释器逐行执行。

【示例：多选题】
2. 下列属于 Python 基本数据类型的有？（多选）
A. int
B. list
C. tuple
D. dict
答案：ABCD
解析：int、list、tuple、dict 均为 Python 内置基本数据类型。

【示例：判断题】
3. Python 中字符串是不可变类型。
A. 正确
B. 错误
答案：A
解析：字符串在 Python 中是不可变类型，修改会生成新字符串。

【示例：填空题】
4. 请写出 Python 中用于创建空列表的语法：______
答案：[]
解析：方括号 [] 表示空列表，是 Python 的字面量写法。

5. 根据牛顿第二定律 F=ma，质量为 2 kg 的物体受 10 N 力，加速度为 ______ m/s²。
答案：5
解析：a=F/m=10/2=5 m/s²。

【示例：简答题】
6. 请简述 Python 中 list 和 tuple 的区别。
答案：list 可变，tuple 不可变；list 用 []，tuple 用 ()。
解析：list 支持增删改，tuple 创建后不可变，常用于固定结构。

"""
    if intent_context and (intent_context := intent_context.strip()):
        prompt += "【用户意图】\n" + intent_context[:2000] + "\n\n"
    if rag_context and (rag_context := rag_context.strip()):
        prompt += "【知识库参考】\n" + rag_context[:4000] + "\n\n"
    prompt += "【用户材料】\n"
    prompt += (content.strip() or "")[:6000]
    return prompt


async def supplement_question_answer_and_analysis(
    stem: str,
    options: list[str],
    question_type: str,
) -> tuple[str, str]:
    """
    仅把题干+选项发给大模型，补全答案和解析（节约 token，不重复发材料）。
    返回 (correct_answer, analysis)；若解析失败返回 ("", "")。
    """
    type_cn = QUESTION_TYPE_LABELS.get(question_type, question_type)
    question_text = stem.strip()
    if options:
        question_text += "\n" + "\n".join(options)
    prompt = f"""请根据以下题目给出正确答案和解析。只输出两行，不要其他内容。
第一行：答案：X（单选题/多选题填选项字母如 A；填空/简答题填正确答案文本，不能为空）。
第二行：解析：简要解析（不能为空）。

题目（{type_cn}）：
{question_text}
"""
    print("\n" + "=" * 60 + " [LLM 提示词] supplement_question_answer_and_analysis " + "=" * 60)
    print(prompt)
    print("=" * 60 + "\n")

    try:
        client = get_openai_client()
        completion = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"enable_thinking": True},  # 该模型要求必须为 True，否则 400
        )
        raw = (completion.choices[0].message.content or "").strip()
        correct = ""
        analysis = ""
        for line in raw.split("\n"):
            line = line.strip()
            m_ans = _answer_re.match(line)
            if m_ans:
                correct = m_ans.group(1).strip()
                continue
            m_ana = _analysis_re.match(line)
            if m_ana:
                analysis = m_ana.group(1).strip()
                continue
            if line.startswith("解析：") or line.startswith("解析:"):
                analysis = line.split(":", 1)[-1].split("：", 1)[-1].strip()
        return (correct, analysis)
    except Exception as e:
        logger.warning("[supplement_question_answer_and_analysis] 补全失败 stem=%s: %s", stem[:50], e)
        return ("", "")


async def parse_and_save_questions(
    full_content: str,
    exercise_id: str,
    question_type: str,
    db_session,
) -> None:
    """
    解析模型返回的流式文本（题干 + 选项 + 答案 + 解析），写入 questions 与 answers 表，并更新 exercise 状态。
    答案与解析必须非空：若任一项为空则仅把该题题干+选项发给大模型补全一次；补全后仍为空则跳过该题不落库。
    """
    from app.repositories.exercise_repository import add_answer, add_question, set_exercise_status

    items = _parse_questions_text(full_content)
    logger.info("[parse_and_save_questions] exercise_id=%s 解析出题目数=%d", exercise_id, len(items))
    # 调试：控制台打印解析过程
    print("\n" + "-" * 50 + " [解析题目过程] exercise_id=%s " % exercise_id + "-" * 50)
    print("解析出 %d 道题目（原始）" % len(items))
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            print("  [%d] 跳过：非 dict" % (i + 1))
            continue
        stem = item.get("stem") or ""
        if not stem:
            print("  [%d] 跳过：题干为空" % (i + 1))
            continue
        options = item.get("options")
        if options is not None and not isinstance(options, list):
            options = []
        correct = (item.get("correct") or "").strip()
        analysis = (item.get("analysis") or "").strip()
        print("  [%d] 题干: %s" % (i + 1, stem[:80] + "…" if len(stem) > 80 else stem))
        print("       选项: %s | 答案: %s | 解析: %s" % (
            options if options else "[]",
            repr(correct)[:50],
            (analysis[:50] + "…" if len(analysis) > 50 else repr(analysis)) if analysis else "(空)",
        ))

        # 答案或解析为空时，仅把该题发给大模型补全（节约 token）
        if not correct or not analysis:
            print("        -> 答案或解析为空，调用大模型补全...")
            correct_sup, analysis_sup = await supplement_question_answer_and_analysis(
                stem, options, question_type
            )
            if correct_sup:
                correct = correct_sup
                print("        -> 补全答案: %s" % repr(correct)[:60])
            if analysis_sup:
                analysis = analysis_sup
                print("        -> 补全解析: %s" % (analysis[:60] + "…" if len(analysis) > 60 else analysis))
        # 约束：答案与解析必须非空才落库，否则跳过该题
        if not correct or not analysis:
            logger.warning(
                "[parse_and_save_questions] 题目答案或解析为空已跳过 exercise_id=%s stem=%s",
                exercise_id,
                stem[:50],
            )
            print("  [%d] 跳过落库：答案或解析仍为空" % (i + 1))
            continue

        qid = str(uuid.uuid4())
        await add_question(
            db_session,
            question_id=qid,
            exercise_id=exercise_id,
            type=question_type,
            stem=stem,
            options=options,
        )

        aid = str(uuid.uuid4())
        print("  [%d] 落库: question_id=%s answer_id=%s" % (i + 1, qid, aid))
        await add_answer(
            db_session,
            answer_id=aid,
            question_id=qid,
            correct_answer=correct,
            analysis=analysis,
        )

    await set_exercise_status(db_session, exercise_id, "done")
    logger.info("[parse_and_save_questions] exercise_id=%s 状态已设为 done", exercise_id)
    print("-" * 50 + " [解析题目过程结束] exercise_id=%s " % exercise_id + "-" * 50 + "\n")
