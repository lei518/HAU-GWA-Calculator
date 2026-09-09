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
    total_weight = sum((D(e.weight) for e in entered), D("0"))
    if total_weight <= 0:
        raise ValueError("Active major-exam weight total must be greater than zero.")
    result = D("0")
    for e in entered:
        result += D(e.weight) / total_weight * percentage(e.score, e.highest_possible_score)
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
