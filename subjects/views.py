from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from .forms import SubjectForm
from .grading import calculate_grade, required_major_exam_average
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
    cs_by_period = {p: [a for a in cs_assessments if a.grading_period == p] for p in PERIODS}
    result = calculate_grade(subject, cs_assessments, list(major_exams.values()))
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
    for subject in subjects:
        result = calculate_grade(
            subject, list(subject.class_standing_assessments.all()), list(subject.major_exams.all()))
        rows.append((subject, result))
        if result.current_grade not in {"5.00", "6.00", "8.00", "9.00"}:
            total_units += subject.units
            weighted += Decimal(result.current_grade) * subject.units
    gwa = weighted / total_units if total_units else None
    return rows, gwa

@login_required
def dashboard(request):
    rows, gwa = _dashboard_rows(request.user)
    return render(request, "dashboard.html", {"rows": rows, "gwa": gwa})

@login_required
def subject_delete(request, pk):
    subject = get_object_or_404(Subject, pk=pk, student=request.user)
    if request.method != "POST":
        return redirect("subjects:dashboard")
    subject.delete()
    if request.headers.get("HX-Request") == "true":
        rows, gwa = _dashboard_rows(request.user)
        return render(request, "subjects/_subjects_section.html", {"rows": rows, "gwa": gwa})
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
                        request.POST.get(f"{prefix}_exam_hps")) or Decimal("100"),
                    weight=_decimal_or_none(request.POST.get(f"{prefix}_exam_weight")) or Decimal("33.33"))
        messages.success(request, f'"{subject.name}" was added.')
        return redirect("subjects:dashboard")
    terms = [{"code": p, "label": PERIOD_LABELS[p], "prefix": PERIOD_PREFIX[p]} for p in PERIODS]
    return render(request, "subjects/form.html", {"form": form, "terms": terms})

@login_required
def subject_detail(request, pk):
    subject, response = _subject_or_redirect(request, pk)
    if response is not None:
        return response
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
    exam.weight = _decimal_or_none(request.POST.get("weight")) or Decimal("33.33")
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
    try:
        result = calculate_grade(
            subject, list(subject.class_standing_assessments.all()), list(subject.major_exams.all()))
        required_mea, required_ca = required_major_exam_average(
            subject, result.class_standing_average, target)
        if required_mea is None:
            message = "Major examinations do not contribute to this subject."
        elif required_mea <= 0:
            message = "Your current performance is already sufficient for this target."
        elif required_mea > 100:
            message = "This target is not currently achievable with a maximum 100% Major Examination Average."
        else:
            message = f"You need at least {required_mea:.2f}% Major Examination Average."
    except (ValueError, ArithmeticError) as exc:
        return HttpResponseBadRequest(str(exc))
    return render(request, "subjects/_target.html",
                  {"message": message, "required_ca": required_ca, "target": target})

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
