"""Measure Redpen against a teacher's marks.

    python eval/evaluate.py                # sample class (samples/class.json)
    python eval/evaluate.py --runs 3       # repeat to measure consistency
    python eval/evaluate.py --set messy    # sloppy handwriting, badly photographed

For each sheet it runs the real pipeline (Lightning rubric -> Super VL reading -> Ultra grading) and reports:
  * reading accuracy: word accuracy of Super VL's transcription vs the true answer text
  * grading agreement: exact / within 0.5 / within 1 mark of the teacher, per question
  * total-score error per student, cost and latency
Results are written to eval/RESULTS.md (or RESULTS_messy.md) and the matching results*.json.
"""

import argparse
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redpen import pipeline  # noqa: E402
from redpen.images import to_data_url  # noqa: E402
from redpen.llm import Ledger  # noqa: E402


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def word_accuracy(truth: str, got: str) -> float:
    """1 - word error rate (Levenshtein over words), floored at 0."""
    a, b = words(truth), words(got)
    if not a:
        return 1.0 if not b else 0.0
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa != wb)))
        prev = cur
    return max(0.0, 1 - prev[-1] / len(a))


def grade_student(student: dict, rubric: dict, ledger: Ledger, folder: str) -> dict:
    slug = student["name"].lower().replace(" ", "_")
    image = to_data_url((ROOT / "samples" / folder / f"{slug}.jpg").read_bytes())
    started = time.time()
    reading = pipeline.read_sheet([image], rubric, ledger)
    grading = pipeline.grade_sheet(rubric, reading, ledger)
    return {"student": student, "reading": reading, "grading": grading, "seconds": time.time() - started}


SET_DESCRIPTION = {
    "neat": "neatly handwritten-style answer sheets (`samples/sheets/`)",
    "messy": "sloppily handwritten, badly photographed answer sheets (`samples/sheets_messy/`: uneven letters, cramped words, scribbles, blur, shadow, skew; one sheet is near-illegible on purpose)",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--set", choices=["neat", "messy"], default="neat")
    args = parser.parse_args()
    folder = "sheets" if args.set == "neat" else "sheets_messy"
    suffix = "" if args.set == "neat" else "_messy"

    data = json.loads((ROOT / "samples" / "class.json").read_text())
    ledger = Ledger()
    rubric = pipeline.structure_rubric((ROOT / "samples" / "answer_key.txt").read_text(), ledger)

    rows, reading_scores, total_errors, sheet_seconds = [], [], [], []
    for run in range(args.runs):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda s: grade_student(s, rubric, ledger, folder), data["students"]))
        for r in results:
            s, g = r["student"], r["grading"]
            sheet_seconds.append(r["seconds"])
            teacher_total = sum(s["marks"].values())
            total_errors.append(abs(g["score"] - teacher_total))
            for q in g["questions"]:
                qid = q["question_id"]
                truth = s["answers"].get(qid, "")
                got = next(a for a in r["reading"]["answers"] if a["question_id"] == qid)
                if truth:
                    reading_scores.append(word_accuracy(truth, got["transcription"]))
                rows.append(
                    {
                        "run": run + 1,
                        "student": s["name"],
                        "question_id": qid,
                        "teacher": s["marks"][qid],
                        "redpen": q["score"],
                        "diff": q["score"] - s["marks"][qid],
                        "flagged": q["needs_review"],
                    }
                )
        print(f"run {run + 1}: graded {len(results)} sheets")

    n = len(rows)
    diffs = [abs(r["diff"]) for r in rows]
    exact = sum(d == 0 for d in diffs) / n
    within_half = sum(d <= 0.5 for d in diffs) / n
    within_one = sum(d <= 1 for d in diffs) / n
    mae = statistics.mean(diffs)
    flagged_wrong = [r for r in rows if abs(r["diff"]) > 0.5]
    caught = sum(r["flagged"] for r in flagged_wrong)
    calls = ledger.to_list()
    cost = sum(c["cost_usd"] for c in calls)
    sheets = len(data["students"]) * args.runs

    summary = {
        "sheets": sheets,
        "answers": n,
        "reading_word_accuracy": round(statistics.mean(reading_scores), 4),
        "exact_agreement": round(exact, 4),
        "within_half_mark": round(within_half, 4),
        "within_one_mark": round(within_one, 4),
        "mean_abs_error_per_question": round(mae, 3),
        "mean_abs_error_per_student_total": round(statistics.mean(total_errors), 3),
        "answers_off_by_more_than_half": len(flagged_wrong),
        "of_which_flagged_for_review": caught,
        "cost_usd_total": round(cost, 4),
        "cost_usd_per_sheet": round(cost / sheets, 4),
        "seconds_per_sheet_median": round(statistics.median(sheet_seconds), 1),
    }
    (ROOT / "eval" / f"results{suffix}.json").write_text(json.dumps({"summary": summary, "rows": rows, "calls": calls}, indent=2))

    disagreements = "\n".join(
        f"| {r['run']} | {r['student']} | {r['question_id']} | {r['teacher']:g} | {r['redpen']:g} | {'yes' if r['flagged'] else 'no'} |"
        for r in rows
        if r["diff"] != 0
    )
    md = f"""# Redpen evaluation

Generated by `python eval/evaluate.py --runs {args.runs} --set {args.set}` on {time.strftime('%Y-%m-%d')}.

**Data:** the synthetic sample class in `samples/` — {len(data['students'])} {SET_DESCRIPTION[args.set]},
4 questions each, written to contain common Class 8 science misconceptions. Reference marks were set by
hand by the Redpen author following the answer key (not yet by an independent teacher).
{args.runs} run(s), {n} graded answers in total.

| Metric | Result |
|---|---|
| Handwriting reading accuracy (Super VL, word-level) | **{summary['reading_word_accuracy']:.1%}** |
| Exact agreement with reference marks, per question | **{exact:.1%}** |
| Within ½ mark of reference | **{within_half:.1%}** |
| Within 1 mark of reference | **{within_one:.1%}** |
| Mean absolute error per question | {mae:.2f} marks |
| Mean absolute error per student total (out of 10) | {summary['mean_abs_error_per_student_total']:.2f} marks |
| Answers off by more than ½ mark | {len(flagged_wrong)} ({caught} of them flagged for teacher review) |
| Cost per sheet (read + grade) | ${summary['cost_usd_per_sheet']:.4f} |
| Median time per sheet | {summary['seconds_per_sheet_median']}s |

## Every disagreement with the reference marks

| Run | Student | Question | Reference | Redpen | Flagged for review |
|---|---|---|---|---|---|
{disagreements or "| – | – | – | – | – | – |"}

## Caveats
- The sample sheets are rendered with handwriting fonts, which are cleaner than real student handwriting.
  Reading accuracy on real sheets will be lower; that is why Redpen flags unclear handwriting for review.
- 8 students is a small sample. Treat these numbers as a smoke test, not a benchmark.
- Every disagreement above is a half-mark judgement call on a partly-made point — the kind two human
  examiners also disagree on.
"""
    (ROOT / "eval" / f"RESULTS{suffix}.md").write_text(md)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
