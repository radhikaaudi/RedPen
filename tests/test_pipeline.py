"""Offline tests for the code that checks the models' work. No API key or network needed.

Run:  python -m unittest discover tests
"""

import base64
import io
import json
import unittest
from unittest import mock

from PIL import Image

from redpen import pipeline
from redpen.images import ImageError, to_data_url
from redpen.llm import Ledger, ModelError, extract_json

RUBRIC = pipeline.normalize_rubric(
    {
        "title": "Maths UT",
        "questions": [
            {
                "id": "Q1",
                "question": "Find the selling price.",
                "max_marks": 4,
                "criteria": [
                    {"id": "Q1.a", "description": "profit = 15/100 x 2400", "marks": 1},
                    {"id": "Q1.b", "description": "profit = 360", "marks": 1},
                    {"id": "Q1.c", "description": "SP = CP + profit", "marks": 1},
                    {"id": "Q1.d", "description": "SP = 2760", "marks": 1},
                ],
            },
            {
                "id": "Q2",
                "question": "Why do we see lightning first?",
                "max_marks": 2,
                "criteria": [
                    {"id": "Q2.a", "description": "light is faster than sound", "marks": 1},
                    {"id": "Q2.b", "description": "produced at the same time", "marks": 1},
                ],
            },
        ],
    }
)


def answer(qid, text, legibility="clear", attempted=True, unclear=()):
    return {"question_id": qid, "attempted": attempted, "transcription": text, "diagram": None,
            "legibility": legibility, "unclear_words": list(unclear)}


def reading(q1="Profit = 15/100 x 2400 = 340. SP = 2400 + 340 = 2740", q2="Light is faster than sound.", **kw):
    return {"name_on_sheet": None, "answers": [answer("Q1", q1, **kw.get("q1kw", {})), answer("Q2", q2, **kw.get("q2kw", {}))]}


def graded(q1=None, q2=None, **extra):
    base = {
        "question_id": "Q1",
        "criteria": [{"criterion_id": f"Q1.{x}", "awarded": a, "evidence": "", "reason": ""} for x, a in zip("abcd", (1, 0, 1, 0))],
        "sentiment": "right_direction",
        "sentiment_note": "Right method; slipped on 15% of 2400.",
        "answer_correct": False,
        "steps": [{"work": "15/100 x 2400 = 340", "ok": False, "note": "slip"}, {"work": "2400 + 340 = 2740", "ok": True, "note": "ECF"}],
        "confidence": 0.9,
    }
    base.update(q1 or {})
    second = {"question_id": "Q2", "criteria": [{"criterion_id": "Q2.a", "awarded": 1}, {"criterion_id": "Q2.b", "awarded": 0}],
              "sentiment": "partly_right", "answer_correct": True, "steps": [], "confidence": 0.9}
    second.update(q2 or {})
    return {"questions": [base, second], "overall_feedback": "ok", "next_step": "practise", **extra}


def q(result, qid):
    return next(x for x in result["questions"] if x["question_id"] == qid)


class NormalizeRubric(unittest.TestCase):
    def test_rescales_criteria_to_teacher_max_marks(self):
        r = pipeline.normalize_rubric({"questions": [{"id": "Q1", "max_marks": 3, "criteria": [
            {"description": "a", "marks": 1}, {"description": "b", "marks": 1}]}]})
        self.assertEqual(sum(c["marks"] for c in r["questions"][0]["criteria"]), 3)
        self.assertEqual(r["total_marks"], 3)

    def test_missing_criteria_become_one_whole_answer_criterion(self):
        r = pipeline.normalize_rubric({"questions": [{"question": "x", "max_marks": 2, "model_answer": "y"}]})
        crit = r["questions"][0]["criteria"]
        self.assertEqual((len(crit), crit[0]["marks"], crit[0]["id"]), (1, 2, "Q1.a"))

    def test_zero_max_marks_takes_criteria_sum(self):
        r = pipeline.normalize_rubric({"questions": [{"id": "Q1", "criteria": [{"description": "a", "marks": 2}]}]})
        self.assertEqual(r["questions"][0]["max_marks"], 2)

    def test_no_questions_is_an_error(self):
        with self.assertRaises(ModelError):
            pipeline.normalize_rubric({"questions": []})


class MarksAndEvidence(unittest.TestCase):
    def test_marks_are_clamped_and_rounded_to_half_marks(self):
        raw = graded({"criteria": [{"criterion_id": "Q1.a", "awarded": 5}, {"criterion_id": "Q1.b", "awarded": -2},
                                   {"criterion_id": "Q1.c", "awarded": 0.3}, {"criterion_id": "Q1.d", "awarded": "abc"}]})
        r = pipeline.reconcile_grades(RUBRIC, reading(), raw)
        self.assertEqual([c["awarded"] for c in q(r, "Q1")["criteria"]], [1, 0, 0.5, 0])

    def test_totals_are_computed_in_code(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded())
        self.assertEqual((q(r, "Q1")["score"], q(r, "Q2")["score"], r["score"], r["total"], r["percent"]), (2, 1, 3, 6, 50.0))

    def test_invented_evidence_is_dropped_real_evidence_kept(self):
        raw = graded(q2={"criteria": [{"criterion_id": "Q2.a", "awarded": 1, "evidence": "Light is faster than sound"},
                                      {"criterion_id": "Q2.b", "awarded": 0, "evidence": "both happen at the same time"}]})
        crit = q(pipeline.reconcile_grades(RUBRIC, reading(), raw), "Q2")["criteria"]
        self.assertEqual((crit[0]["evidence"], crit[1]["evidence"]), ("Light is faster than sound", ""))

    def test_unattempted_question_scores_zero_even_if_model_gave_marks(self):
        rd = reading(q2="", q2kw={"attempted": False})
        r = pipeline.reconcile_grades(RUBRIC, rd, graded())
        self.assertEqual((q(r, "Q2")["score"], q(r, "Q2")["sentiment"]), (0, "not_attempted"))

    def test_question_the_model_skipped_is_zero_and_flagged(self):
        raw = graded()
        raw["questions"] = raw["questions"][:1]
        r = pipeline.reconcile_grades(RUBRIC, reading(), raw)
        self.assertEqual(q(r, "Q2")["score"], 0)
        self.assertIn("Not graded by model", q(r, "Q2")["review_reasons"])

    def test_bad_confidence_values(self):
        for value, expected in (("high", 0.5), (7, 1.0), (-1, 0.0)):
            r = pipeline.reconcile_grades(RUBRIC, reading(), graded(q2={"confidence": value}))
            self.assertEqual(q(r, "Q2")["confidence"], expected)

    def test_low_confidence_is_flagged(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded(q2={"confidence": 0.5}))
        self.assertIn("Grader unsure", q(r, "Q2")["review_reasons"])


class SentimentAndIntervention(unittest.TestCase):
    """Sentiment is the direction of the student's thinking. Right thinking + wrong answer -> teacher intervenes."""

    def test_right_thinking_wrong_answer_asks_for_teacher_intervention(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded())
        self.assertTrue(q(r, "Q1")["needs_intervention"])
        self.assertIn("Right thinking, wrong answer — teacher intervention needed", q(r, "Q1")["review_reasons"])
        self.assertEqual((r["needs_intervention"], len(q(r, "Q1")["steps"])), (1, 2))

    def test_full_marks_is_never_an_intervention(self):
        raw = graded({"criteria": [{"criterion_id": f"Q1.{x}", "awarded": 1} for x in "abcd"], "answer_correct": True})
        res = q(pipeline.reconcile_grades(RUBRIC, reading(), raw), "Q1")
        self.assertFalse(res["needs_intervention"] or res["needs_review"])

    def test_wrong_direction_is_not_an_intervention(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded({"sentiment": "wrong_direction"}))
        self.assertFalse(q(r, "Q1")["needs_intervention"])
        self.assertFalse(q(r, "Q1")["needs_review"])

    def test_right_thinking_with_right_answer_but_missing_step_is_only_a_check(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded({"answer_correct": True}))
        self.assertFalse(q(r, "Q1")["needs_intervention"])
        self.assertTrue(any("marks lost on a step" in x for x in q(r, "Q1")["review_reasons"]))

    def test_prose_answer_right_direction_but_incomplete_is_not_flagged(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded(q2={"sentiment": "right_direction", "answer_correct": True}))
        self.assertFalse(q(r, "Q2")["needs_review"])

    def test_answer_correct_must_be_a_real_boolean(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded({"answer_correct": "no"}))
        self.assertIsNone(q(r, "Q1")["answer_correct"])
        self.assertFalse(q(r, "Q1")["needs_intervention"])

    def test_unknown_sentiment_falls_back_safely(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded({"sentiment": "ecstatic"}))
        self.assertEqual(q(r, "Q1")["sentiment"], "partly_right")
        self.assertFalse(q(r, "Q1")["needs_intervention"])

    def test_malformed_steps_are_cleaned(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded({"steps": ["text", {"ok": True}, {"work": "x = 6", "ok": 1}]}))
        self.assertEqual(q(r, "Q1")["steps"], [{"work": "x = 6", "ok": True, "note": ""}])


class TeacherNeeded(unittest.TestCase):
    def test_illegible_answer_goes_to_teacher(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(q1="[?]", q1kw={"legibility": "illegible"}), graded())
        self.assertTrue(q(r, "Q1")["needs_teacher"])
        self.assertEqual(q(r, "Q1")["sentiment"], "unreadable")
        self.assertFalse(q(r, "Q1")["needs_intervention"])
        self.assertTrue(q(r, "Q1")["review_reasons"][0].startswith("Couldn't read"))
        self.assertNotIn("Grader unsure", q(r, "Q1")["review_reasons"])
        self.assertEqual(r["needs_teacher"], 1)

    def test_mostly_unreadable_words_go_to_teacher(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(q1="[?] = [?] x 2400 [?]", q1kw={"legibility": "partly_unclear"}), graded())
        self.assertTrue(q(r, "Q1")["needs_teacher"])

    def test_a_few_unclear_words_only_need_a_check(self):
        rd = reading(q1="Profit = 15/100 x 2400 = [?] so SP = 2400 + 340 = 2740", q1kw={"legibility": "partly_unclear"})
        r = pipeline.reconcile_grades(RUBRIC, rd, graded())
        self.assertFalse(q(r, "Q1")["needs_teacher"])
        self.assertTrue(any("Hard-to-read" in x for x in q(r, "Q1")["review_reasons"]))

    def test_model_saying_unreadable_sends_it_to_teacher(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(), graded({"sentiment": "unreadable"}))
        self.assertTrue(q(r, "Q1")["needs_teacher"])

    def test_blank_answer_is_not_a_teacher_hand_off(self):
        r = pipeline.reconcile_grades(RUBRIC, reading(q2="", q2kw={"attempted": False}), graded())
        self.assertFalse(q(r, "Q2")["needs_teacher"])


class ClassLevel(unittest.TestCase):
    def students(self):
        slip = pipeline.reconcile_grades(RUBRIC, reading(), graded())
        unreadable = pipeline.reconcile_grades(RUBRIC, reading(q1="[?]", q1kw={"legibility": "illegible"}), graded())
        return [{"name": "Arjun", "grading": slip}, {"name": "Kunal", "grading": unreadable}]

    def test_stats_counts(self):
        st = pipeline.class_stats(RUBRIC, self.students())
        self.assertEqual(st["needs_teacher"], 1)
        self.assertEqual(st["sentiment"]["unreadable"], 1)
        self.assertEqual(st["sentiment"]["right_direction"], 1)  # Arjun's Q1; Kunal's unreadable Q1 is not counted
        self.assertEqual([(i["name"], i["question_id"]) for i in st["intervention"]], [("Arjun", "Q1")])

    def test_stats_accept_grades_from_before_sentiment_existed(self):
        g = pipeline.reconcile_grades(RUBRIC, reading(), graded())
        for x in g["questions"]:
            for k in ("sentiment", "sentiment_note", "answer_correct", "steps", "needs_teacher", "needs_intervention"):
                x.pop(k)
        st = pipeline.class_stats(RUBRIC, [{"name": "Old", "grading": g}])
        self.assertEqual((st["needs_teacher"], st["intervention"]), (0, []))

    def test_report_keeps_unreadable_answers_out_and_drops_unknown_names(self):
        seen = {}

        def fake(step, model, messages, ledger, **kw):
            seen["prompt"] = messages[0]["content"]
            return {"headline": "h", "misconceptions": [{"question_id": "Q1", "label": "x", "students": ["Arjun", "Ghost"]},
                                                        {"label": "y", "students": ["Nobody"]}],
                    "students_to_support": [{"name": "Ghost", "reason": "r"}, {"name": "Kunal", "reason": "r"}]}

        with mock.patch.object(pipeline, "chat_json", fake):
            rep = pipeline.class_report(RUBRIC, self.students(), Ledger())
        evidence = json.loads(seen["prompt"].split("WHAT EACH STUDENT GOT WRONG (missed rubric points and misconceptions):\n")[1].split("\n\nReturn JSON")[0])
        kunal_q1 = [e for e in evidence if e["student"] == "Kunal" and e["question_id"] == "Q1"]
        self.assertEqual(kunal_q1, [{"student": "Kunal", "question_id": "Q1", "note": "unreadable, the teacher is marking it"}])
        self.assertTrue(any(e.get("note", "").startswith("right thinking, wrong answer") for e in evidence if e["student"] == "Arjun"))
        self.assertEqual([m["students"] for m in rep["misconceptions"]], [["Arjun"]])
        self.assertEqual([x["name"] for x in rep["students_to_support"]], ["Kunal"])


class Translation(unittest.TestCase):
    def run_with(self, replies, language):
        calls = iter(replies)
        with mock.patch.object(pipeline, "chat_json", lambda *a, **k: {"text": next(calls)}):
            return pipeline.translate("Score: 5/10", language, Ledger())

    def test_retries_until_the_reply_is_in_the_right_script(self):
        self.assertEqual(self.run_with(["Score: 5/10", "Ank: 5/10", "अंक: 5/10"], "Hindi"), "अंक: 5/10")

    def test_language_without_script_check_retries_unchanged_text(self):
        self.assertEqual(self.run_with(["Score: 5/10", "Puntuación: 5/10"], "Spanish"), "Puntuación: 5/10")


class JsonAndImages(unittest.TestCase):
    def test_extract_json_handles_think_tags_fences_and_prose(self):
        self.assertEqual(extract_json('<think>hmm {"no": 1}</think>```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Sure! Here it is: {"a": {"b": 2}} hope that helps'), {"a": {"b": 2}})

    def test_garbage_upload_is_rejected(self):
        with self.assertRaises(ImageError):
            to_data_url(b"%PDF-1.4 not an image")

    def png(self, size, mode="RGBA", exif_rotate=None):
        img = Image.new(mode, size, (200, 10, 10, 128) if mode == "RGBA" else (200, 10, 10))
        buf = io.BytesIO()
        if exif_rotate:
            exif = Image.Exif()
            exif[0x0112] = exif_rotate
            img.save(buf, "JPEG", exif=exif)
        else:
            img.save(buf, "PNG")
        return buf.getvalue()

    def decode(self, url):
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))

    def test_transparent_png_is_converted_and_large_photo_downscaled(self):
        self.assertEqual(max(self.decode(to_data_url(self.png((4000, 3000)))).size), 1800)

    def test_phone_rotation_is_corrected(self):
        self.assertEqual(self.decode(to_data_url(self.png((300, 200), "RGB", exif_rotate=6))).size, (200, 300))


if __name__ == "__main__":
    unittest.main()
