from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from . import ai_assistant
from django.utils import timezone

from .forms import SubjectForm, preset_for

# How many subjects Home shows under "Recently viewed". Home is meant to
# fit one screen, so this is a layout constraint as much as a limit.
RECENT_SUBJECT_COUNT = 3
from .grading import build_target_plan, calculate_grade
from .models import ClassStandingAssessment, FINAL, GRADING_PERIOD_CHOICES, MajorExam, MIDTERM, PRELIM, Subject

PERIODS = [PRELIM, MIDTERM, FINAL]
PERIOD_LABELS = dict(GRADING_PERIOD_CHOICES)
PERIOD_PREFIX = {PRELIM: "prelim", MIDTERM: "midterm", FINAL: "final"}

def _decimal_or_none(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None

def _subject_context(subject):
    cs_assessments = list(subject.class_standing_assessments.order_by("id"))
    major_exams = {e.grading_period: e for e in subject.major_exams.all()}
    major_exam_list = list(major_exams.values())
    cs_by_period = {p: [a for a in cs_assessments if a.grading_period == p] for p in PERIODS}
    result = calculate_grade(subject, cs_assessments, major_exam_list)

    return {
        "subject": subject,
        "result": result,
        "periods": [
            {
                "code": p,
                "label": PERIOD_LABELS[p],
                "cs_assessments": cs_by_period[p],
                "major_exam": major_exams.get(p),
            }
            for p in PERIODS
        ],
    }

def _subject_or_redirect(request, pk):
    """Look up a subject owned by the current user.

    Returns (subject, None) when found, or (None, response) with a graceful
    redirect back to the dashboard when the subject doesn't exist (e.g. it was
    already deleted, in another tab or by a stale/bookmarked link) — this
    keeps a deleted subject's old URL from surfacing an unhandled-looking
    error page.
    """
    subject = Subject.objects.filter(pk=pk, student=request.user).first()
    if subject is not None:
        return subject, None
    messages.error(request, "That subject could not be found. It may have already been deleted.")
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("subjects:dashboard")
        return None, response
    return None, redirect("subjects:dashboard")

def _dashboard_rows(user):
    subjects = Subject.objects.filter(student=user).prefetch_related(
        "class_standing_assessments", "major_exams")
    rows, total_units, weighted = [], Decimal("0"), Decimal("0")
    all_units = Decimal("0")
    for subject in subjects:
        result = calculate_grade(
            subject, list(subject.class_standing_assessments.all()), list(subject.major_exams.all()))
        rows.append((subject, result))
        all_units += subject.units
        if result.current_grade not in {"5.00", "6.00", "8.00", "9.00"}:
            total_units += subject.units
            weighted += Decimal(result.current_grade) * subject.units
    gwa = weighted / total_units if total_units else None
    return rows, gwa, all_units

@login_required
def dashboard(request):
    """Home: overall standing plus the subjects most recently opened.

    The full, alphabetised roster lives on the subjects page. Home answers
    "what was I just working on", which is a different question from "show
    me everything", so the two lists are not duplicates of each other.
    """
    rows, gwa, all_units = _dashboard_rows(request.user)
    opened = [row for row in rows if row[0].last_viewed_at is not None]
    opened.sort(key=lambda row: row[0].last_viewed_at, reverse=True)
    return render(request, "dashboard.html", {
        "rows": opened[:RECENT_SUBJECT_COUNT],
        "has_any_subject": bool(rows),
        "gwa": gwa,
        "total_units": all_units,
        "subject_count": len(rows),
        "ai_subjects": sorted((row[0] for row in rows), key=lambda s: s.name.lower()),
    })

@login_required
def subject_list(request):
    """Every subject, A to Z -- the complete roster."""
    rows, gwa, all_units = _dashboard_rows(request.user)
    rows.sort(key=lambda row: row[0].name.lower())
    return render(request, "subjects/list.html", {
        "rows": rows, "gwa": gwa, "total_units": all_units,
        "ai_subjects": [row[0] for row in rows],
    })

@login_required
def subject_delete(request, pk):
    subject = get_object_or_404(Subject, pk=pk, student=request.user)
    if request.method != "POST":
        return redirect("subjects:dashboard")
    subject.delete()
    if request.headers.get("HX-Request") == "true":
        rows, gwa, all_units = _dashboard_rows(request.user)
        return render(request, "subjects/_subjects_section.html",
                      {"rows": rows, "gwa": gwa, "total_units": all_units})
    return redirect("subjects:dashboard")

@login_required
def subject_create(request):
    form = SubjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            subject = form.save(commit=False)
            subject.student = request.user
            subject.save()

            for period in PERIODS:
                prefix = PERIOD_PREFIX[period]
                names = request.POST.getlist(f"{prefix}_name")
                scores = request.POST.getlist(f"{prefix}_score")
                hps_list = request.POST.getlist(f"{prefix}_hps")
                for name, score, hps in zip(names, scores, hps_list):
                    if not name.strip():
                        continue
                    ClassStandingAssessment.objects.create(
                        subject=subject, name=name.strip(), grading_period=period,
                        score=_decimal_or_none(score),
                        highest_possible_score=_decimal_or_none(hps) or Decimal("100"))

                MajorExam.objects.create(
                    subject=subject, grading_period=period,
                    score=_decimal_or_none(request.POST.get(f"{prefix}_exam_score")),
                    highest_possible_score=_decimal_or_none(
                        request.POST.get(f"{prefix}_exam_hps")) or Decimal("100"))
        messages.success(request, f'"{subject.name}" was added.')
        return redirect("subjects:dashboard")
    terms = [{"code": p, "label": PERIOD_LABELS[p], "prefix": PERIOD_PREFIX[p]} for p in PERIODS]
    return render(request, "subjects/form.html", {"form": form, "terms": terms})

@login_required
def subject_update(request, pk):
    """Edit a subject's own settings (name, units, passing average, and the
    Class Standing / Major Examination split) without touching any recorded
    assessment or exam score.

    This exists because the weighting is a per-subject property that a
    student often only learns partway through the term. Without an edit
    path the only way to correct it is to delete the subject and re-enter
    every activity, which loses real data over a settings mistake."""
    subject, response = _subject_or_redirect(request, pk)
    if subject is None:
        return response

    if request.method == "POST":
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
            messages.success(request, f'"{subject.name}" was updated.')
            return redirect("subjects:subject_detail", pk=subject.pk)
    else:
        form = SubjectForm(instance=subject, initial={
            "share_preset": preset_for(subject.class_standing_percent_share,
                                       subject.major_exam_percent_share),
        })
    return render(request, "subjects/edit.html", {"form": form, "subject": subject})

@login_required
def subject_detail(request, pk):
    subject, response = _subject_or_redirect(request, pk)
    if response is not None:
        return response
    # Stamp the visit so Home can order by what was opened most recently.
    # update() avoids a full save (and any auto_now fields firing) and does
    # not disturb the in-memory instance used to render the page.
    Subject.objects.filter(pk=subject.pk).update(last_viewed_at=timezone.now())
    context = _subject_context(subject)
    context["target_grades"] = "1.00,1.25,1.50,1.75,2.00,2.25,2.50,2.75,3.00".split(",")
    return render(request, "subjects/detail.html", context)

@login_required
def class_standing_add(request, pk):
    subject, response = _subject_or_redirect(request, pk)
    if response is not None:
        return response
    if request.method != "POST":
        return redirect("subjects:subject_detail", pk)
    period = request.POST.get("grading_period")
    if period not in PERIODS:
        return HttpResponseBadRequest("Invalid grading period.")
    name = request.POST.get("name", "").strip()
    if name:
        ClassStandingAssessment.objects.create(
            subject=subject, name=name, grading_period=period,
            score=_decimal_or_none(request.POST.get("score")),
            highest_possible_score=_decimal_or_none(
                request.POST.get("highest_possible_score")) or Decimal("100"))
    context = _subject_context(subject)
    context["active_period"] = period
    return render(request, "subjects/_term.html", _period_context(context, period))

@login_required
def class_standing_delete(request, pk, assessment_id):
    subject, response = _subject_or_redirect(request, pk)
    if response is not None:
        return response
    if request.method != "POST":
        return redirect("subjects:subject_detail", pk)
    assessment = ClassStandingAssessment.objects.filter(pk=assessment_id, subject=subject).first()
    if assessment is None:
        # Already removed (e.g. a duplicate click) — nothing left to delete.
        period = request.POST.get("grading_period")
        if period not in PERIODS:
            period = PRELIM
    else:
        period = assessment.grading_period
        assessment.delete()
    context = _subject_context(subject)
    return render(request, "subjects/_term.html", _period_context(context, period))

@login_required
def major_exam_update(request, pk, period):
    subject, response = _subject_or_redirect(request, pk)
    if response is not None:
        return response
    if period not in PERIODS:
        return HttpResponseBadRequest("Invalid grading period.")
    if request.method != "POST":
        return redirect("subjects:subject_detail", pk)
    exam, _ = MajorExam.objects.get_or_create(subject=subject, grading_period=period)
    exam.score = _decimal_or_none(request.POST.get("score"))
    exam.highest_possible_score = _decimal_or_none(
        request.POST.get("highest_possible_score")) or Decimal("100")
    exam.save()
    context = _subject_context(subject)
    return render(request, "subjects/_term.html", _period_context(context, period))

def _period_context(context, period):
    period_data = next(p for p in context["periods"] if p["code"] == period)
    return {"subject": context["subject"], "result": context["result"], "period": period_data, "oob": True}

@login_required
def recalculate(request, pk):
    subject, response = _subject_or_redirect(request, pk)
    if response is not None:
        return response
    result = calculate_grade(
        subject, list(subject.class_standing_assessments.all()), list(subject.major_exams.all()))
    return render(request, "subjects/_results.html", {"result": result})

@login_required
def target_grade(request, pk):
    subject, response = _subject_or_redirect(request, pk)
    if response is not None:
        return response
    target = request.POST.get("target_grade", "1.75")
    cs_assessments = list(subject.class_standing_assessments.all())
    major_exams = list(subject.major_exams.all())
    try:
        plan = build_target_plan(subject, cs_assessments, major_exams, target)
    except (ValueError, ArithmeticError) as exc:
        return HttpResponseBadRequest(str(exc))
    me_remaining_label = None
    if len(plan.me.remaining_exams) == 1:
        me_remaining_label = PERIOD_LABELS[plan.me.remaining_exams[0].grading_period]
    return render(request, "subjects/_target.html",
                  {"plan": plan, "target": target, "me_remaining_label": me_remaining_label})

@login_required
@require_POST
def ai_assistant_ask(request, pk):
    subject, response = _subject_or_redirect(request, pk)
    if response is not None:
        return response
    question = request.POST.get("question", "")
    cs_assessments = list(subject.class_standing_assessments.all())
    major_exams = list(subject.major_exams.all())
    try:
        answer = ai_assistant.answer_question(subject, cs_assessments, major_exams, question)
    except ai_assistant.AIAssistantError as exc:
        return render(request, "subjects/_ai_response.html", {"error": str(exc)})
    return render(request, "subjects/_ai_response.html",
                  {"question": question.strip(), "answer": answer})

def signup(request):
    if request.user.is_authenticated:
        return redirect("subjects:dashboard")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        auth_login(request, user)
        messages.success(request, f"Welcome, {user.username}! Your account has its own subjects.")
        return redirect("subjects:dashboard")
    return render(request, "registration/signup.html", {"form": form})