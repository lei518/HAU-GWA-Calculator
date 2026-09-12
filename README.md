# HAU Grade & GWA Planner

A web app for Holy Angel University students to track subject grades, compute
their GWA, and work out exactly what scores they still need to hit a target
grade.

Enter your activities and major exams as you get them back. The app computes
your Class Standing Average, Major Examination Average, Computed Average,
Transmuted Value, and Current Grade using the HAU College Grading System, then
an AI assistant answers questions like "Can I still get 1.00?" with concrete
numbers rather than encouragement.

## What it does

**Per-subject grade tracking.** Each subject holds Class Standing assessments
(activities, quizzes, seatwork) and one Major Examination per grading period —
Prelim, Midterm, and Final. Scores are entered against their own highest
possible score, so a 38/40 quiz and a 45/50 exam are handled correctly without
manual conversion.

**Configurable weighting.** Subjects differ in how Class Standing and Major
Examinations split the final grade. Pick 70/30, 60/40, or a custom split when
you create the subject, and change it later without losing any recorded score.
The two shares are validated to total 100, because a 70/40 typo would otherwise
produce a computed average above 100% and hand out a grade nobody earned.

**Target-grade planning.** Choose a target and the app solves for what it takes.
It reports the minimum score needed on your next activity and on your remaining
exams, separately, and states plainly that those are *alternative routes* rather
than a combined to-do list — each assumes the other component holds steady, so
doing both minimums at once falls short.

**AI assistant.** A Gemini-backed assistant scoped to one subject at a time. It
never calculates anything: every figure it quotes is computed by the grading
engine and passed to it as structured context, so its answers cannot drift from
what the app itself shows.

**GWA across subjects.** A unit-weighted general weighted average, with Home
showing overall standing and the three subjects you opened most recently.

## Grading model

    Performance items -> CSA / MEA -> Computed Average -> Transmuted Value -> Current Grade

- **Class Standing Average** — total points earned over total possible points.
- **Major Examination Average** — the mean of each graded period's percentage.
  Prelim, Midterm, and Final each count as one equal share, so a Final out of
  100 does not outweigh a Prelim out of 50.
- **Computed Average** — the two averages combined using the subject's split.
- **Transmuted Value** — the Computed Average mapped onto HAU's scale using the
  subject's passing average.
- **Current Grade** — 1.00 through 5.00, from the transmuted value.

Unscored items are excluded from the current average rather than counted as
zero, so an untaken final exam does not drag the grade down before it is sat.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, Django 5.2 |
| Frontend | Django templates, HTMX 2.0, hand-written CSS, vanilla JavaScript |
| AI | Google Gemini via `google-genai` |
| Database | SQLite in development, PostgreSQL in production via `psycopg` |
| Server | Gunicorn |
| Deployment | Render (`render.yaml`), Procfile-compatible |

No build step, no bundler, no CSS framework, and no frontend framework. HTMX
handles partial page updates — adding an assessment, recalculating a target,
asking the assistant — so the server keeps rendering HTML and there is no
client-side state to keep in sync with it.

## Project layout

    config/              Django settings, root URLs, WSGI
    subjects/
      models.py          Subject, ClassStandingAssessment, MajorExam
      grading.py         Pure grading engine - no Django imports
      ai_assistant.py    Context building, prompt, Gemini client
      views.py           Dashboard, subject CRUD, assistant endpoint
      forms.py           Subject form and weighting validation
      tests.py           144 tests
    templates/           Base layout, dashboard, subject pages, auth
    static/css/app.css   All styles
    static/js/           Assistant modal, sidebar, form helpers

`grading.py` deliberately imports nothing from Django. It works on plain objects
with `score`, `highest_possible_score`, and `grading_period`, which keeps the
maths testable on its own and makes it obvious that the AI layer sits on top of
the engine rather than beside it.

## Running locally

    python -m venv .venv
    .venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py runserver

Open http://127.0.0.1:8000/

### Environment

Create a `.env` file in the project root:

    GEMINI_API_KEY=your-key-here
    GEMINI_MODEL=gemini-3.1-flash-lite     # optional
    DJANGO_SECRET_KEY=...                  # optional in development
    DJANGO_DEBUG=True
    DATABASE_URL=...                       # optional; PostgreSQL when set

Without `GEMINI_API_KEY` everything works except the assistant, which reports
that it is unavailable instead of failing silently.

## Tests

    python manage.py test

144 tests. Most cover the grading engine and the assistant's context: target
plans are verified by feeding the recommended score back through the real
`calculate_grade()` and asserting the target is actually reached, rather than
restating the formula in the test. Others guard failures that render wrong
without raising, such as a stylesheet referencing an undefined custom property.

## Deployment

`render.yaml` provisions a web service and a PostgreSQL database, sets
`DJANGO_DEBUG=False`, and generates a secret key. `GEMINI_API_KEY` must be added
manually. The Procfile makes the project work on any Gunicorn host.

## Notes and limitations

- Three grading periods (Prelim, Midterm, Final) are assumed throughout.
- Major exams are averaged as equal shares per period. If a department totals
  raw exam points instead, `major_exam_average()` in `grading.py` is the single
  place to change, and `EqualPeriodWeightTests` documents both readings.
- Assistant output is shaped by a prompt. Figures that must never drift — the
  status line and the tip — are built in Python and quoted verbatim rather than
  left to the model.