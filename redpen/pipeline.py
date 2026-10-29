"""Redpen's grading pipeline.

    answer key text --(Lightning)--> structured rubric
    sheet photos    --(Super VL)---> faithful transcription per question
    transcription   --(Ultra)------> per-criterion marks, evidence, feedback, confidence
    all students    --(Ultra)------> class misconceptions + reteach plan
    feedback slip   --(Lightning)--> translated for parents

Models only make judgements. Arithmetic (totals, clamping, class statistics) is done
here in Python, so a model can never mis-add a student's marks.
"""

import json
import re
import statistics

from . import config
from .llm import Ledger, ModelError, chat_json

# --------------------------------------------------------------------------- rubric


RUBRIC_PROMPT = """You turn a teacher's answer key into a structured marking rubric.

Return JSON:
{
  "title": "short assessment title",
  "questions": [
    {
      "id": "Q1",
      "question": "question text",
      "max_marks": 3,
      "model_answer": "the ideal answer",
      "criteria": [
        {"id": "Q1.a", "description": "one specific, checkable point a student must make", "marks": 1}
      ]
    }
  ]
}

Rules:
- Keep the teacher's question numbering and marks exactly.
- If the teacher lists marking points, use them as criteria. Otherwise split the model answer into
  specific, checkable points whose marks add up to max_marks.
- Criteria must be observable in a written answer (e.g. "states that oxygen is released"),
  never vague ("good understanding").
- For numerical questions, separate method/working from the final answer and unit.
"""


def structure_rubric(answer_key: str, ledger: Ledger) -> dict:
    rubric = chat_json(
        "Structure answer key",
        config.MODEL_FAST,
        [{"role": "system", "content": RUBRIC_PROMPT}, {"role": "user", "content": answer_key}],
        ledger,
        max_tokens=4000,
    )
    return normalize_rubric(rubric)


def normalize_rubric(rubric: dict) -> dict:
    """Validate the rubric and make criterion marks add up to each question's max marks."""
    questions = rubric.get("questions") or []
    if not questions:
        raise ModelError("No questions found in the answer key.")
    for i, q in enumerate(questions, 1):
        q["id"] = str(q.get("id") or f"Q{i}")
        q["max_marks"] = float(q.get("max_marks") or 0)
        criteria = [c for c in q.get("criteria") or [] if c.get("description")]
        if not criteria:
            criteria = [{"description": q.get("model_answer") or "Correct answer", "marks": q["max_marks"]}]
        for j, c in enumerate(criteria):
            c["id"] = c.get("id") or f"{q['id']}.{chr(97 + j)}"
            c["marks"] = float(c.get("marks") or 0)
        total = sum(c["marks"] for c in criteria)
        if q["max_marks"] <= 0:
            q["max_marks"] = total
        elif abs(total - q["max_marks"]) > 1e-6:
            # Rescale to the teacher's max marks in half-mark steps; remainder goes on the last criterion.
            for c in criteria:
                share = c["marks"] / total if total else 1 / len(criteria)
                c["marks"] = round(share * q["max_marks"] * 2) / 2
            criteria[-1]["marks"] += q["max_marks"] - sum(c["marks"] for c in criteria)
        q["criteria"] = criteria
    rubric["title"] = rubric.get("title") or "Assessment"
    rubric["total_marks"] = sum(q["max_marks"] for q in questions)
    return rubric


# --------------------------------------------------------------------------- reading

READ_PROMPT = """You are a meticulous transcriber of students' handwritten exam answer sheets.
You will see photos of one student's answer sheet (one or more pages, in order).

Questions on this paper:
{questions}

Return JSON:
{{
  "name_on_sheet": "student name written on the sheet, or null",
  "answers": [
    {{
      "question_id": "Q1",
      "attempted": true,
      "transcription": "the student's answer, word for word",
      "diagram": "short description of any drawing/diagram/working in the answer, or null",
      "legibility": "clear | partly_unclear | illegible",
      "unclear_words": ["words you could not read with confidence"]
    }}
  ]
}}

Rules:
- Transcribe EXACTLY what the student wrote, including spelling and grammar mistakes. Never correct,
  improve or complete the answer. Grading depends on what is really on the page.
- Leave out any word that has a line drawn through it — the student crossed it out.
- Match each answer to the question number the student wrote. Include every question listed above;
  if a question was not answered, set attempted=false and transcription="".
- Write [?] in the transcription where a word is unreadable, and list your best guesses in unclear_words.
- NEVER fill gaps from what the answer "should" say. Students write incomplete, wrong and oddly worded
  answers; a textbook-perfect sentence on a messy page is a sign you are guessing. Keep the student's
  own word order and phrasing even when it is clumsy, and prefer [?] over a plausible guess.
- Judge legibility honestly: if you had to guess any word, legibility is at least "partly_unclear".
"""


def read_sheet(page_data_urls: list[str], rubric: dict, ledger: Ledger) -> dict:
    questions = "\n".join(f"- {q['id']}: {q['question']}" for q in rubric["questions"])
    content: list[dict] = [{"type": "text", "text": READ_PROMPT.format(questions=questions)}]
    for i, url in enumerate(page_data_urls, 1):
        content.append({"type": "text", "text": f"Page {i}:"})
        content.append({"type": "image_url", "image_url": {"url": url}})
    reading = chat_json(
        "Read handwriting",
        config.MODEL_VISION,
        [{"role": "user", "content": content}],
        ledger,
        max_tokens=4000,
    )
    by_id = {str(a.get("question_id")): a for a in reading.get("answers") or []}
    answers = []
    for q in rubric["questions"]:
        a = by_id.get(q["id"], {})
        text = (a.get("transcription") or "").strip()
        answers.append(
            {
                "question_id": q["id"],
                "attempted": bool(a.get("attempted", bool(text))) and bool(text or a.get("diagram")),
                "transcription": text,
                "diagram": a.get("diagram") or None,
                "legibility": a.get("legibility") if a.get("legibility") in ("clear", "partly_unclear", "illegible") else "clear",
                "unclear_words": [w for w in a.get("unclear_words") or [] if isinstance(w, str)],
            }
        )
    return {"name_on_sheet": reading.get("name_on_sheet") or None, "answers": answers}


# --------------------------------------------------------------------------- grading

GRADE_PROMPT = """You are an experienced, fair examiner. Grade one student's answers against the rubric.

RUBRIC (JSON):
{rubric}

STUDENT'S ANSWERS (transcribed from handwriting, JSON):
{answers}

Return JSON:
{{
  "questions": [
    {{
      "question_id": "Q1",
      "criteria": [
        {{
          "criterion_id": "Q1.a",
          "awarded": 1,
          "evidence": "exact quote from the student's answer that earns (or fails) this point, or empty",
          "reason": "one short sentence explaining the mark"
        }}
      ],
      "misconception": "short label for a conceptual error the answer reveals, or null",
      "feedback": "1-2 sentences to the student: what was right, what to fix",
      "confidence": 0.9
    }}
  ],
  "overall_feedback": "2-3 encouraging, specific sentences to the student",
  "next_step": "the single most useful thing this student should practise next"
}}

Marking rules:
- Award marks for meaning, not exact wording. Accept correct synonyms and equivalent explanations.
- Do not penalise spelling or grammar unless the rubric asks for it, or the meaning becomes wrong.
- 'awarded' may be 0, the criterion's full marks, or a half mark when a point is partly made.
- Only quote evidence that actually appears in the transcription. Never invent student text.
- A misconception is a wrong idea (e.g. "thinks plants take in oxygen for photosynthesis"), not a missing point.
- Lower confidence (< 0.7) when handwriting was unclear, the answer is ambiguous, or the rubric
  does not clearly cover what the student wrote.
- Unattempted questions get 0 on every criterion and confidence 1.
"""


def grade_sheet(rubric: dict, reading: dict, ledger: Ledger) -> dict:
    rubric_for_prompt = {"questions": [{k: q[k] for k in ("id", "question", "max_marks", "model_answer", "criteria")} for q in rubric["questions"]]}
    raw = chat_json(
        "Grade answers",
        config.MODEL_REASONING,
        [
            {
                "role": "user",
                "content": GRADE_PROMPT.format(
                    rubric=json.dumps(rubric_for_prompt, ensure_ascii=False),
                    answers=json.dumps(reading["answers"], ensure_ascii=False),
                ),
            }
        ],
        ledger,
        thinking=True,
        max_tokens=16000,
    )
    return reconcile_grades(rubric, reading, raw)


def _squash(text: str) -> str:
    """Lowercase and drop punctuation/whitespace, for checking a quote really appears in a transcription."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def reconcile_grades(rubric: dict, reading: dict, raw: dict) -> dict:
    """Clamp marks to the rubric, compute totals in code, and flag answers a teacher should check."""
    graded_by_q = {str(g.get("question_id")): g for g in raw.get("questions") or []}
    reading_by_q = {a["question_id"]: a for a in reading["answers"]}
    questions = []
    for q in rubric["questions"]:
        g = graded_by_q.get(q["id"], {})
        r = reading_by_q.get(q["id"], {})
        crit_by_id = {str(c.get("criterion_id")): c for c in g.get("criteria") or []}
        criteria = []
        for c in q["criteria"]:
            gc = crit_by_id.get(c["id"], {})
            try:
                awarded = float(gc.get("awarded") or 0)
            except (TypeError, ValueError):
                awarded = 0.0
            awarded = max(0.0, min(c["marks"], round(awarded * 2) / 2))
            evidence = (gc.get("evidence") or "").strip()
            # Drop "evidence" the model did not actually find in the student's text.
            if evidence and _squash(evidence)[:30] not in _squash(r.get("transcription") or ""):
                evidence = ""
            criteria.append(
                {
                    "criterion_id": c["id"],
                    "description": c["description"],
                    "max": c["marks"],
                    "awarded": awarded,
                    "evidence": evidence,
                    "reason": gc.get("reason") or "",
                }
            )
        if not r.get("attempted"):
            for c in criteria:
                c["awarded"] = 0.0
        try:
            confidence = float(g.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        review_reasons = []
        if r.get("legibility") in ("partly_unclear", "illegible"):
            review_reasons.append("Hard-to-read handwriting — compare the transcription with the photo")
        if confidence < 0.7:
            review_reasons.append("Grader unsure")
        if not g:
            review_reasons.append("Not graded by model")
        questions.append(
            {
                "question_id": q["id"],
                "max": q["max_marks"],
                "score": sum(c["awarded"] for c in criteria),
                "criteria": criteria,
                "misconception": g.get("misconception") or None,
                "feedback": g.get("feedback") or "",
                "confidence": round(confidence, 2),
                "needs_review": bool(review_reasons),
                "review_reasons": review_reasons,
            }
        )
    score = sum(q["score"] for q in questions)
    total = rubric["total_marks"]
    return {
        "questions": questions,
        "score": score,
        "total": total,
        "percent": round(100 * score / total, 1) if total else 0.0,
        "overall_feedback": raw.get("overall_feedback") or "",
        "next_step": raw.get("next_step") or "",
        "needs_review": sum(1 for q in questions if q["needs_review"]),
    }


# --------------------------------------------------------------------------- class report

REPORT_PROMPT = """You are a head teacher reviewing a class's marked test to plan the next lesson.

ASSESSMENT: {title}
CLASS SIZE: {count} students
PER-QUESTION STATISTICS (computed exactly; "full_marks" and "zero" are numbers of students):
{stats}

WHAT EACH STUDENT GOT WRONG (missed rubric points and misconceptions):
{evidence}

Return JSON:
{{
  "headline": "one sentence: the most important thing this teacher should know about the class",
  "misconceptions": [
    {{
      "question_id": "Q1",
      "label": "short name of the wrong idea",
      "explanation": "what students believe and why it is wrong, in 1-2 sentences",
      "students": ["names"]
    }}
  ],
  "reteach_plan": [
    {{"topic": "what to reteach", "why": "evidence from this class", "activity": "a concrete 10-minute classroom activity"}}
  ],
  "students_to_support": [{{"name": "student", "reason": "specific reason"}}],
  "strengths": ["what most of the class did well"]
}}

Rules: group students who share the same underlying wrong idea, even if worded differently.
Only use names and facts present above; when you quote a number, copy it from the statistics
(e.g. "5 of {count} students"), never compute your own. Order misconceptions by number of students, most first.
Give at most 3 reteach activities.
"""


def class_stats(rubric: dict, students: list[dict]) -> dict:
    per_question = []
    for q in rubric["questions"]:
        scores = [next((x["score"] for x in s["grading"]["questions"] if x["question_id"] == q["id"]), 0) for s in students]
        per_question.append(
            {
                "question_id": q["id"],
                "question": q["question"],
                "max": q["max_marks"],
                "average": round(statistics.mean(scores), 2) if scores else 0,
                "average_percent": round(100 * statistics.mean(scores) / q["max_marks"], 1) if scores and q["max_marks"] else 0,
                "full_marks": sum(1 for x in scores if x >= q["max_marks"]),
                "zero": sum(1 for x in scores if x == 0),
            }
        )
    percents = [s["grading"]["percent"] for s in students]
    return {
        "students": len(students),
        "average_percent": round(statistics.mean(percents), 1) if percents else 0,
        "median_percent": round(statistics.median(percents), 1) if percents else 0,
        "highest": max(percents) if percents else 0,
        "lowest": min(percents) if percents else 0,
        "needs_review": sum(s["grading"]["needs_review"] for s in students),
        "per_question": per_question,
    }


def class_report(rubric: dict, students: list[dict], ledger: Ledger) -> dict:
    stats = class_stats(rubric, students)
    evidence = []
    for s in students:
        for q in s["grading"]["questions"]:
            missed = [c["description"] for c in q["criteria"] if c["awarded"] < c["max"]]
            if missed or q["misconception"]:
                evidence.append(
                    {"student": s["name"], "question_id": q["question_id"], "missed_points": missed, "misconception": q["misconception"]}
                )
    report = chat_json(
        "Class insights",
        config.MODEL_REASONING,
        [
            {
                "role": "user",
                "content": REPORT_PROMPT.format(
                    title=rubric.get("title", ""),
                    count=len(students),
                    stats=json.dumps(stats["per_question"], ensure_ascii=False),
                    evidence=json.dumps(evidence, ensure_ascii=False),
                ),
            }
        ],
        ledger,
        thinking=True,
        max_tokens=12000,
    )
    names = {s["name"] for s in students}
    for m in report.get("misconceptions") or []:
        m["students"] = [n for n in m.get("students") or [] if n in names]
    report["misconceptions"] = [m for m in report.get("misconceptions") or [] if m["students"]]
    report["students_to_support"] = [x for x in report.get("students_to_support") or [] if x.get("name") in names]
    return {"stats": stats, **report}


# --------------------------------------------------------------------------- translation

TRANSLATE_SYSTEM = """You are a translator for a school. You translate a teacher's feedback slip
faithfully. You never speak as the student, never write "I" or "my" on the student's behalf, and never
add or remove information."""

TRANSLATE_PROMPT = """Translate this teacher's feedback slip from English into {language}.
- Write in {language}{script}. Every word must be {language}, including the labels ("Student",
  "Test", "Score", "Feedback", "Next step") — only people's names, numbers and formulas stay as they are.
- Keep the same lines in the same order, one "label: text" per line. Do not merge them into a letter.
- The teacher wrote the feedback to the student ("you"). Keep it addressed to the student in the
  second person — never change it to first person ("I", "my", "my name is").
- Keep scores exactly as written; keep subject terms accurate.
Return JSON: {{"text": "the translated lines, separated by \\n"}}

FEEDBACK SLIP:
{text}
"""

# Lightning sometimes answers in romanised form or returns the English unchanged; the script check catches both.
SCRIPTS = {
    "Hindi": (" in Devanagari script", "ऀ", "ॿ"),
    "Marathi": (" in Devanagari script", "ऀ", "ॿ"),
    "Tamil": (" in Tamil script", "஀", "௿"),
    "Bengali": (" in Bengali script", "ঀ", "৿"),
}


def _in_script(text: str, lo: str, hi: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(lo <= c <= hi for c in letters) / len(letters) > 0.5


def translate(text: str, language: str, ledger: Ledger) -> str:
    script, lo, hi = SCRIPTS.get(language, ("", None, None))
    messages = [
        {"role": "system", "content": TRANSLATE_SYSTEM},
        {"role": "user", "content": TRANSLATE_PROMPT.format(language=language, script=script, text=text)},
    ]
    result = ""
    # Ultra, not Lightning: Lightning's Tamil and Bengali came out garbled in testing. Reasoning stays off;
    # a slip costs under $0.001.
    for _ in range(3):
        result = chat_json("Translate feedback", config.MODEL_REASONING, messages, ledger, max_tokens=2000).get("text") or ""
        if lo is None and result.strip() and result.strip() != text.strip():
            break
        if lo is not None and _in_script(result, lo, hi):
            break
    return result
