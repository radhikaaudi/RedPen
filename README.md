# Redpen ✍️

**Redpen grades a stack of handwritten answer sheets in minutes — and shows its working.**
Photograph the sheets. Redpen reads the handwriting, marks every rubric point with the student's own words as evidence, flags anything it is unsure about, and tells you what the whole class misunderstood. The teacher stays in charge of every mark.

Built for the **Nebius x NVIDIA Global AI Hackathon** · Track: **Best Apps & Agents** · Runs on **NVIDIA Nemotron** via **Nebius Token Factory**.

- 🌐 **Live demo:** _add your deployed URL here_ — click **“Try it with a sample class”**, **“Try messy handwriting”** or **“Try a maths test”**, no sign-up needed
- 🎬 **Demo video:** _add your YouTube link here_
- 📄 License: [MIT](LICENSE)

![Redpen marking a student's answer sheet with evidence](docs/screenshots/4_student.png)

---

## The problem

A subject teacher often teaches several sections — easily over a hundred students. One unit test means hundreds of handwritten pages, marked in the evenings, by hand. Two things suffer:

1. **Feedback.** By sheet 120, “See me” is all a student gets. Students learn their mark, not their mistake.
2. **Teaching.** The pile of marked papers holds the most useful information a teacher has — *what the class misunderstood* — but nobody has time to tally it, so tomorrow's lesson is planned blind.

Typed-answer auto-graders don't help: most schools still test on paper.

## What Redpen does

| Step | What the teacher sees | Model |
|---|---|---|
| 1. Answer key → rubric | Paste the answer key in plain text; Redpen turns it into precise, checkable marking points | **Nemotron 3.5 Lightning** |
| 2. Read the sheets | Every sheet transcribed word-for-word *including the student's mistakes*; unreadable words highlighted | **Nemotron 3.5 Super VL** (vision) |
| 3. Grade with evidence | Each rubric point: ✓ / ½ / ✗, the exact quote that earned or lost it, a one-line reason, the misconception it reveals, and feedback to the student. **Step marking** for working: each line is checked, and a slip loses only that step. **Sentiment** — the direction of the student's thinking (right / partly right / wrong) — is judged separately from the final answer | **Nemotron 3 Ultra** (reasoning on) |
| 4. Teacher review | Unreadable answers go to the teacher ✋ instead of being guessed. Right thinking with a wrong answer is sent to the teacher for intervention 🧭. Low-confidence or hard-to-read answers are flagged ⚑. One click adjusts any mark; totals update instantly | — (pure code) |
| 5. Class insights | Shared misconceptions grouped across students, per-question breakdown, who needs support, and a 3-step reteach plan with 10-minute classroom activities | **Nemotron 3 Ultra** |
| 6. Parents | Printable feedback slips, translated into Hindi, Tamil, Bengali, Marathi, Spanish or French | **Nemotron 3 Ultra** (reasoning off) |

The **Model ledger** (top right) shows every Nemotron call: model, step, tokens, latency and cost.

| Results | Class insights |
|---|---|
| ![Results table](docs/screenshots/3_results.png) | ![Class insights](docs/screenshots/5_insights.png) |

## Measured results

Two sample sets, same 8 students and answers: **neat** handwriting, and **messy** handwriting photographed badly (uneven, cramped letters, scribbled-out words, blur, shadow, skew — one sheet near-illegible on purpose). Full reports: [`eval/RESULTS.md`](eval/RESULTS.md), [`eval/RESULTS_messy.md`](eval/RESULTS_messy.md).

| Metric | Neat (3 runs, 96 answers) | Messy (2 runs, 64 answers) |
|---|---|---|
| Handwriting reading accuracy (word-level) | **99.2%** | **90.9%** |
| Exact agreement with reference marks, per question | **83.3%** | **82.8%** |
| Within ½ mark of reference marks | **100%** | **96.9%** |
| Average error on a student's total (out of 10) | **0.21 marks** | **0.22 marks** |
| Answers off by more than ½ mark | 0 | 2 — **both flagged for teacher review** |
| Cost per sheet (read + grade) | ≈ $0.01 | ≈ $0.01 |

On messy sheets, grading stays almost as accurate as on neat ones because marks depend on meaning, not exact wording — and the only answers Redpen got meaningfully wrong were ones it had already flagged. **Read the limitations below** — these sheets are synthetic.

| Messy sheet: unclear handwriting flagged, transcription next to the photo |
|---|
| ![Messy handwriting](docs/screenshots/messy_3_zoya.png) |

## How it works

![Redpen architecture: the teacher's browser, a stateless FastAPI server, and three NVIDIA Nemotron models on Nebius Token Factory](static/architecture.svg)

Three parts, each with one job:

- **The teacher's browser** holds the whole session: rubric, transcriptions, grades and the cost ledger. When the teacher changes a mark, totals are recomputed right there.
- **The Redpen server** (FastAPI) is stateless. It fixes photo rotation and size in memory, sends each step to the right model, and then **checks the model's work in Python**. Marks are clamped to the rubric, any evidence quote that isn't in the student's transcription is dropped, totals are computed, and unsure answers are flagged. The API key never leaves the server.
- **Nebius Token Factory** serves three NVIDIA Nemotron models: Lightning (rubric), Super VL (reading handwriting) and Ultra (grading, class insights, translation).

A PNG version for slides is at [`docs/architecture.png`](docs/architecture.png).

### Reading handwriting: OCR that understands the page

Redpen's OCR is **NVIDIA Nemotron 3.5 Super VL**, the vision model Nebius Token Factory offers for document understanding. There is no separate OCR engine. Plain OCR gives you lines of text. Super VL returns, in **one call for all of a student's pages**, structured JSON per question:

| Plain OCR | Super VL in Redpen |
|---|---|
| Lines of text in reading order | Each answer matched to the question number the student wrote |
| Plain text out | Structured JSON, word-for-word, spelling mistakes kept — the grade depends on them |
| Crossed-out words read as text | Crossed-out words left out |
| Unreadable words guessed, at most with a confidence score | Unreadable words become `[?]`, best guesses listed in `unclear_words` |
| No signal for the teacher | A `legibility` rating per answer — unclear answers are flagged for review |
| Drawings ignored | Diagrams and working described |

```json
{ "question_id": "Q1", "attempted": true,
  "transcription": "Plants make food using sunlight. They take in oxygen and water and give out carbon dioxide.",
  "diagram": null, "legibility": "clear", "unclear_words": [] }
```

Measured: **99.2%** word accuracy on neat sheets, **90.9%** on messy ones, at about **$0.001 and ~5 s per sheet**. The prompt is `READ_PROMPT` in [`redpen/pipeline.py`](redpen/pipeline.py).

### Marking like a teacher: step marking, sentiment, teacher intervention

Click **Try a maths test** to see all three. The sample is 5 students and 3 questions (profit and loss, a linear equation, area of a circle); it is in [`samples/maths/`](samples/maths/).

- **Step marking.** For an answer with working, Ultra lists each line and marks it ✓ or ✗. A slip loses only the marks for that step and the values that depend on it. Later steps that correctly use the wrong value still earn their method mark (error carried forward). Arjun wrote 15% of 2400 = 340, then 2400 + 340 = 2740: he gets **2/4, not 0**. A different valid method (Riya: 115% of 2400 = 2760) earns full marks. A teacher's own step-marking notes in the answer key are followed.
- **Sentiment = the direction of the student's thinking.** Every answer gets *right direction / partly right / wrong direction*, judged apart from the final answer, plus whether the final answer is correct. **When the thinking was in the right direction but the answer came out wrong, Python asks the teacher to intervene 🧭**: a quick word fixes a slip faster than a red cross. In the maths sample, Arjun (15% of 2400 = 340) and Riya (22 × 7 = 144) are sent for intervention; Arjun's circumference-for-area answer is the wrong direction, so it isn't. Class insights list every "right thinking, wrong answer" student.
- **Teacher needed.** If an answer is too unreadable to mark (illegible, mostly `[?]`, or Ultra says it can't tell what the student did), Python hands it to the teacher ✋ rather than letting a guess stand. The class report leaves it out of the evidence until the teacher has marked it.

| Step marking | Unreadable → teacher |
|---|---|
| ![Step marking](docs/screenshots/maths_1_step_marking.png) | ![Teacher needed](docs/screenshots/maths_2_teacher_needed.png) |

On the maths sample (3 runs), Redpen marked 14 of the 15 answers itself and handed Kunal's unreadable one to the teacher every time. It matched the hand-set reference marks on 12–13 of those 14 answers, and every difference was 1 mark or less. Most differences were "3x = 18, x = 6" with the division step not written, and Redpen flagged those for the teacher. Once, Sana's sign-error answer got 0 instead of 1, where error carried forward is a judgement call; that one was not flagged. This is a 5-student smoke test, not a benchmark. Adding these checks did not change science grading: a fresh neat-set run had 100% of answers within ½ mark.

### Which model does what, and why

| Model (Token Factory ID) | Job | Why this model |
|---|---|---|
| `nvidia/Nemotron-3.5-Super-VL` | Read handwriting | The vision model. Asked to transcribe *verbatim* — never correct spelling or complete answers, because grading must judge what is really on the page. Reasoning off: this is perception, not judgement. |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | Grade; find class misconceptions; translate feedback for parents | Grading is the step where errors cost a student marks, so it gets the strongest reasoning model with thinking enabled. Grouping “plants breathe in CO₂” and “plants take in oxygen” as related errors also needs real reasoning. Translation runs with thinking off (~1 s, < $0.001 per slip): we started on Lightning, but its Tamil and Bengali came out garbled in testing, and a note to parents has to be right. |
| `nvidia/Nemotron-3_5-Lightning` | Structure rubric | Fast and cheap (~$0.0002 per call) for a well-defined text task, so the app stays responsive and credits go to grading. |

Reasoning is switched per call with `chat_template_kwargs: {"enable_thinking": ...}`; all calls use JSON mode.

### Where Nebius Token Factory accelerated our workflow

- **No GPUs, no model hosting.** Three NVIDIA Nemotron models (a vision model, a fast model and a 550B reasoning model) are served by Token Factory, so we spent our time on prompts, checks and the teacher's experience instead of infrastructure.
- **One API for every model.** Token Factory is OpenAI-compatible: the standard `openai` Python client with a different `base_url` ([`redpen/config.py`](redpen/config.py)). Trying a different model for a step is a one-line change. That is how we moved translation from Lightning to Ultra in minutes when Lightning's Tamil and Bengali came out garbled.
- **The right model for each job.** Having Super VL, Lightning and Ultra behind one key let us route each step to the cheapest model that does it well: the expensive reasoning model is used only where judgement matters.
- **Reasoning on or off per call.** `chat_template_kwargs.enable_thinking` let us use Ultra with thinking for grading and without thinking for fast translation, on the same model.
- **Setup check in seconds.** [`check_setup.py`](check_setup.py) lists the available models with `GET /v1/models` and confirms the exact Nemotron model IDs before the app runs.
- **Parallel grading.** Three sheets are read and graded at once in the app and four at once in the evaluation, with no rate-limit tuning needed for a class-sized batch.
- **Transparent cost.** Per-token pricing made it easy to show the cost of every call in the app's Model ledger (about 1–2 cents per sheet) and to run our whole evaluation for well under a dollar.

Nebius services used: **Nebius Token Factory** (inference for all three NVIDIA Nemotron models). The app is a single container ([`Dockerfile`](Dockerfile)), ready for Nebius Serverless Endpoints or any container host.

### Design decisions that make it trustworthy

- **Models judge, code counts.** Totals, clamping to the rubric, half-mark rounding and every class statistic are computed in Python ([`redpen/pipeline.py`](redpen/pipeline.py)). A model can never mis-add a student's marks.
- **Evidence is verified.** If Ultra quotes “evidence” that isn't in the transcription, Redpen drops the quote rather than show invented student text.
- **Uncertainty is surfaced.** Answers with unclear handwriting or grader confidence < 0.7 are flagged for the teacher; unreadable words are highlighted in the transcription. Answers that can't be read at all are handed to the teacher to mark — Python decides this, not the model.
- **The teacher has the last word.** Any mark can be changed in half-mark steps; changed marks are labelled and feed into the class insights.
- **Robust I/O.** Phone photos are rotation-corrected and downscaled; malformed model JSON is retried; failed sheets can be retried individually.

## Run it locally

Requirements: Python 3.11+ and a [Nebius Token Factory](https://tokenfactory.nebius.com) API key.

```bash
git clone <this repo> && cd redpen
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then paste your key into .env
python check_setup.py         # confirms the key and the three Nemotron models
uvicorn app:app --reload      # open http://localhost:8000
```

Click **Try it with a sample class**, then **Grade all**.

Run the offline tests (no API key needed; they cover marking, step marking, sentiment and teacher intervention, teacher hand-off and image handling): `python -m unittest discover tests`

Run the evaluation: `python eval/evaluate.py --runs 3` and `python eval/evaluate.py --set messy --runs 2` (≈ $0.25 and $0.17 in Token Factory credits).

Test it on **your own handwriting**: write the four sample questions' answers on paper, photograph the page, click *Try it with a sample class*, remove a student, and drop your photo in.

## Deploy

The app is a single container ([`Dockerfile`](Dockerfile)); it needs one secret, `NEBIUS_API_KEY`.

```bash
docker build -t redpen .
docker run -p 8000:8000 -e NEBIUS_API_KEY=... redpen
```

It deploys as-is to any container host (Nebius Serverless Endpoints, Render, Railway, Fly.io). The public demo has a per-IP hourly request limit (`REDPEN_MAX_REQUESTS_PER_HOUR`, default 120) to protect credits.

## Project layout

```
app.py                 FastAPI routes + demo rate limiting
redpen/pipeline.py     rubric → read → grade → reconcile → class report → translate (all prompts live here)
redpen/llm.py          Token Factory client wrapper, JSON parsing/retry, per-call cost ledger
redpen/images.py       photo rotation fix + downscaling
static/                single-page frontend (HTML + Tailwind + vanilla JS, no build step)
samples/               sample answer key, 8 neat + 8 messy answer sheets, reference marks
samples/maths/         maths test: step marking, right-thinking-wrong-answer, an unreadable answer
scripts/make_samples.py  regenerates the sample sheets (make_maths_samples.py for the maths set)
eval/evaluate.py       accuracy / cost / latency evaluation → eval/RESULTS.md
check_setup.py         verifies API key and model availability
```

## Limitations (honest list)

- **The evaluation set is synthetic.** The 8 sample sheets are rendered with handwriting fonts — cleaner than real student handwriting — and the reference marks were set by the project author, not an independent teacher. Real-world reading accuracy will be lower. Next step: evaluate on real, consented, anonymised sheets marked by two teachers.
- **On near-illegible handwriting the vision model can “fill in” a plausible answer.** On our deliberately unreadable sample sheet, Super VL sometimes returned a cleaner, textbook-like sentence instead of the student's actual words (70% word accuracy on that sheet). Prompting it to prefer `[?]` over guesses did not fully stop this. Redpen's defence: every hard-to-read answer is flagged “compare the transcription with the photo”, and the photo is shown beside the transcription. Next step: a second, independent reading pass and flagging answers whose two readings disagree.
- **Text answers only, for now.** Super VL describes diagrams and working, but the rubric does not yet award marks for drawn diagrams (e.g. labelling a cell).
- **English answers.** Feedback can be translated, but sheets written in Hindi or other scripts have not been tested.
- **Not for high-stakes exams.** Redpen is designed for classroom tests where a teacher reviews flagged answers — not for board exams without human checking.
- **Privacy.** Sheet images are sent to Nebius Token Factory for inference and are not stored by Redpen. For school deployments, use a zero-data-retention endpoint where Token Factory offers one.

## Built with

NVIDIA Nemotron 3.5 Super VL · NVIDIA Nemotron 3 Ultra · NVIDIA Nemotron 3.5 Lightning · Nebius Token Factory (OpenAI-compatible API) · Python · FastAPI · Pillow · Tailwind CSS

## License

[MIT](LICENSE)
