# Devpost submission kit for Redpen

Copy these into the Devpost “Enter a Submission” form. Replace everything in ⟨angle brackets⟩.
**Deadline: Friday Oct 30, 2026, 10:00 AM PT (10:30 PM IST).** Submit a few hours early; you cannot edit afterwards.

---

## Checklist

- [ ] Public GitHub repo, MIT license visible in the repo's About section
- [ ] App deployed; demo URL works in an incognito window (“Try it with a sample class” → “Grade all”)
- [ ] `NEBIUS_API_KEY` set as a secret on the host (never in the repo)
- [ ] Demo video < 3 min, **public** on YouTube, says “NVIDIA Nemotron” and “Nebius Token Factory” out loud
- [ ] README demo + video links filled in
- [ ] Track selected: **Best Apps & Agents**
- [ ] Feedback section filled (required, and eligible for the Most Valuable Feedback prize)
- [ ] Optional: replace one synthetic sheet in the video with a real handwritten page (yours), to show it works on real handwriting

---

## Project name
Redpen

## Tagline (one line)
Photograph a stack of handwritten answer sheets — Redpen marks every point with evidence and tells you what your class misunderstood.

## Track
Best Apps & Agents

## Built with
nvidia-nemotron, nemotron-3-ultra, nemotron-3.5-super-vl, nemotron-3.5-lightning, nebius-token-factory, python, fastapi, pillow, tailwindcss, javascript

---

## Project description

### Inspiration
Teachers in most schools still test on paper. A subject teacher with several sections can face hundreds of handwritten pages after a single unit test — marked at night, by hand. By the hundredth sheet, students get a number and a tick, not an explanation. Worse, the most useful information in that pile — *what the class misunderstood* — is never tallied, so tomorrow's lesson is planned blind. We wanted a tool that gives that time back without taking the teacher's judgement away.

### What it does
Redpen grades handwritten answer sheets end to end:
1. **Answer key → rubric.** The teacher pastes their answer key in plain text. Redpen turns it into precise, checkable marking points.
2. **Reads the handwriting.** Each photographed sheet is transcribed word for word — *including the student's mistakes*, because you can't grade what you've auto-corrected. Unreadable words are highlighted.
3. **Grades with evidence.** Every rubric point gets ✓ / ½ / ✗, the exact quote from the student's answer that earned or lost the mark, a one-line reason, the misconception it reveals, and feedback for the student.
4. **Asks for help when unsure.** Answers with messy handwriting or low grader confidence are flagged. The teacher can change any mark with one click.
5. **Class insights.** Redpen groups shared misconceptions across the class (“2 students think rusting needs only water”), shows how each question went, lists who needs support, and writes a 3-step reteach plan with 10-minute classroom activities.
6. **Feedback slips for parents.** Printable per-student slips, translatable into Hindi, Tamil, Bengali, Marathi, Spanish or French.

A **Model ledger** shows every model call: which Nemotron model, which step, tokens, time and cost. Grading costs about **one US cent per sheet**.

### How we built it
Redpen is a FastAPI backend with a single-page frontend. Every AI step runs on **NVIDIA Nemotron models served by Nebius Token Factory** through its OpenAI-compatible API. Each model has one job:
- **Nemotron 3.5 Super VL** (vision) reads the sheets. Reasoning is off — this is perception.
- **Nemotron 3 Ultra** with reasoning on does the grading and the class-level misconception analysis, the two steps where judgement matters most. With reasoning off, it also translates feedback slips for parents.
- **Nemotron 3.5 Lightning** structures the rubric, keeping the app fast and the credits for grading.

We switch reasoning per call with `chat_template_kwargs.enable_thinking` and use JSON mode everywhere. A key design rule: **models judge, code counts.** Totals, clamping marks to the rubric and every class statistic are computed in Python, and any “evidence” quote that doesn't actually appear in the student's transcription is discarded.

We built an evaluation harness (`eval/evaluate.py`) with two sets of the same 8 students' answers. One set is neat. The other is messy handwriting photographed badly: cramped, uneven letters, scribbles, blur, shadow and skew, with one sheet near-illegible on purpose.
- **Neat sheets** (96 graded answers): **99.2% reading accuracy, 83% exact agreement with reference marks, 100% within half a mark.**
- **Messy sheets** (64 graded answers): **90.9% reading accuracy, 83% exact agreement, 97% within half a mark.** The only two answers that were off by more than half a mark were both already flagged for the teacher.

Each sheet takes about 11 s and costs about $0.01.

### Challenges we ran into
- **Faithful transcription.** Vision models want to “help” by fixing spelling or finishing sentences, which would hide exactly the errors a teacher needs to see. Prompting for verbatim transcription with crossed-out text removed took several iterations.
- **Reasoning output.** With reasoning enabled and a tight token limit, Lightning's thinking leaked into the answer field. We now control reasoning explicitly for every call.
- **Numbers in AI-written text.** Ultra's first class report said “5/6 students” in an 8-student class. We now pass exact statistics and tell it to copy numbers, never compute them.
- **Trust.** A grader that is confidently wrong is worse than none, so we added confidence flags, evidence verification and one-click overrides.

### Accomplishments that we're proud of
- An end-to-end product a teacher can actually use, from photo to parent slip — not a demo script.
- Measured accuracy, cost and latency, with every disagreement listed in `eval/RESULTS.md`.
- Clear model routing: the expensive reasoning model is used only where judgement matters.

### What we learned
- Splitting the work across specialised models (vision, fast, reasoning) was cheaper *and* more accurate than asking one model to read and grade at once.
- Showing evidence for every mark changes the experience from “trust the AI” to “check the AI in five seconds”.

### What's next for Redpen
- Evaluate on real, consented, anonymised sheets double-marked by teachers.
- Marks for diagrams (labelled cell, circuit, graph), and answers written in Hindi and other scripts.
- Bulk scanning: one PDF of a whole class, automatically split by student.
- Track each student's misconceptions across tests to show learning over time.

### Limitations (we'd rather you hear it from us)
The evaluation sheets are synthetic: they're generated from handwriting fonts, and we set the reference marks ourselves. On near-illegible handwriting, the vision model can "fill in" a plausible textbook sentence instead of the student's actual words. On our deliberately unreadable sheet, its word accuracy was 70%. Redpen's defence is to flag every hard-to-read answer and show the photo beside the transcription. A second, independent reading pass is our next step. Redpen is meant for classroom tests with a teacher in the loop, not for high-stakes exams.

### Is this a new project?
Yes. Redpen was built from scratch during the submission period.

---

## Feedback on Nebius Token Factory and NVIDIA models (required field)

> Only include what you actually experienced. These are drawn from building Redpen; edit them to match your own experience.

**What worked well**
- The OpenAI-compatible API meant zero new SDKs: the standard `openai` Python client with a different `base_url`. Moving between the three Nemotron models was a one-line change.
- `GET /v1/models` made it easy to write a setup checker that confirms the exact model IDs before the app runs.
- Nemotron 3.5 Super VL transcribed handwriting-style sheets with about 99% word accuracy at roughly 2–3 s per page.
- Nemotron 3 Ultra returns its reasoning separately from the answer, so we get clean JSON plus a reasoning trace we could audit.
- JSON mode (`response_format: json_object`) worked reliably across all three models.
- Per-model pricing let us show cost per sheet in the app (≈ $0.01), which matters for schools.

**What could be better**
- **Reasoning control is hard to discover.** We found the `chat_template_kwargs.enable_thinking` toggle by experiment. A per-model table in the docs (“reasoning on by default? how to switch it off? where does reasoning appear?”) would save time.
- **Truncated reasoning leaks into `content`.** With reasoning on and a small `max_tokens`, Lightning returned its unfinished thinking in the `content` field instead of the reasoning field. Returning it in the reasoning field, with an empty `content` and a clear `finish_reason`, would be safer for apps that parse `content`.
- **Deprecation timing.** Nemotron 3 Nano and Super leave serverless on Nov 9, before judging (Dec 1–15). We switched to the 3.5 models early, but hackathon participants could easily miss this. A banner on the hackathon page would help.
- **Cost in the response.** Returning the request's cost (or price per token) in response headers would make cost dashboards like our Model ledger trivial, with no hard-coded price table.
- **Indian-language output from Lightning.** Nemotron 3.5 Lightning's Hindi was sometimes romanised and its Tamil and Bengali were often garbled (mixed scripts, invented words), and it once returned the English unchanged. Nemotron 3 Ultra translated the same text well, so we moved translation to Ultra. A published per-language quality table would help builders pick the right model for multilingual features.
- **Vision limits.** Please document the maximum images per request and the recommended image resolution for Super VL.

⟨Add one or two points from your own experience: sign-up, billing, credits, docs, Discord support.⟩

---

## Demo video script (target 2:45; judges stop at 3:00)

Record your screen at 1080p with a voice-over. Hook in the first 30 s, then show, don't explain.

**0:00–0:20 — Hook**
On screen: a real pile of answer sheets, or the sample sheets.
> “This is one unit test for one section — and a teacher has five sections. Marking it takes an evening, and students still get just a number. This is Redpen.”

**0:20–0:45 — Setup**
Click *Try it with a sample class*. The answer key fills in and the rubric appears.
> “I paste my answer key in plain English. NVIDIA Nemotron 3.5 Lightning, running on Nebius Token Factory, turns it into precise marking points.”

**0:45–1:15 — The aha: grading with evidence**
Click *Grade all*. Status chips move from Reading · Super VL to Grading · Ultra. Open Meera's sheet.
> “Nemotron Super VL reads each sheet exactly as written, mistakes included. Then Nemotron 3 Ultra reasons through every rubric point. Look: Meera wrote ‘plants take in oxygen’. Redpen quotes her words, marks the point wrong, and names the misconception: she's confusing photosynthesis with respiration.”

**1:15–1:40 — Teacher in control**
Show a flagged answer, the highlighted unclear word, and a click on + to adjust a mark; the total updates.
> “When handwriting is unclear or the grader is unsure, Redpen flags it for me. I can change any mark in one click. Totals are always computed in code, never by the AI.”

**1:40–2:15 — Class insights**
Click *Generate class insights*. Scroll through the misconceptions, the reteach plan and the students to support.
> “Now the part no teacher has time for. Ultra finds patterns across the whole class: two students think rust needs only water, and the lightning question was the weakest. Here is tomorrow's reteach plan, with ten-minute activities.”

**2:15–2:35 — Parents and cost**
Translate a slip into Hindi, then open the Model ledger.
> “Feedback slips can go home in Hindi. And the Model ledger shows every Nemotron call: about one cent per sheet.”

**2:35–2:50 — Proof and close**
Flash Zoya's messy sheet from *Try messy handwriting*, then the README results table.
> “Even on messy, badly photographed handwriting, Redpen lands within half a mark on 97% of answers — and the ones it got wrong, it had already flagged for me. Redpen: your red pen, now with a teaching assistant. Built with NVIDIA Nemotron on Nebius Token Factory.”
