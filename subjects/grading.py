from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

@dataclass(frozen=True)
class GradeResult:
    class_standing_average: Decimal
    major_exam_average: Decimal
    computed_average: Decimal
    transmuted_value: int
    current_grade: str

GRADE_TABLE = [
    (97, "1.00", "Outstanding"),
    (94, "1.25", "Excellent"),
    (91, "1.50", "Superior"),
    (88, "1.75", "Very Good"),
    (85, "2.00", "Good"),
    (82, "2.25", "Satisfactory"),
    (79, "2.50", "Fairly Satisfactory"),
    (76, "2.75", "Fair"),
    (75, "3.00", "Passed"),
]

def D(value):
    return Decimal(str(value))

def percentage(score, hps):
    score, hps = D(score), D(hps)
    if hps <= 0:
        raise ValueError("Highest possible score must be greater than zero.")
    return score / hps * D("100")

def class_standing_average(assessments):
    entered = [a for a in assessments if a.score is not None]
    if not entered:
        return D("0")
    scores = sum((D(a.score) for a in entered), D("0"))
    hps = sum((D(a.highest_possible_score) for a in entered), D("0"))
    if hps <= 0:
        raise ValueError("Class-standing HPS total must be greater than zero.")
    return scores / hps * D("100")

def major_exam_average(major_exams):
    entered = [e for e in major_exams if e.score is not None]
    if not entered:
        return D("0")
    total_weight = D(len(entered))
    if total_weight <= 0:
        raise ValueError("At least one major exam must be entered.")
    result = D("0")
    for e in entered:
        result += percentage(e.score, e.highest_possible_score) / total_weight
    return result

def computed_average(subject, csa, mea, cs_active, me_active):
    csps = D(subject.class_standing_percent_share) / D("100")
    meps = D(subject.major_exam_percent_share) / D("100")
    if cs_active and me_active:
        return csps * csa + meps * mea
    if cs_active:
        return csa
    if me_active:
        return mea
    return D("0")

def transmuted_value(computed_average_value, passing_average):
    ca, pa = D(computed_average_value), D(passing_average)
    if pa >= 100:
        raise ValueError("Passing Average must be below 100.")
    raw = ((ca - pa) * D("25")) / (D("100") - pa) + D("75")
    return int(raw.to_integral_value(rounding=ROUND_FLOOR))

def grade_from_transmuted(tv):
    for minimum, grade, _ in GRADE_TABLE:
        if tv >= minimum:
            return grade
    return "5.00"

def calculate_grade(subject, class_standing_assessments, major_exams):
    csa = class_standing_average(class_standing_assessments)
    mea = major_exam_average(major_exams)
    cs_active = any(a.score is not None for a in class_standing_assessments)
    me_active = any(e.score is not None for e in major_exams)
    ca = computed_average(subject, csa, mea, cs_active, me_active)
    tv = transmuted_value(ca, subject.passing_average)
    return GradeResult(csa, mea, ca, tv, grade_from_transmuted(tv))

def minimum_computed_average_for_grade(target_grade, passing_average):
    minimum_tv = next(
        (D(m) for m, grade, _ in GRADE_TABLE if D(grade) == D(target_grade)),
        None
    )
    if minimum_tv is None:
        raise ValueError("Unsupported target grade.")
    pa = D(passing_average)
    ca = pa + (minimum_tv - D("75")) * (D("100") - pa) / D("25")
    return ca.quantize(D("0.0001"))

def required_major_exam_average(subject, current_csa, target_grade):
    required_ca = minimum_computed_average_for_grade(
        target_grade, subject.passing_average)
    meps = D(subject.major_exam_percent_share) / D("100")
    csps = D(subject.class_standing_percent_share) / D("100")
    if meps <= 0:
        return None, required_ca
    return (required_ca - csps * D(current_csa)) / meps, required_ca

def required_class_standing_average(subject, current_mea, target_grade):
    """Mirror of required_major_exam_average: what Class Standing average is
    needed to hit the target, if the Major Examination average stays fixed."""
    required_ca = minimum_computed_average_for_grade(
        target_grade, subject.passing_average)
    csps = D(subject.class_standing_percent_share) / D("100")
    meps = D(subject.major_exam_percent_share) / D("100")
    if csps <= 0:
        return None, required_ca
    return (required_ca - meps * D(current_mea)) / csps, required_ca

@dataclass(frozen=True)
class ComponentBreakdown:
    """Current vs. best-case standing for one grading component (Class
    Standing points, or Major Examination weighted percentages), based on
    which underlying records already have a score and which don't.

    Points are the primary, user-facing numbers (scored_points/scored_hps =
    "Completed", max_points/max_hps = "Maximum Possible"); the *_average
    percentages exist only because the university grading formula needs a
    percentage internally -- they are always derived from the same points,
    never a second calculation."""
    active: bool
    has_remaining: bool
    scored_points: Decimal
    scored_hps: Decimal
    remaining_hps: Decimal
    max_points: Decimal
    max_hps: Decimal
    current_average: Decimal
    max_average: Decimal

def class_standing_breakdown(assessments):
    scored = [a for a in assessments if a.score is not None]
    unscored = [a for a in assessments if a.score is None]
    scored_points = sum((D(a.score) for a in scored), D("0"))
    scored_hps = sum((D(a.highest_possible_score) for a in scored), D("0"))
    remaining_hps = sum((D(a.highest_possible_score) for a in unscored), D("0"))
    max_points = scored_points + remaining_hps
    max_hps = scored_hps + remaining_hps
    current_average = (scored_points / scored_hps * D("100")) if scored_hps > 0 else D("0")
    max_average = (max_points / max_hps * D("100")) if max_hps > 0 else D("0")
    return ComponentBreakdown(bool(scored), bool(unscored), scored_points, scored_hps, remaining_hps,
                               max_points, max_hps, current_average, max_average)

def class_standing_points_needed(breakdown, required_average):
    """Extra points needed (out of breakdown.remaining_hps) to raise the
    Class Standing average to required_average. May be negative (already
    enough) or exceed remaining_hps (not reachable through Class Standing
    alone). None when there are no pending assessments to earn points on."""
    if breakdown.remaining_hps <= 0:
        return None
    total_hps = breakdown.scored_hps + breakdown.remaining_hps
    required_total_points = D(required_average) / D("100") * total_hps
    return required_total_points - breakdown.scored_points

def points_needed_on_hypothetical_assessment(breakdown, required_average, hypothetical_hps):
    """Points needed (out of hypothetical_hps) on ONE not-yet-existing
    assessment to raise the Class Standing average to required_average,
    given only what is already scored.

    This is for clearly-labeled what-if predictions only -- it must never be
    presented as a real, known assessment. hypothetical_hps should come from
    a caller-supplied estimate (e.g. the pattern of the student's own past
    assessments), never invented here."""
    if hypothetical_hps is None or hypothetical_hps <= 0:
        return None
    total_hps = breakdown.scored_hps + D(hypothetical_hps)
    required_total_points = D(required_average) / D("100") * total_hps
    return required_total_points - breakdown.scored_points

@dataclass(frozen=True)
class MajorExamBreakdown:
    """Major Exam is inherently percentage-based (each period has its own
    HPS, so raw scores aren't directly additive across
    periods the way Class Standing points are) -- scored_points here is a
    weighted-percentage sum, not a raw point total. Individual exams still
    carry their own real score/HPS points (see remaining_exams / the exam
    records themselves) for point-level display."""
    active: bool
    has_remaining: bool
    scored_points: Decimal
    scored_hps: Decimal
    remaining_hps: Decimal
    max_points: Decimal
    max_hps: Decimal
    current_average: Decimal
    max_average: Decimal
    remaining_exams: list

def major_exam_breakdown(major_exams):
    scored = [e for e in major_exams if e.score is not None]
    unscored = [e for e in major_exams if e.score is None]
    # Every grading period counts the same: Prelim, Midterm and Final are
    # each one equal share of the Major Exam component, regardless of how
    # many points their papers happen to be out of.
    scored_weight = D(len(scored))
    weighted_scored = D("0")
    for e in scored:
        weighted_scored += percentage(e.score, e.highest_possible_score)
    current_average = (weighted_scored / scored_weight) if scored_weight > 0 else D("0")
    remaining_weight = D(len(unscored))
    max_points = weighted_scored + remaining_weight * D("100")
    max_hps = scored_weight + remaining_weight
    max_average = (max_points / max_hps) if max_hps > 0 else D("0")
    return MajorExamBreakdown(bool(scored), bool(unscored), weighted_scored, scored_weight, remaining_weight,
                               max_points, max_hps, current_average, max_average, unscored)

def required_score_for_single_exam(breakdown, required_average):
    """The percentage score needed on the sole remaining major exam to reach
    required_average overall, holding the already-scored exams fixed. None
    unless exactly one major exam is still unscored."""
    if required_average is None or len(breakdown.remaining_exams) != 1:
        return None
    exam = breakdown.remaining_exams[0]
    weight = D("1")
    if weight <= 0:
        return None
    total_weight = breakdown.scored_hps + weight
    return (D(required_average) * total_weight - breakdown.scored_points) / weight

DIFFICULT_ROOM_RATIO = D("0.8")

ALL_GRADING_PERIODS = ("PRELIM", "MIDTERM", "FINAL")

def open_grading_periods(major_exams):
    """Grading periods that have not finished yet: the period's Major Exam
    has no score, or no exam record exists for it at all.

    This is what tells the engine that the term is still running. Without
    it, a student who has only entered Prelim and Midterm looks like a
    student whose Class Standing is permanently closed at its current
    average, because "remaining work" is inferred solely from assessment
    rows that already exist in the database."""
    by_period = {e.grading_period: e for e in major_exams}
    return [p for p in ALL_GRADING_PERIODS
            if by_period.get(p) is None or by_period[p].score is None]

def periods_missing_class_standing(cs_assessments, major_exams):
    """Open periods that have no Class Standing assessment entered at all --
    i.e. activities the student will almost certainly still get, but which
    do not exist as rows yet."""
    entered = {a.grading_period for a in cs_assessments}
    return [p for p in open_grading_periods(major_exams) if p not in entered]

def class_standing_is_open(cs_assessments, major_exams):
    """True when Class Standing can still change: either a pending
    assessment exists, or a grading period has not happened yet."""
    if any(a.score is None for a in cs_assessments):
        return True
    return bool(periods_missing_class_standing(cs_assessments, major_exams))

def estimated_future_cs_hps(cs_assessments, major_exams):
    """Deterministic estimate of the Class Standing points still to come in
    periods that have not happened yet, inferred only from the student's own
    history: their average total points per completed period, multiplied by
    the number of periods with no Class Standing entered. Returns 0 when
    there is no history or no missing period -- it never invents a value out
    of nothing."""
    scored = [a for a in cs_assessments if a.score is not None]
    missing = periods_missing_class_standing(cs_assessments, major_exams)
    if not scored or not missing:
        return D("0")
    periods_with_history = {a.grading_period for a in scored}
    total_hps = sum((D(a.highest_possible_score) for a in scored), D("0"))
    per_period = total_hps / D(len(periods_with_history))
    return per_period * D(len(missing))

def perfect_cs_points_needed(cs, required_average):
    """The smallest number of ADDITIONAL Class Standing points, all earned
    at 100%, that would lift the Class Standing average to
    required_average -- assuming any already-pending assessment is also
    perfect.

    Solves (scored + x) / (hps + x) = r for x, which is exact and needs no
    guess about how many future activities there will be or how big they
    are. Returns None when required_average is 100 or more (unreachable
    once a single point has been lost)."""
    r = D(required_average) / D("100")
    if r >= 1:
        return None
    points = cs.scored_points + cs.remaining_hps
    hps = cs.scored_hps + cs.remaining_hps
    return max(D("0"), (r * hps - points) / (D("1") - r))

def required_average_for_remaining_exams(me, required_me_average):
    """The average percentage needed ACROSS every still-unscored major exam.

    When more than one exam is left, no single score answers "what do I
    need"; the honest answer is the average the remaining papers must hit
    together. Each grading period is one equal share, so this solves
    (scored_total + n_remaining * x) / n_total = required, which is exact
    and makes no assumption about how the student splits it between papers.
    Returns None when nothing is outstanding."""
    remaining = len(me.remaining_exams)
    if remaining <= 0:
        return None
    scored_count = me.scored_hps  # one unit per scored exam
    total = scored_count + D(remaining)
    return (D(required_me_average) * total - me.scored_points) / D(remaining)

def best_possible(subject, cs, me, extra_cs_hps=None):
    """The highest Computed Average/grade reachable from here, assuming a
    perfect 100% on every not-yet-scored Class Standing point and Major
    Exam. Reuses the exact same formula as the current-grade calculation.

    extra_cs_hps adds estimated future Class Standing points for grading
    periods that have not happened yet, so an unfinished term is not scored
    as though Class Standing were already final."""
    extra = D(extra_cs_hps or 0)
    cs_max_points = cs.max_points + extra
    cs_max_hps = cs.max_hps + extra
    cs_max_average = (cs_max_points / cs_max_hps * D("100")) if cs_max_hps > 0 else D("0")
    cs_potential = cs_max_hps > 0
    me_potential = me.scored_hps + me.remaining_hps > 0
    max_ca = computed_average(subject, cs_max_average, me.max_average, cs_potential, me_potential)
    max_tv = transmuted_value(max_ca, subject.passing_average)
    max_grade = grade_from_transmuted(max_tv)
    return max_ca, max_tv, max_grade

@dataclass(frozen=True)
class TargetPlan:
    target: str
    required_ca: Decimal
    max_ca: Decimal
    max_tv: int
    max_grade: str
    status: str
    cs: ComponentBreakdown
    me: MajorExamBreakdown
    cs_required_avg: object
    cs_points_needed: object
    me_required_avg: object
    me_required_score: object
    scenario_current_cs_required_me: object
    scenario_perfect_cs_required_me: object
    scenario_current_cs_achievable: object
    scenario_perfect_cs_achievable: object
    scenario_perfect_cs_reachable: bool
    cs_open: bool = False
    max_ca_open: object = None
    max_grade_open: object = None
    open_periods: tuple = ()
    estimated_future_cs_hps: object = None
    cs_required_avg_with_best_exams: object = None
    perfect_cs_points_needed: object = None

def build_target_plan(subject, cs_assessments, major_exams, target_grade):
    """Full requirement breakdown for reaching target_grade, built entirely
    from the existing grading formula (calculate_grade / transmutation) plus
    the actual assessment and exam records — no separate grading system."""
    result = calculate_grade(subject, cs_assessments, major_exams)
    required_ca = minimum_computed_average_for_grade(target_grade, subject.passing_average)

    cs = class_standing_breakdown(cs_assessments)
    me = major_exam_breakdown(major_exams)

    cs_open = class_standing_is_open(cs_assessments, major_exams)
    open_periods = tuple(open_grading_periods(major_exams))
    future_cs_hps = estimated_future_cs_hps(cs_assessments, major_exams)

    # max_ca stays strictly database-grounded (a perfect score on rows that
    # actually exist). Everything downstream that splits a requirement
    # between components depends on it being exactly the weighted
    # combination of cs.max_average and me.max_average, so estimated future
    # points must never be folded into it.
    max_ca, max_tv, max_grade = best_possible(subject, cs, me)
    # A second, wider ceiling used ONLY to decide whether the term is still
    # open enough for the target to survive.
    max_ca_open, _, max_grade_open = best_possible(subject, cs, me, future_cs_hps)
    # The true ceiling while the term is open: enough future activities, all
    # perfect, push the Class Standing average arbitrarily close to 100%.
    # This -- not the estimate above -- is what decides whether a target is
    # genuinely dead, because it makes no guess about how much work is left.
    supremum_ca = computed_average(
        subject, D("100"), me.max_average, True, me.scored_hps + me.remaining_hps > 0)

    if result.computed_average >= required_ca:
        # Already met with current, already-scored performance.
        status = "achievable"
    elif max_ca >= required_ca:
        gap_needed = required_ca - result.computed_average
        gap_available = max_ca - result.computed_average
        status = "difficult" if gap_needed / gap_available > DIFFICULT_ROOM_RATIO else "achievable"
    elif cs_open and supremum_ca >= required_ca:
        # Not reachable from the rows that exist today, but the term is not
        # over: Class Standing activities for a period that has not happened
        # yet simply have not been entered. "impossible" would be a lie --
        # the honest verdict is that it depends on work not yet recorded.
        status = "open"
    else:
        status = "impossible"

    me_required_avg, _ = required_major_exam_average(subject, result.class_standing_average, target_grade)
    cs_required_avg, _ = required_class_standing_average(subject, result.major_exam_average, target_grade)

    me_required_score = required_score_for_single_exam(me, me_required_avg)
    cs_points_needed = (
        class_standing_points_needed(cs, cs_required_avg) if cs_required_avg is not None else None
    )

    # A scenario's required Major Exam average is only truly reachable if it
    # doesn't exceed what the Major Exam component can actually still reach
    # (me.max_average), which already accounts for exams already locked in.
    scenario_current_cs_required_me = me_required_avg
    scenario_perfect_cs_required_me, _ = required_major_exam_average(subject, D("100"), target_grade)
    scenario_perfect_cs_reachable = cs.max_average >= D("100")

    scenario_current_cs_achievable = (
        scenario_current_cs_required_me is not None and scenario_current_cs_required_me <= me.max_average
    )
    scenario_perfect_cs_achievable = (
        scenario_perfect_cs_required_me is not None
        and scenario_perfect_cs_required_me <= me.max_average
        and scenario_perfect_cs_reachable
    )

    # The realistic combined plan: assume the student aces every remaining
    # Major Exam (me.max_average), then solve for the Class Standing average
    # they must FINISH the term with, and how many more perfect Class
    # Standing points that takes. This is the number that actually answers
    # "can I still get 1.00" for an unfinished term.
    csps = D(subject.class_standing_percent_share) / D("100")
    meps = D(subject.major_exam_percent_share) / D("100")
    if csps > 0:
        cs_required_avg_with_best_exams = (required_ca - meps * me.max_average) / csps
        perfect_points = perfect_cs_points_needed(cs, cs_required_avg_with_best_exams)
    else:
        cs_required_avg_with_best_exams = None
        perfect_points = None

    return TargetPlan(
        target=target_grade, required_ca=required_ca, max_ca=max_ca, max_tv=max_tv, max_grade=max_grade,
        status=status, cs=cs, me=me,
        cs_required_avg=cs_required_avg, cs_points_needed=cs_points_needed,
        me_required_avg=me_required_avg, me_required_score=me_required_score,
        scenario_current_cs_required_me=scenario_current_cs_required_me,
        scenario_perfect_cs_required_me=scenario_perfect_cs_required_me,
        scenario_current_cs_achievable=scenario_current_cs_achievable,
        scenario_perfect_cs_achievable=scenario_perfect_cs_achievable,
        scenario_perfect_cs_reachable=scenario_perfect_cs_reachable,
        cs_open=cs_open,
        max_ca_open=max_ca_open,
        max_grade_open=max_grade_open,
        open_periods=open_periods,
        estimated_future_cs_hps=future_cs_hps,
        cs_required_avg_with_best_exams=cs_required_avg_with_best_exams,
        perfect_cs_points_needed=perfect_points,
    )