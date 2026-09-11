from django.conf import settings
from django.db import models

PRELIM = "PRELIM"
MIDTERM = "MIDTERM"
FINAL = "FINAL"
GRADING_PERIOD_CHOICES = [
    (PRELIM, "Prelim"),
    (MIDTERM, "Midterm"),
    (FINAL, "Final"),
]

class Subject(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="subjects")
    name = models.CharField(max_length=150)
    units = models.DecimalField(max_digits=4, decimal_places=2, default=3)

    passing_average = models.DecimalField(max_digits=5, decimal_places=2, default=50)
    class_standing_percent_share = models.DecimalField(max_digits=5, decimal_places=2, default=70)
    major_exam_percent_share = models.DecimalField(max_digits=5, decimal_places=2, default=30)

    # Stamped whenever the student opens the subject, so Home can show what
    # they were last working on. Null means never opened -- such subjects
    # sort last rather than being treated as opened at the epoch.
    last_viewed_at = models.DateTimeField(null=True, blank=True, default=None)

    def __str__(self):
        return self.name

class ClassStandingAssessment(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE,
                                related_name="class_standing_assessments")
    name = models.CharField(max_length=150)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    highest_possible_score = models.DecimalField(max_digits=7, decimal_places=2, default=100)
    grading_period = models.CharField(max_length=20, choices=GRADING_PERIOD_CHOICES)

    def __str__(self):
        return f"{self.subject}: {self.name}"

class MajorExam(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE,
                                related_name="major_exams")
    grading_period = models.CharField(max_length=20, choices=GRADING_PERIOD_CHOICES)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    highest_possible_score = models.DecimalField(max_digits=7, decimal_places=2, default=100)
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=33.33)

    class Meta:
        unique_together = [("subject", "grading_period")]

    def __str__(self):
        return f"{self.subject}: {self.get_grading_period_display()} Exam"