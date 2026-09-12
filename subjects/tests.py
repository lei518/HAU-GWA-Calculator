from decimal import Decimal
from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from .forms import SubjectForm
from . import ai_assistant
from .grading import (
    best_possible, build_target_plan, calculate_grade, class_standing_breakdown,
    major_exam_breakdown, minimum_computed_average_for_grade, transmuted_value,
)
from .models import ClassStandingAssessment, MajorExam, Subject
from .views import RECENT_SUBJECT_COUNT

class GradingEngineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="test", password="pass")
        self.subject = Subject.objects.create(
            student=self.user, name="Sample", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)

    def add_cs(self, name, period, score=90, hps=100):
        return ClassStandingAssessment.objects.create(
            subject=self.subject, name=name, grading_period=period, score=score,
            highest_possible_score=hps)

    def add_exam(self, period, score=None, hps=100):
        return MajorExam.objects.create(
            subject=self.subject, grading_period=period, score=score,
            highest_possible_score=hps)

    def test_class_standing_average(self):
        self.add_cs("Quiz", "PRELIM", score=18, hps=20)
        self.add_cs("Activity", "PRELIM", score=45, hps=50)
        result = calculate_grade(
            self.subject, list(self.subject.class_standing_assessments.all()),
            list(self.subject.major_exams.all()))
        self.assertEqual(result.class_standing_average, Decimal("90"))

    def test_missing_final_normalizes_active_exam_weights(self):
        self.add_exam("PRELIM", score=80)
        self.add_exam("MIDTERM", score=100)
        self.add_exam("FINAL", score=None)
        result = calculate_grade(
            self.subject, list(self.subject.class_standing_assessments.all()),
            list(self.subject.major_exams.all()))
        self.assertAlmostEqual(float(result.major_exam_average), 90, places=4)

    def test_transmutation_truncates(self):
        self.assertEqual(transmuted_value(Decimal("77.6765"), Decimal("50")), 88)

    def test_reverse_transmutation_for_1_75(self):
        self.assertEqual(
            minimum_computed_average_for_grade("1.75", Decimal("50")),
            Decimal("76.0000"))

    def test_no_subject_code_field(self):
        self.assertFalse(hasattr(self.subject, "code"))


class SubjectCreateViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="test2", password="pass")
        self.client.force_login(self.user)

    def test_create_subject_without_code_creates_terms(self):
        response = self.client.post(reverse("subjects:subject_create"), {
            "name": "Database Management Systems",
            "units": "3",
            "passing_average": "50",
            "class_standing_percent_share": "70",
            "major_exam_percent_share": "30",
            "prelim_name": ["Quiz 1", "Activity 1"],
            "prelim_score": ["18", "45"],
            "prelim_hps": ["20", "50"],
            "prelim_exam_score": "", "prelim_exam_hps": "100", "prelim_exam_weight": "33.33",
            "midterm_name": [], "midterm_score": [], "midterm_hps": [],
            "midterm_exam_score": "", "midterm_exam_hps": "100", "midterm_exam_weight": "33.33",
            "final_name": [], "final_score": [], "final_hps": [],
            "final_exam_score": "", "final_exam_hps": "100", "final_exam_weight": "33.33",
        })
        self.assertRedirects(response, reverse("subjects:dashboard"))
        subject = Subject.objects.get(name="Database Management Systems")
        self.assertFalse(hasattr(subject, "code"))
        self.assertEqual(subject.class_standing_assessments.count(), 2)
        self.assertEqual(subject.major_exams.count(), 3)

    def test_add_subject_page_has_no_code_field(self):
        response = self.client.get(reverse("subjects:subject_create"))
        self.assertNotContains(response, 'name="code"')
        self.assertContains(response, "Subject Name")

    def minimal_payload(self, name):
        payload = {
            "name": name, "units": "3", "passing_average": "50",
            "class_standing_percent_share": "70", "major_exam_percent_share": "30",
        }
        for prefix in ("prelim", "midterm", "final"):
            payload.update({
                f"{prefix}_name": [], f"{prefix}_score": [], f"{prefix}_hps": [],
                f"{prefix}_exam_score": "", f"{prefix}_exam_hps": "100", f"{prefix}_exam_weight": "33.33",
            })
        return payload

    def test_adding_a_subject_does_not_hide_existing_subjects(self):
        # Mirrors the reported bug: add A, add B, add C, then check the
        # dashboard shows all of them together, not just the newest one.
        self.client.post(reverse("subjects:subject_create"), self.minimal_payload("Subject A"))
        self.client.post(reverse("subjects:subject_create"), self.minimal_payload("Subject B"))
        self.client.post(reverse("subjects:subject_create"), self.minimal_payload("Subject C"))

        self.assertEqual(Subject.objects.filter(student=self.user).count(), 3)
        pks = list(Subject.objects.filter(student=self.user).values_list("pk", flat=True))
        self.assertEqual(len(set(pks)), 3, "each new subject must get its own id, not reuse one")

        response = self.client.get(reverse("subjects:dashboard"))
        body = response.content.decode()
        for name in ("Subject A", "Subject B", "Subject C"):
            self.assertIn(name, body)

    def test_create_redirects_to_dashboard_not_detail(self):
        response = self.client.post(reverse("subjects:subject_create"), self.minimal_payload("Redirect Check"))
        self.assertRedirects(response, reverse("subjects:dashboard"))


class SubjectDeleteViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="test3", password="pass")
        self.other_user = get_user_model().objects.create_user(username="test4", password="pass")
        self.client.force_login(self.user)
        self.subject_a = Subject.objects.create(
            student=self.user, name="Keep Me", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        self.subject_b = Subject.objects.create(
            student=self.user, name="Delete Me", units=5,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        ClassStandingAssessment.objects.create(
            subject=self.subject_b, name="Quiz", grading_period="PRELIM", score=9, highest_possible_score=10)
        MajorExam.objects.create(subject=self.subject_b, grading_period="PRELIM", score=90, highest_possible_score=100)

    def test_delete_removes_subject_and_children_only(self):
        assessment_id = self.subject_b.class_standing_assessments.first().pk
        response = self.client.post(reverse("subjects:subject_delete", args=[self.subject_b.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Subject.objects.filter(pk=self.subject_b.pk).exists())
        self.assertFalse(ClassStandingAssessment.objects.filter(pk=assessment_id).exists())
        self.assertTrue(Subject.objects.filter(pk=self.subject_a.pk).exists())

    def test_htmx_delete_returns_updated_section(self):
        response = self.client.post(
            reverse("subjects:subject_delete", args=[self.subject_b.pk]),
            HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('id="subjects-section"', body)
        self.assertNotIn("Delete Me", body)
        self.assertIn("Keep Me", body)

    def test_deleting_last_subject_shows_empty_state(self):
        self.client.post(reverse("subjects:subject_delete", args=[self.subject_b.pk]), HTTP_HX_REQUEST="true")
        response = self.client.post(
            reverse("subjects:subject_delete", args=[self.subject_a.pk]),
            HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No subjects yet.", response.content.decode())

    def test_cannot_delete_another_users_subject(self):
        self.client.force_login(self.other_user)
        response = self.client.post(reverse("subjects:subject_delete", args=[self.subject_a.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Subject.objects.filter(pk=self.subject_a.pk).exists())

    def test_get_request_does_not_delete(self):
        response = self.client.get(reverse("subjects:subject_delete", args=[self.subject_a.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Subject.objects.filter(pk=self.subject_a.pk).exists())


class DeletedSubjectAccessTests(TestCase):
    """Covers the reported 404: visiting a deleted subject's old URL."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="test5", password="pass")
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(
            student=self.user, name="Temporary", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        self.deleted_pk = self.subject.pk
        self.subject.delete()

    def test_detail_page_redirects_instead_of_404ing(self):
        response = self.client.get(
            reverse("subjects:subject_detail", args=[self.deleted_pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("subjects:dashboard"))
        self.assertContains(response, "could not be found")

    def test_nonexistent_pk_also_redirects(self):
        response = self.client.get(
            reverse("subjects:subject_detail", args=[999999]), follow=True)
        self.assertRedirects(response, reverse("subjects:dashboard"))

    def test_class_standing_add_on_deleted_subject_redirects(self):
        response = self.client.post(
            reverse("subjects:class_standing_add", args=[self.deleted_pk]),
            {"grading_period": "PRELIM", "name": "Quiz", "score": "8", "highest_possible_score": "10"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ClassStandingAssessment.objects.filter(subject_id=self.deleted_pk).exists())

    def test_htmx_request_on_deleted_subject_gets_hx_redirect(self):
        response = self.client.post(
            reverse("subjects:target_grade", args=[self.deleted_pk]),
            {"target_grade": "1.75"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("subjects:dashboard"))

    def test_major_exam_update_on_deleted_subject_redirects(self):
        response = self.client.post(
            reverse("subjects:major_exam_update", args=[self.deleted_pk, "PRELIM"]),
            {"score": "10", "highest_possible_score": "10", "weight": "33.33"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MajorExam.objects.filter(subject_id=self.deleted_pk).exists())

    def test_deleting_subject_does_not_break_a_second_open_tab(self):
        # Simulate the exact bug report: a second tab already viewing the
        # subject issues an in-page action after it was deleted elsewhere.
        response = self.client.post(
            reverse("subjects:class_standing_delete", args=[self.deleted_pk, 1]))
        self.assertEqual(response.status_code, 302)


class CrossUserIsolationTests(TestCase):
    """User A must never be able to see or touch User B's data, via any view."""

    def setUp(self):
        self.user_a = get_user_model().objects.create_user(username="alice", password="pass12345")
        self.user_b = get_user_model().objects.create_user(username="bob", password="pass12345")

        self.subject_b = Subject.objects.create(
            student=self.user_b, name="Bob Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        self.assessment_b = ClassStandingAssessment.objects.create(
            subject=self.subject_b, name="Bob Quiz", grading_period="PRELIM",
            score=9, highest_possible_score=10)
        self.exam_b = MajorExam.objects.create(
            subject=self.subject_b, grading_period="PRELIM", score=88, highest_possible_score=100)

        self.client.force_login(self.user_a)

    def test_dashboard_does_not_list_other_users_subject(self):
        response = self.client.get(reverse("subjects:dashboard"))
        body = response.content.decode()
        self.assertNotIn("Bob Subject", body)
        self.assertContains(response, "No subjects yet.")

    def test_gwa_excludes_other_users_subjects(self):
        Subject.objects.create(
            student=self.user_a, name="Alice Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        response = self.client.get(reverse("subjects:dashboard"))
        self.assertContains(response, "Alice Subject")
        self.assertNotContains(response, "Bob Subject")

    def test_subject_detail_of_other_user_redirects_not_leaks(self):
        response = self.client.get(
            reverse("subjects:subject_detail", args=[self.subject_b.pk]), follow=True)
        self.assertRedirects(response, reverse("subjects:dashboard"))
        self.assertNotIn("Bob Subject", response.content.decode())

    def test_cannot_add_assessment_to_other_users_subject(self):
        response = self.client.post(
            reverse("subjects:class_standing_add", args=[self.subject_b.pk]),
            {"grading_period": "PRELIM", "name": "Injected", "score": "5", "highest_possible_score": "10"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ClassStandingAssessment.objects.filter(subject=self.subject_b, name="Injected").exists())

    def test_cannot_delete_other_users_assessment(self):
        response = self.client.post(
            reverse("subjects:class_standing_delete", args=[self.subject_b.pk, self.assessment_b.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ClassStandingAssessment.objects.filter(pk=self.assessment_b.pk).exists())

    def test_cannot_edit_other_users_major_exam(self):
        response = self.client.post(
            reverse("subjects:major_exam_update", args=[self.subject_b.pk, "PRELIM"]),
            {"score": "0", "highest_possible_score": "100", "weight": "10"})
        self.assertEqual(response.status_code, 302)
        self.exam_b.refresh_from_db()
        self.assertEqual(self.exam_b.score, Decimal("88"))

    def test_cannot_delete_other_users_subject(self):
        response = self.client.post(reverse("subjects:subject_delete", args=[self.subject_b.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Subject.objects.filter(pk=self.subject_b.pk).exists())

    def test_cannot_view_other_users_target_grade(self):
        response = self.client.post(
            reverse("subjects:target_grade", args=[self.subject_b.pk]), {"target_grade": "1.75"})
        self.assertEqual(response.status_code, 302)

    def test_url_tampering_to_guess_ids_is_blocked(self):
        # Directly mirrors the reported /subjects/2/-style concern: iterate
        # over plausible ids and confirm none leak another user's subject.
        for pk in range(1, 20):
            response = self.client.get(reverse("subjects:subject_detail", args=[pk]), follow=True)
            self.assertNotIn("Bob Subject", response.content.decode())


class UnauthenticatedAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="carol", password="pass12345")
        self.subject = Subject.objects.create(
            student=self.user, name="Carol's Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("subjects:dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('subjects:dashboard')}")

    def test_subject_detail_requires_login(self):
        response = self.client.get(reverse("subjects:subject_detail", args=[self.subject.pk]))
        self.assertTrue(response.url.startswith(reverse("login")))

    def test_subject_create_requires_login(self):
        response = self.client.get(reverse("subjects:subject_create"))
        self.assertTrue(response.url.startswith(reverse("login")))

    def test_subject_delete_requires_login(self):
        response = self.client.post(reverse("subjects:subject_delete", args=[self.subject.pk]))
        self.assertTrue(response.url.startswith(reverse("login")))
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())


class SignupViewTests(TestCase):
    def test_signup_creates_account_and_logs_in(self):
        response = self.client.post(reverse("signup"), {
            "username": "newstudent", "password1": "s3cure-pass-99", "password2": "s3cure-pass-99",
        })
        self.assertRedirects(response, reverse("subjects:dashboard"))
        self.assertTrue(get_user_model().objects.filter(username="newstudent").exists())
        # session is authenticated as the new user
        response = self.client.get(reverse("subjects:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_new_account_starts_with_no_subjects_and_cannot_see_others(self):
        other = get_user_model().objects.create_user(username="existing", password="pass12345")
        Subject.objects.create(
            student=other, name="Existing User Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)

        self.client.post(reverse("signup"), {
            "username": "freshuser", "password1": "s3cure-pass-99", "password2": "s3cure-pass-99",
        })
        response = self.client.get(reverse("subjects:dashboard"))
        body = response.content.decode()
        self.assertContains(response, "No subjects yet.")
        self.assertNotIn("Existing User Subject", body)

    def test_duplicate_username_rejected(self):
        get_user_model().objects.create_user(username="taken", password="pass12345")
        response = self.client.post(reverse("signup"), {
            "username": "taken", "password1": "s3cure-pass-99", "password2": "s3cure-pass-99",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_model().objects.filter(username="taken").count(), 1)

    def test_already_authenticated_user_redirected_away_from_signup(self):
        user = get_user_model().objects.create_user(username="loggedin", password="pass12345")
        self.client.force_login(user)
        response = self.client.get(reverse("signup"))
        self.assertRedirects(response, reverse("subjects:dashboard"))


class ClassStandingPointsBreakdownTests(TestCase):
    """Points, not percentages, are the primary representation of Class
    Standing: completed points exclude pending items, maximum possible
    points include only assessments that actually exist in the database."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pointstest", password="pass12345")
        self.subject = Subject.objects.create(
            student=self.user, name="Points Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)

    def add(self, name, period="PRELIM", score=None, hps=50):
        return ClassStandingAssessment.objects.create(
            subject=self.subject, name=name, grading_period=period, score=score,
            highest_possible_score=hps)

    def test_1_all_assessments_completed_current_equals_maximum(self):
        self.add("Activity 1", score=50, hps=50)
        self.add("Activity 2", score=38, hps=40)
        self.add("Activity 3", score=45, hps=50)
        assessments = list(self.subject.class_standing_assessments.all())
        breakdown = class_standing_breakdown(assessments)

        self.assertEqual(breakdown.scored_points, Decimal("133"))
        self.assertEqual(breakdown.scored_hps, Decimal("140"))
        self.assertEqual(breakdown.remaining_hps, Decimal("0"))
        self.assertFalse(breakdown.has_remaining)
        # Current points ARE the maximum possible points -- nothing pending.
        self.assertEqual(breakdown.max_points, breakdown.scored_points)
        self.assertEqual(breakdown.max_hps, breakdown.scored_hps)

    def test_2_completed_and_pending_mix_matches_worked_example(self):
        self.add("Activity 1", score=50, hps=50)
        self.add("Activity 2", score=38, hps=40)
        self.add("Activity 3", score=45, hps=50)
        self.add("Activity 4", score=None, hps=50)  # known but pending
        assessments = list(self.subject.class_standing_assessments.all())
        breakdown = class_standing_breakdown(assessments)

        # Completed earned/possible excludes the pending assessment entirely.
        self.assertEqual(breakdown.scored_points, Decimal("133"))
        self.assertEqual(breakdown.scored_hps, Decimal("140"))
        # Pending available points = Activity 4's HPS.
        self.assertEqual(breakdown.remaining_hps, Decimal("50"))
        self.assertTrue(breakdown.has_remaining)
        # Maximum possible = completed + full marks on the pending item.
        self.assertEqual(breakdown.max_points, Decimal("183"))
        self.assertEqual(breakdown.max_hps, Decimal("190"))

    def test_3_no_pending_assessments_is_correctly_identified(self):
        self.add("Activity 1", score=50, hps=50)
        assessments = list(self.subject.class_standing_assessments.all())
        breakdown = class_standing_breakdown(assessments)
        self.assertFalse(breakdown.has_remaining)
        self.assertEqual(breakdown.remaining_hps, Decimal("0"))

    def test_4_hypothetical_future_assessment_is_never_invented(self):
        self.add("Activity 1", score=50, hps=50)
        self.add("Activity 2", score=None, hps=50)
        assessments = list(self.subject.class_standing_assessments.all())
        breakdown = class_standing_breakdown(assessments)

        # Only the two real records exist -- nothing named "Activity 3" etc.
        names = {a.name for a in assessments}
        self.assertEqual(names, {"Activity 1", "Activity 2"})
        self.assertEqual(len(assessments), 2)
        # Maximum possible reflects only Activity 2's real HPS (50), not some
        # imagined additional activity.
        self.assertEqual(breakdown.max_hps, Decimal("100"))


class TargetGradeWithPendingAssessmentsTests(TestCase):
    """TEST 5: the target calculator must use the real maximum possible
    result (current + pending HPS), never silently assume max == current."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="targetpoints", password="pass12345")
        self.subject = Subject.objects.create(
            student=self.user, name="Target Points Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)

    def test_pending_assessment_expands_maximum_possible(self):
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 1", grading_period="PRELIM", score=30, highest_possible_score=50)
        MajorExam.objects.create(subject=self.subject, grading_period="PRELIM", score=60, highest_possible_score=100)
        cs_assessments = list(self.subject.class_standing_assessments.all())
        major_exams = list(self.subject.major_exams.all())

        plan_before = build_target_plan(self.subject, cs_assessments, major_exams, "1.75")

        # Now add a pending (unscored) assessment worth 50 points.
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 2", grading_period="PRELIM", score=None, highest_possible_score=50)
        cs_assessments = list(self.subject.class_standing_assessments.all())
        plan_after = build_target_plan(self.subject, cs_assessments, major_exams, "1.75")

        # Maximum possible must increase once a real pending assessment
        # exists -- it must NOT stay equal to the (now stale) prior max.
        self.assertGreater(plan_after.max_ca, plan_before.max_ca)
        self.assertTrue(plan_after.cs.has_remaining)
        self.assertEqual(plan_after.cs.remaining_hps, Decimal("50"))
        self.assertEqual(plan_after.cs.max_hps, Decimal("100"))


class AIAssistantContextTests(TestCase):
    """TEST 6/7: the AI assistant must receive exact, deterministic point
    totals computed by Django, and must never be handed invented data."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="aicontext", password="pass12345")
        self.subject = Subject.objects.create(
            student=self.user, name="AI Context Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 1", grading_period="PRELIM", score=50, highest_possible_score=50)
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 2", grading_period="PRELIM", score=38, highest_possible_score=40)
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 3", grading_period="PRELIM", score=45, highest_possible_score=50)
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 4", grading_period="PRELIM", score=None, highest_possible_score=50)

    def test_6_context_carries_exact_point_totals(self):
        cs_assessments = list(self.subject.class_standing_assessments.all())
        major_exams = list(self.subject.major_exams.all())
        context = ai_assistant.build_context(self.subject, cs_assessments, major_exams, "Predict my final grade.")

        points = context["class_standing_points"]
        self.assertEqual(points["completed_earned_points"], 133.0)
        self.assertEqual(points["completed_possible_points"], 140.0)
        self.assertEqual(points["pending_points_available"], 50.0)
        self.assertEqual(points["maximum_possible_earned_points"], 183.0)
        self.assertEqual(points["maximum_possible_total_points"], 190.0)
        self.assertTrue(points["has_pending_assessments"])

    def test_7_context_never_invents_assessments(self):
        cs_assessments = list(self.subject.class_standing_assessments.all())
        major_exams = list(self.subject.major_exams.all())
        # Ask about an assessment that does not exist in the database.
        context = ai_assistant.build_context(
            self.subject, cs_assessments, major_exams, "What if Activity 5 gets 100%?")

        names = {a["name"] for a in context["class_standing_assessments"]}
        self.assertEqual(names, {"Activity 1", "Activity 2", "Activity 3", "Activity 4"})
        self.assertNotIn("Activity 5", names)
        self.assertEqual(len(context["class_standing_assessments"]), 4)


class AIAssistantVisibilityTests(TestCase):
    """TEST 8/9/10: the AI Grade Assistant must actually be present in the
    rendered Subject Details HTML -- not merely exist as backend code."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="aivisible", password="pass12345")
        self.client.force_login(self.user)

    def test_8_ai_assistant_renders_on_subject_with_data(self):
        subject = Subject.objects.create(
            student=self.user, name="Visible Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM", score=45, highest_possible_score=50)

        response = self.client.get(reverse("subjects:subject_detail", args=[subject.pk]))
        body = response.content.decode()
        self.assertContains(response, "AI Grade Assistant")
        self.assertIn('class="ai-fab"', body)
        self.assertIn("data-ai-modal", body)
        self.assertIn('id="ai-assistant-form"', body)
        self.assertIn('id="ai-question-input"', body)
        self.assertIn("Answering about Visible Subject", body)
        self.assertIn(reverse("subjects:ai_assistant_ask", args=[subject.pk]), body)

    def test_8_ai_assistant_renders_even_with_no_assessments_at_all(self):
        # Regression guard: the assistant must not be hidden behind a
        # condition that only happens to be true for subjects with data.
        subject = Subject.objects.create(
            student=self.user, name="Empty Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        response = self.client.get(reverse("subjects:subject_detail", args=[subject.pk]))
        body = response.content.decode()
        self.assertContains(response, "AI Grade Assistant")
        self.assertIn('id="ai-assistant-form"', body)

    def test_9_ai_assistant_markup_is_not_hidden(self):
        subject = Subject.objects.create(
            student=self.user, name="Not Hidden Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        body = self.client.get(reverse("subjects:subject_detail", args=[subject.pk])).content.decode()
        # The launcher must always be visible; the modal it opens is
        # deliberately `hidden` until clicked.
        fab_start = body.index('class="ai-fab"')
        tag_start = body.rindex("<", 0, fab_start)
        opening_tag = body[tag_start:body.index(">", fab_start)]
        self.assertNotIn("display:none", opening_tag.replace(" ", ""))
        self.assertNotIn("hidden", opening_tag)

    def test_10_ai_assistant_present_for_subject_owned_by_this_user_only(self):
        subject = Subject.objects.create(
            student=self.user, name="Owner Check Subject", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        ask_url = reverse("subjects:ai_assistant_ask", args=[subject.pk])
        detail_url = reverse("subjects:subject_detail", args=[subject.pk])

        self.assertContains(self.client.get(detail_url), ask_url)

        other = get_user_model().objects.create_user(username="notowner", password="pass12345")
        self.client.force_login(other)
        response = self.client.get(detail_url, follow=True)
        # Bounced to Home: the assistant chrome is global, but nothing there
        # can ask about a subject this user does not own.
        self.assertNotContains(response, ask_url)
        self.assertNotContains(response, "ai-assistant-form")


class RequiredScoreRecommendationTests(TestCase):
    """The AI recommendation must be the true, mathematically-derived
    required score -- never silently capped at the assessment maximum, and
    never two independently-"maxed" numbers that would double-count if both
    were achieved. Every recommendation here is verified by feeding it back
    into the actual calculate_grade() the rest of the app uses."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="reqscore", password="pass12345")

    def make_subject(self, **overrides):
        defaults = dict(student=self.user, name="Req Score Subject", units=3,
                         passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        defaults.update(overrides)
        return Subject.objects.create(**defaults)

    def recommendation_for(self, subject, cs_assessments, major_exams, target):
        ctx = ai_assistant.build_context(subject, cs_assessments, major_exams, f"Can I still get {target}?")
        ta = ctx["target_analysis"]
        return ta, ta["recommendation"]["class_standing"], ta["recommendation"]["major_exam"]

    def test_1_achievable_target_single_remaining_assessment_is_minimum_sufficient(self):
        # Major Exam fully locked (all three periods scored) -- Class
        # Standing's one pending activity is the only lever.
        subject = self.make_subject()
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM", score=18, highest_possible_score=20)
        pending = ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 2", grading_period="PRELIM", score=None, highest_possible_score=20)
        MajorExam.objects.create(subject=subject, grading_period="PRELIM", score=80, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="MIDTERM", score=80, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="FINAL", score=80, highest_possible_score=100)

        cs_assessments = list(subject.class_standing_assessments.all())
        major_exams = list(subject.major_exams.all())
        ta, cs_rec, me_rec = self.recommendation_for(subject, cs_assessments, major_exams, "1.75")

        self.assertEqual(ta["status"], "achievable")
        self.assertEqual(cs_rec["type"], "known_pending_assessment")
        self.assertEqual(cs_rec["assessment_name"], "Activity 2")
        self.assertFalse(cs_rec["is_estimate"])
        # Major Exam is fully locked (all three periods scored) -- it still
        # reports its current standing, but offers no remaining-score lever.
        self.assertEqual(me_rec["type"], "no_remaining_exams")
        required = Decimal(str(cs_rec["required_score"]))
        self.assertGreater(required, 0)

        # The recommended score, applied to the pending assessment, must
        # reach the target; one hundredth of a point below must not.
        pending.score = required
        pending.save()
        result_ok = calculate_grade(subject, list(subject.class_standing_assessments.all()), major_exams)
        required_ca = build_target_plan(subject, cs_assessments, major_exams, "1.75").required_ca
        self.assertGreaterEqual(result_ok.computed_average, required_ca)

        pending.score = required - Decimal("0.01")
        pending.save()
        result_short = calculate_grade(subject, list(subject.class_standing_assessments.all()), major_exams)
        self.assertLess(result_short.computed_average, required_ca)

    def test_2_achievable_target_both_components_remaining_reaches_target_together(self):
        subject = self.make_subject()
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM", score=15, highest_possible_score=20)
        pending_cs = ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 2", grading_period="PRELIM", score=None, highest_possible_score=20)
        MajorExam.objects.create(subject=subject, grading_period="PRELIM", score=70, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="MIDTERM", score=70, highest_possible_score=100)
        pending_me = MajorExam.objects.create(
            subject=subject, grading_period="FINAL", score=None, highest_possible_score=100)

        cs_assessments = list(subject.class_standing_assessments.all())
        major_exams = list(subject.major_exams.all())
        ta, cs_rec, me_rec = self.recommendation_for(subject, cs_assessments, major_exams, "1.75")

        self.assertEqual(ta["status"], "achievable")
        self.assertTrue(cs_rec.get("combined_with_major_exam"))
        self.assertTrue(me_rec.get("combined_with_class_standing"))

        pending_cs.score = Decimal(str(cs_rec["required_score"]))
        pending_cs.save()
        pending_me.score = Decimal(str(me_rec["required_score"]))
        pending_me.save()

        required_ca = build_target_plan(subject, cs_assessments, major_exams, "1.75").required_ca
        result = calculate_grade(
            subject, list(subject.class_standing_assessments.all()), list(subject.major_exams.all()))
        self.assertGreaterEqual(result.computed_average, required_ca)

    def test_3_impossible_target_preserves_true_requirement_beyond_maximum(self):
        # Major Exam fully locked (mediocre); only Class Standing's one
        # pending activity remains -- the only lever, and even a perfect
        # score on it cannot reach a 1.00.
        subject = self.make_subject()
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM", score=10, highest_possible_score=20)
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 2", grading_period="PRELIM", score=None, highest_possible_score=20)
        MajorExam.objects.create(subject=subject, grading_period="PRELIM", score=60, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="MIDTERM", score=60, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="FINAL", score=60, highest_possible_score=100)

        cs_assessments = list(subject.class_standing_assessments.all())
        major_exams = list(subject.major_exams.all())
        ta, cs_rec, me_rec = self.recommendation_for(subject, cs_assessments, major_exams, "1.00")

        self.assertEqual(ta["status"], "impossible")
        self.assertTrue(cs_rec["exceeds_maximum"])
        # The TRUE requirement must exceed the assessment's own maximum --
        # never silently replaced by the maximum itself.
        self.assertGreater(Decimal(str(cs_rec["required_score"])), Decimal(str(cs_rec["assessment_max_score"])))

    def test_4_pending_major_exam_alone_is_minimum_sufficient(self):
        # Class Standing fully locked; the sole remaining Final exam (a real,
        # already-stored HPS) is the only lever.
        subject = self.make_subject()
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM", score=19, highest_possible_score=20)
        MajorExam.objects.create(subject=subject, grading_period="PRELIM", score=85, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="MIDTERM", score=85, highest_possible_score=100)
        pending_exam = MajorExam.objects.create(
            subject=subject, grading_period="FINAL", score=None, highest_possible_score=100)

        cs_assessments = list(subject.class_standing_assessments.all())
        major_exams = list(subject.major_exams.all())
        ta, cs_rec, me_rec = self.recommendation_for(subject, cs_assessments, major_exams, "1.25")

        # Class Standing has no real pending assessment, but one prior score
        # exists, so a hypothetical next-assessment estimate is still offered.
        self.assertEqual(cs_rec["type"], "inferred_next_assessment")
        self.assertTrue(cs_rec["is_estimate"])
        self.assertEqual(me_rec["type"], "known_remaining_exam")
        self.assertEqual(me_rec["exam_period_label"], "Final")
        required = Decimal(str(me_rec["required_score"]))

        required_ca = build_target_plan(subject, cs_assessments, major_exams, "1.25").required_ca
        pending_exam.score = required
        pending_exam.save()
        result_ok = calculate_grade(subject, cs_assessments, list(subject.major_exams.all()))
        self.assertGreaterEqual(result_ok.computed_average, required_ca)

        pending_exam.score = required - Decimal("0.01")
        pending_exam.save()
        result_short = calculate_grade(subject, cs_assessments, list(subject.major_exams.all()))
        self.assertLess(result_short.computed_average, required_ca)

    def test_5_hps_inference_uses_most_common_value_not_the_historical_maximum(self):
        subject = self.make_subject()
        # HPS pattern 50, 40, 40, 20 -- the maximum is 50, but the MOST
        # COMMON value is 40. The estimate must follow the pattern, not
        # simply take max(previous_hps).
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM", score=45, highest_possible_score=50)
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 2", grading_period="PRELIM", score=35, highest_possible_score=40)
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 3", grading_period="PRELIM", score=36, highest_possible_score=40)
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 4", grading_period="PRELIM", score=18, highest_possible_score=20)
        MajorExam.objects.create(subject=subject, grading_period="PRELIM", score=80, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="MIDTERM", score=80, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="FINAL", score=80, highest_possible_score=100)

        cs_assessments = list(subject.class_standing_assessments.all())
        major_exams = list(subject.major_exams.all())
        ta, cs_rec, me_rec = self.recommendation_for(subject, cs_assessments, major_exams, "1.75")

        self.assertEqual(cs_rec["type"], "inferred_next_assessment")
        self.assertTrue(cs_rec["is_estimate"])
        self.assertEqual(Decimal(str(cs_rec["assessment_max_score"])), Decimal("40"))
        self.assertEqual(
            [Decimal(str(v)) for v in cs_rec["inferred_from_past_maximum_scores"]],
            [Decimal("50"), Decimal("40"), Decimal("40"), Decimal("20")])

    def test_6_known_pending_assessment_uses_its_real_stored_hps(self):
        subject = self.make_subject()
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM", score=45, highest_possible_score=50)
        pending = ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 2", grading_period="PRELIM", score=None, highest_possible_score=35)
        MajorExam.objects.create(subject=subject, grading_period="PRELIM", score=80, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="MIDTERM", score=80, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="FINAL", score=80, highest_possible_score=100)

        cs_assessments = list(subject.class_standing_assessments.all())
        major_exams = list(subject.major_exams.all())
        ta, cs_rec, me_rec = self.recommendation_for(subject, cs_assessments, major_exams, "1.75")

        self.assertEqual(cs_rec["type"], "known_pending_assessment")
        self.assertFalse(cs_rec["is_estimate"])
        # The real, stored HPS (35) must be used -- not an inferred/guessed one.
        self.assertEqual(Decimal(str(cs_rec["assessment_max_score"])), Decimal("35"))

    def test_7_no_hypothetical_offered_without_any_scored_assessment_to_infer_from(self):
        subject = self.make_subject()
        # No Class Standing assessments recorded at all -- there is no
        # pattern to infer a hypothetical next assessment's HPS from.
        MajorExam.objects.create(subject=subject, grading_period="PRELIM", score=70, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="MIDTERM", score=70, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="FINAL", score=70, highest_possible_score=100)

        cs_assessments = list(subject.class_standing_assessments.all())
        major_exams = list(subject.major_exams.all())
        ta, cs_rec, me_rec = self.recommendation_for(subject, cs_assessments, major_exams, "1.75")

        self.assertEqual(cs_rec["type"], "no_data_to_recommend")
        self.assertNotIn("required_score", cs_rec)

    def test_8_recommendation_never_equals_a_silently_capped_maximum(self):
        # Regression guard for the reported bug: recommended_score/max_score
        # capping. Construct a case where the true requirement is strictly
        # between 0 and the maximum, and confirm it is NOT simply the max.
        subject = self.make_subject()
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM", score=15, highest_possible_score=20)
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 2", grading_period="PRELIM", score=None, highest_possible_score=20)
        MajorExam.objects.create(subject=subject, grading_period="PRELIM", score=80, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="MIDTERM", score=80, highest_possible_score=100)
        MajorExam.objects.create(subject=subject, grading_period="FINAL", score=80, highest_possible_score=100)

        cs_assessments = list(subject.class_standing_assessments.all())
        major_exams = list(subject.major_exams.all())
        ta, cs_rec, me_rec = self.recommendation_for(subject, cs_assessments, major_exams, "1.75")

        required = Decimal(str(cs_rec["required_score"]))
        maximum = Decimal(str(cs_rec["assessment_max_score"]))
        self.assertFalse(cs_rec["exceeds_maximum"])
        self.assertGreater(required, Decimal("0"))
        self.assertLess(required, maximum)


class GreatBooksRegressionTests(TestCase):
    """Regression coverage for a real, reported case: a subject with Class
    Standing 50/50, 38/40, 17/20, 40/50 and Major Exams Prelim 45/50,
    Midterm 46/50, Final pending/100, target grade 1.00. Uses the exact
    input data reported -- not a synthetic approximation."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="greatbooks", password="pass12345")
        self.subject = Subject.objects.create(
            student=self.user, name="Great Books Regression", units=3,
            passing_average=50, class_standing_percent_share=70, major_exam_percent_share=30)
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 1", grading_period="PRELIM", score=50, highest_possible_score=50)
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 2", grading_period="PRELIM", score=38, highest_possible_score=40)
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 3", grading_period="MIDTERM", score=17, highest_possible_score=20)
        ClassStandingAssessment.objects.create(
            subject=self.subject, name="Activity 4", grading_period="MIDTERM", score=40, highest_possible_score=50)
        MajorExam.objects.create(subject=self.subject, grading_period="PRELIM", score=45, highest_possible_score=50)
        MajorExam.objects.create(subject=self.subject, grading_period="MIDTERM", score=46, highest_possible_score=50)
        MajorExam.objects.create(subject=self.subject, grading_period="FINAL", score=None, highest_possible_score=100)
        self.cs_assessments = list(self.subject.class_standing_assessments.all())
        self.major_exams = list(self.subject.major_exams.all())

    def test_1_current_class_standing_is_145_of_160(self):
        cs = class_standing_breakdown(self.cs_assessments)
        self.assertEqual(cs.scored_points, Decimal("145"))
        self.assertEqual(cs.scored_hps, Decimal("160"))
        self.assertAlmostEqual(float(cs.current_average), 90.625, places=3)

    def test_2_final_exam_is_pending_not_91_of_100(self):
        ctx = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        final = next(e for e in ctx["major_exams"] if e["grading_period"] == "FINAL")
        self.assertIsNone(final["score"])
        self.assertFalse(final["scored_yet"])

        me_rec = ctx["target_analysis"]["recommendation"]["major_exam"]
        # 91/100 is real (Prelim+Midterm combined) but must never be
        # presented as the Final exam's own score.
        self.assertEqual(me_rec["completed_major_exams_points"], 91.0)
        self.assertEqual(me_rec["completed_major_exams_possible"], 100.0)
        self.assertIn("not the score of the remaining", me_rec["completed_major_exams_note"])
        self.assertEqual(me_rec["exam_period_label"], "Final")
        self.assertNotIn("current_earned_points", me_rec)  # old, ambiguous key must be gone

    def test_3_global_maximum_uses_only_real_database_rows(self):
        cs = class_standing_breakdown(self.cs_assessments)
        me = major_exam_breakdown(self.major_exams)
        max_ca, max_tv, max_grade = best_possible(self.subject, cs, me)

        # No real pending Class Standing assessment exists -> its ceiling
        # cannot move past what is already scored.
        self.assertFalse(cs.has_remaining)
        self.assertEqual(cs.max_average, cs.current_average)
        # Major Exam's ceiling correctly assumes a perfect Final (100/100),
        # the one real pending row.
        self.assertEqual(me.max_average, Decimal("94.00"))
        # 0.70 * 90.625 + 0.30 * 94.00
        self.assertEqual(max_ca, Decimal("90.625") * Decimal("0.70") + Decimal("94.00") * Decimal("0.30"))
        self.assertAlmostEqual(float(max_ca), 91.6375, places=3)

    def test_4_target_1_00_is_open_not_impossible_while_the_term_is_unfinished(self):
        plan = build_target_plan(self.subject, self.cs_assessments, self.major_exams, "1.00")
        self.assertEqual(plan.required_ca, Decimal("94.0000"))
        # The Final grading period has not happened yet (its Major Exam is
        # unscored and it has no Class Standing rows), so Class Standing is
        # still open. "impossible" would be wrong: it would be treating
        # "not entered yet" as "cannot be earned".
        self.assertEqual(plan.status, "open")
        self.assertTrue(plan.cs_open)
        self.assertEqual(plan.open_periods, ("FINAL",))
        # max_ca stays database-grounded and still falls short -- that is
        # exactly why the status is "open" rather than "achievable".
        self.assertLess(plan.max_ca, plan.required_ca)

        # The plan states the real requirement: finish Class Standing at
        # 94.00% (with a perfect Final exam), which takes 90 more perfect
        # Class Standing points.
        self.assertEqual(plan.cs_required_avg_with_best_exams, Decimal("94.00"))
        self.assertEqual(plan.perfect_cs_points_needed, Decimal("90"))

        # Proof by construction: 90 more perfect points plus a perfect Final
        # exam reaches 1.00 through the real, unmodified calculate_grade().
        final_exam = next(e for e in self.major_exams if e.grading_period == "FINAL")
        final_exam.score = final_exam.highest_possible_score
        future = ClassStandingAssessment(
            subject=self.subject, name="Future", grading_period="FINAL",
            score=Decimal("90"), highest_possible_score=Decimal("90"))
        reached = calculate_grade(self.subject, self.cs_assessments + [future], self.major_exams)
        self.assertEqual(reached.current_grade, "1.00")
        final_exam.score = None  # restore

    def test_5_no_hypothetical_value_is_presented_as_an_actual_stored_score(self):
        ctx = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        cs_rec = ctx["target_analysis"]["recommendation"]["class_standing"]
        self.assertTrue(cs_rec["is_estimate"])
        self.assertEqual(cs_rec["prediction_basis"], "Most common historical Class Standing HPS")
        self.assertEqual(cs_rec["assessment_max_score"], 50.0)
        # The four real, already-entered assessments are exactly what is in
        # the database -- nothing extra was invented.
        names = {a["name"] for a in ctx["class_standing_assessments"]}
        self.assertEqual(names, {"Activity 1", "Activity 2", "Activity 3", "Activity 4"})

    def test_6_open_term_recommends_full_marks_not_an_impossible_score(self):
        # While a grading period is still unentered, no single item can carry
        # the target, so an "alone" solve would print an absurd score like
        # 55.10 / 50.00. The open-term plan recommends full marks on what
        # exists and states the end-of-term requirement separately.
        ctx = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        cs_rec = ctx["target_analysis"]["recommendation"]["class_standing"]
        me_rec = ctx["target_analysis"]["recommendation"]["major_exam"]

        self.assertEqual(cs_rec["type"], "open_term_next_activity")
        self.assertFalse(cs_rec["exceeds_maximum"])
        self.assertEqual(cs_rec["required_score"], cs_rec["assessment_max_score"])
        self.assertEqual(cs_rec["class_standing_average_needed_by_end_of_term"], 94.0)
        self.assertEqual(cs_rec["additional_perfect_points_needed"], 90.0)
        self.assertTrue(cs_rec["one_activity_is_not_enough"])

        self.assertEqual(me_rec["type"], "open_term_remaining_exam")
        self.assertFalse(me_rec["exceeds_maximum"])
        self.assertEqual(me_rec["required_score"], me_rec["assessment_max_score"])

    def test_7_impossible_target_does_not_assume_a_single_combined_split(self):
        # Class Standing has no REAL pending row (only a hypothetical), so
        # the two components must be evaluated independently, each holding
        # the other at its real current value -- not silently forced into
        # one combined split, which would require a real lever on both sides.
        ctx = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        cs_rec = ctx["target_analysis"]["recommendation"]["class_standing"]
        me_rec = ctx["target_analysis"]["recommendation"]["major_exam"]
        self.assertNotIn("combined_with_major_exam", cs_rec)
        self.assertNotIn("combined_with_class_standing", me_rec)

    def test_8_recommendation_verified_against_the_real_grading_calculation(self):
        # A pending exam is EXCLUDED from the weighted Major Exam average
        # entirely (different denominator: two weights, not three), so
        # "currently on track without Final" is not the same question as
        # "what score keeps the target met once Final IS scored" -- scoring
        # Final at 0 actually pulls the three-exam average down and can miss
        # the target even though the *current* (Final-excluded) standing
        # already clears it. required_score is Django's answer to the real
        # question ("once scored, what is the minimum"), verified here by
        # applying it (and one cent less) through the actual calculate_grade().
        plan = build_target_plan(self.subject, self.cs_assessments, self.major_exams, "1.50")
        ctx = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "What do I need to get a 1.50?")
        me_rec = ctx["target_analysis"]["recommendation"]["major_exam"]
        self.assertFalse(me_rec["already_sufficient"])
        self.assertFalse(me_rec["exceeds_maximum"])
        required = Decimal(str(me_rec["required_score"]))

        final_exam = next(e for e in self.major_exams if e.grading_period == "FINAL")
        final_exam.score = required
        result_ok = calculate_grade(self.subject, self.cs_assessments, self.major_exams)
        self.assertGreaterEqual(result_ok.computed_average, plan.required_ca)

        final_exam.score = required - Decimal("0.01")
        result_short = calculate_grade(self.subject, self.cs_assessments, self.major_exams)
        self.assertLess(result_short.computed_average, plan.required_ca)

        # A pending Final (score=None, excluded from the average) is not the
        # same as a Final scored at 0 (included, dragging the average down)
        # -- confirm this distinction holds for the real data.
        final_exam.score = Decimal("0")
        result_zero = calculate_grade(self.subject, self.cs_assessments, self.major_exams)
        self.assertLess(result_zero.computed_average, plan.required_ca)
        final_exam.score = None  # restore (genuinely pending)

        # Minimum-sufficiency itself (recommended score succeeds, one cent
        # less fails) is proven with data where an achievable target
        # genuinely requires improvement -- see
        # RequiredScoreRecommendationTests.test_1 / test_4, which use
        # synthetic data specifically constructed to sit in that window.

    def test_9_estimated_activity_never_affects_the_global_maximum(self):
        # Requirement D: the ESTIMATED next Class Standing activity (HPS 50,
        # inferred from history) must never be folded into cs.max_average /
        # plan.max_ca -- those must reflect only real database rows. Proven
        # two ways: (a) cs.max_average equals cs.current_average exactly
        # (nothing pending in the DB to raise it), and (b) plan.max_ca is
        # unaffected no matter which target grade is asked about, since the
        # estimate is recomputed fresh per question and never persisted.
        cs = class_standing_breakdown(self.cs_assessments)
        self.assertFalse(cs.has_remaining)
        self.assertEqual(cs.max_average, cs.current_average)
        self.assertEqual(cs.max_average, Decimal("90.625"))

        for target in ("1.00", "1.25", "1.50", "1.75"):
            plan = build_target_plan(self.subject, self.cs_assessments, self.major_exams, target)
            self.assertEqual(plan.max_ca, Decimal("91.6375000"))

    def test_10_prediction_basis_is_explicit_and_explainable(self):
        ctx = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        cs_rec = ctx["target_analysis"]["recommendation"]["class_standing"]
        self.assertEqual(cs_rec["prediction_basis"], "Most common historical Class Standing HPS")

    def test_11_predicted_activity_never_mutates_the_database(self):
        # Requirement: prediction must never insert or alter a real row.
        before_count = self.subject.class_standing_assessments.count()
        ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        after_count = self.subject.class_standing_assessments.count()
        self.assertEqual(before_count, after_count)
        # And the four real rows are byte-for-byte what was entered.
        real = list(self.subject.class_standing_assessments.order_by("id").values_list(
            "name", "score", "highest_possible_score"))
        self.assertEqual(real, [
            ("Activity 1", Decimal("50.00"), Decimal("50.00")),
            ("Activity 2", Decimal("38.00"), Decimal("40.00")),
            ("Activity 3", Decimal("17.00"), Decimal("20.00")),
            ("Activity 4", Decimal("40.00"), Decimal("50.00")),
        ])

    def test_12_display_value_for_target_1_00_is_open_with_a_stated_requirement(self):
        # What the "Status:" line's rounded display value and verdict will
        # actually be for a 1.00 target on this exact real data.
        ctx = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        ta = ctx["target_analysis"]
        self.assertEqual(ta["status"], "open")
        self.assertEqual(ta["supporting_details"]["maximum_possible_computed_average"], 91.64)
        self.assertEqual(ta["supporting_details"]["maximum_possible_grade"], "1.25")
        self.assertEqual(ta["supporting_details"]["required_computed_average"], 94.0)

    def test_13_required_percent_is_present_and_correct_for_both_scenarios(self):
        # The percentage now folded into the "Recommended score" sentence
        # (e.g. "55.10 / 50.00 (110.20%)") must be Django-computed, not left
        # for Gemini to calculate.
        ctx = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        cs_rec = ctx["target_analysis"]["recommendation"]["class_standing"]
        me_rec = ctx["target_analysis"]["recommendation"]["major_exam"]
        self.assertEqual(
            cs_rec["required_percent"],
            round(cs_rec["required_score"] / cs_rec["assessment_max_score"] * 100, 2))
        self.assertEqual(
            me_rec["required_percent"],
            round(me_rec["required_score"] / me_rec["assessment_max_score"] * 100, 2))
        # Open term: full marks on what exists, never a fabricated >100% score.
        self.assertEqual(cs_rec["required_percent"], 100.0)
        self.assertEqual(me_rec["required_percent"], 100.0)

    def test_14_maximum_possible_block_signal_differs_by_status(self):
        # The "Maximum possible result" block is now a prompt-level
        # decision keyed on target_analysis.status -- confirm the
        # underlying signal is correct for both an impossible and an
        # achievable target on this same real subject.
        ctx_open = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "Can I still get 1.00?")
        self.assertEqual(ctx_open["target_analysis"]["status"], "open")

        ctx_achievable = ai_assistant.build_context(
            self.subject, self.cs_assessments, self.major_exams, "What do I need to get a 1.50?")
        self.assertEqual(ctx_achievable["target_analysis"]["status"], "achievable")


class SubjectWeightingTests(TestCase):
    """The Class Standing / Major Examination split is a per-subject setting:
    some subjects are 70/30, others 60/40. It must be selectable, editable
    after creation, and impossible to save in a state the grading formula
    cannot handle."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="weights", password="pass12345")
        self.client.login(username="weights", password="pass12345")

    def _base(self, **overrides):
        data = {"name": "Subj", "units": "3", "passing_average": "50",
                "class_standing_percent_share": "70", "major_exam_percent_share": "30",
                "share_preset": "custom"}
        data.update(overrides)
        return data

    def test_shares_that_do_not_total_100_are_rejected(self):
        # 70 + 40 would make the grading formula return ~99.84% for work that
        # is nowhere near it, handing out an unearned 1.00.
        form = SubjectForm(data=self._base(major_exam_percent_share="40"))
        self.assertFalse(form.is_valid())
        self.assertIn("100", str(form.non_field_errors()))

    def test_custom_split_totalling_100_is_accepted(self):
        form = SubjectForm(data=self._base(
            class_standing_percent_share="55", major_exam_percent_share="45"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_60_40_preset_overrides_the_number_inputs(self):
        form = SubjectForm(data=self._base(share_preset="60_40",
                                           class_standing_percent_share="70",
                                           major_exam_percent_share="30"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["class_standing_percent_share"], Decimal("60"))
        self.assertEqual(form.cleaned_data["major_exam_percent_share"], Decimal("40"))

    def test_subject_can_be_switched_to_60_40_without_losing_scores(self):
        subject = Subject.objects.create(
            student=self.user, name="Switchable", units=3, passing_average=50,
            class_standing_percent_share=70, major_exam_percent_share=30)
        ClassStandingAssessment.objects.create(
            subject=subject, name="Activity 1", grading_period="PRELIM",
            score=45, highest_possible_score=50)
        MajorExam.objects.create(
            subject=subject, grading_period="PRELIM", score=40,
            highest_possible_score=50)

        response = self.client.post(
            reverse("subjects:subject_update", args=[subject.pk]),
            self._base(name="Switchable", share_preset="60_40"))
        self.assertEqual(response.status_code, 302)

        subject.refresh_from_db()
        self.assertEqual(subject.class_standing_percent_share, Decimal("60.00"))
        self.assertEqual(subject.major_exam_percent_share, Decimal("40.00"))
        # Editing settings must never disturb recorded work.
        self.assertEqual(subject.class_standing_assessments.count(), 1)
        self.assertEqual(subject.major_exams.get(grading_period="PRELIM").score, Decimal("40.00"))

    def test_edit_form_reopens_on_the_subject_s_own_preset(self):
        subject = Subject.objects.create(
            student=self.user, name="SixtyForty", units=3, passing_average=50,
            class_standing_percent_share=60, major_exam_percent_share=40)
        response = self.client.get(reverse("subjects:subject_update", args=[subject.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["share_preset"].value(), "60_40")

    def test_another_student_cannot_edit_someone_else_s_subject(self):
        other = get_user_model().objects.create_user(username="other", password="pass12345")
        subject = Subject.objects.create(
            student=other, name="Theirs", units=3, passing_average=50,
            class_standing_percent_share=70, major_exam_percent_share=30)
        response = self.client.post(
            reverse("subjects:subject_update", args=[subject.pk]),
            self._base(share_preset="60_40"))
        subject.refresh_from_db()
        self.assertEqual(subject.class_standing_percent_share, Decimal("70.00"))


class IndependentScenarioTests(TestCase):
    """Guards the trap that following BOTH per-component recommendations at
    once undershoots the target: each figure is solved holding the OTHER
    component at its current rate, so they are alternative routes, not two
    halves of one plan."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="scenarios", password="pass12345")
        self.subject = Subject.objects.create(
            student=self.user, name="Great Books", units=3, passing_average=50,
            class_standing_percent_share=70, major_exam_percent_share=30)
        for name, period, score, hps in [
            ("Activity 1", "PRELIM", 50, 50), ("Activity 2", "PRELIM", 38, 40),
            ("Activity 3", "MIDTERM", 17, 20), ("Activity 4", "MIDTERM", 40, 50)]:
            ClassStandingAssessment.objects.create(
                subject=self.subject, name=name, grading_period=period,
                score=score, highest_possible_score=hps)
        for period, score in [("PRELIM", 45), ("MIDTERM", 46)]:
            MajorExam.objects.create(
                subject=self.subject, grading_period=period, score=score,
                highest_possible_score=50)
        MajorExam.objects.create(
            subject=self.subject, grading_period="FINAL", score=None,
            highest_possible_score=100)
        self.cs = list(self.subject.class_standing_assessments.all())
        self.me = list(self.subject.major_exams.all())

    def _recs(self, target):
        ctx = ai_assistant.build_context(self.subject, self.cs, self.me, f"What do I need for {target}?")
        rec = ctx["target_analysis"]["recommendation"]
        return rec["class_standing"], rec["major_exam"]

    def test_both_recommendations_are_flagged_as_standalone_scenarios(self):
        cs_rec, me_rec = self._recs("1.50")
        self.assertTrue(cs_rec["is_standalone_scenario"])
        self.assertTrue(me_rec["is_standalone_scenario"])
        # Each states the rate it holds the other component at, so the
        # answer can name the assumption instead of implying a joint plan.
        self.assertAlmostEqual(cs_rec["assumes_major_exam_average_stays_at"], 91.0, places=2)
        self.assertAlmostEqual(me_rec["assumes_class_standing_average_stays_at"], 90.62, places=2)

    def test_each_recommendation_alone_reaches_the_target(self):
        cs_rec, me_rec = self._recs("1.50")
        required = minimum_computed_average_for_grade("1.50", self.subject.passing_average)

        final = next(e for e in self.me if e.grading_period == "FINAL")
        final.score = Decimal(str(me_rec["required_score"]))
        exam_only = calculate_grade(self.subject, self.cs, self.me)
        self.assertGreaterEqual(exam_only.computed_average, required)

        # And the class-standing route, with the exam held at its current rate.
        final.score = Decimal("91")
        nxt = ClassStandingAssessment(
            subject=self.subject, name="next", grading_period="FINAL",
            score=Decimal(str(cs_rec["required_score"])),
            highest_possible_score=Decimal(str(cs_rec["assessment_max_score"])))
        activity_only = calculate_grade(self.subject, self.cs + [nxt], self.me)
        self.assertGreaterEqual(activity_only.computed_average, required)
        final.score = None

    def test_doing_both_minimums_together_undershoots(self):
        # The exact failure mode the wording must prevent: 19.1/50 plus
        # 3.63/100 reads like a to-do list but lands on a 2.00.
        cs_rec, me_rec = self._recs("1.50")
        required = minimum_computed_average_for_grade("1.50", self.subject.passing_average)

        final = next(e for e in self.me if e.grading_period == "FINAL")
        final.score = Decimal(str(me_rec["required_score"]))
        nxt = ClassStandingAssessment(
            subject=self.subject, name="next", grading_period="FINAL",
            score=Decimal(str(cs_rec["required_score"])),
            highest_possible_score=Decimal(str(cs_rec["assessment_max_score"])))
        both = calculate_grade(self.subject, self.cs + [nxt], self.me)
        final.score = None
        self.assertLess(both.computed_average, required)


class AlreadySufficientTests(IndependentScenarioTests):
    """A target both components already cover is still not locked in: each
    "no minimum needed" holds only while the OTHER component stays put."""

    def test_both_sufficient_is_flagged_for_the_combined_warning(self):
        ctx = ai_assistant.build_context(
            self.subject, self.cs, self.me, "What do I need for 2.00?")
        details = ctx["target_analysis"]["supporting_details"]
        self.assertTrue(details["both_components_already_sufficient"])

    def test_zero_on_either_item_alone_still_holds_the_target(self):
        required = minimum_computed_average_for_grade("2.00", self.subject.passing_average)
        final = next(e for e in self.me if e.grading_period == "FINAL")

        final.score = Decimal("0")
        self.assertGreaterEqual(
            calculate_grade(self.subject, self.cs, self.me).computed_average, required)

        final.score = Decimal("91")
        flunked = ClassStandingAssessment(
            subject=self.subject, name="next", grading_period="FINAL",
            score=Decimal("0"), highest_possible_score=Decimal("50"))
        self.assertGreaterEqual(
            calculate_grade(self.subject, self.cs + [flunked], self.me).computed_average, required)
        final.score = None

    def test_zero_on_both_items_together_loses_the_target(self):
        # Why "any score here keeps you on track" was the wrong wording.
        required = minimum_computed_average_for_grade("2.00", self.subject.passing_average)
        final = next(e for e in self.me if e.grading_period == "FINAL")
        final.score = Decimal("0")
        flunked = ClassStandingAssessment(
            subject=self.subject, name="next", grading_period="FINAL",
            score=Decimal("0"), highest_possible_score=Decimal("50"))
        both = calculate_grade(self.subject, self.cs + [flunked], self.me)
        final.score = None
        self.assertLess(both.computed_average, required)


class ResponseTextTests(IndependentScenarioTests):
    """The Status, Note, heading and Tip lines are composed in Python and
    quoted verbatim, so their correctness is testable instead of depending
    on the model following a prompt."""

    def _details(self, target):
        ctx = ai_assistant.build_context(
            self.subject, self.cs, self.me, f"Can I still get {target}?")
        return ctx["target_analysis"]["supporting_details"]

    def test_every_composed_line_is_present_for_every_target(self):
        for target in ("1.00", "1.25", "1.50", "1.75", "2.00"):
            details = self._details(target)
            for key in ("status_text", "class_standing_note",
                        "major_exam_note", "tip_text", "class_standing_heading"):
                self.assertTrue(details.get(key), f"{key} missing for {target}")

    def test_estimated_activity_is_disclosed_on_every_target(self):
        # The 50-pt activity does not exist in the database. A student must
        # never see it presented as a scheduled task, whichever grade they ask
        # about.
        for target in ("1.00", "1.25", "1.50", "1.75", "2.00"):
            self.assertIn("Estimated", self._details(target)["class_standing_heading"])

    def test_open_target_status_does_not_claim_plain_achievable(self):
        details = self._details("1.00")
        self.assertIn("additional future activities", details["status_text"])

    def test_combined_warning_appears_only_when_both_minimums_are_real(self):
        # 1.50: two real minimums -> the warning matters.
        self.assertIn("not both", self._details("1.50")["class_standing_note"])
        # 2.00: neither is needed -> a "pick one route" warning would be noise.
        self.assertNotIn("not both", self._details("2.00")["class_standing_note"])

    def test_open_note_reports_the_projected_average_and_the_remainder(self):
        note = self._details("1.00")["class_standing_note"]
        self.assertIn("92.86%", note)   # where a perfect next activity lands
        self.assertIn("94.0%", note)    # what the term must finish at
        self.assertIn("40.0", note)     # points still needed after that


class AssistantScopeTests(TestCase):
    """The assistant answers one subject at a time. Off a subject page there
    is nothing whose recorded scores could ground an answer, so the modal
    must offer a picker rather than a question box."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="scope", password="pass12345")
        self.client.force_login(self.user)

    def make(self, name):
        return Subject.objects.create(
            student=self.user, name=name, units=3, passing_average=50,
            class_standing_percent_share=70, major_exam_percent_share=30)

    def test_modal_on_a_subject_page_reaches_only_that_subject(self):
        a, b = self.make("Algebra"), self.make("Great Books")
        body = self.client.get(reverse("subjects:subject_detail", args=[a.pk])).content.decode()

        self.assertIn("Answering about Algebra", body)
        self.assertIn(reverse("subjects:ai_assistant_ask", args=[a.pk]), body)
        self.assertNotIn(reverse("subjects:ai_assistant_ask", args=[b.pk]), body)
        self.assertNotIn("Choose a subject to ask about", body)

    def test_modal_off_a_subject_page_offers_a_picker_and_no_question_box(self):
        a, b = self.make("Algebra"), self.make("Great Books")
        for url in (reverse("subjects:dashboard"), reverse("subjects:subject_list")):
            body = self.client.get(url).content.decode()
            self.assertIn("Choose a subject to ask about", body)
            self.assertIn('class="ai-subject-list"', body)
            for subject in (a, b):
                self.assertIn(reverse("subjects:subject_detail", args=[subject.pk]) + "?ask=1", body)
            self.assertNotIn('id="ai-assistant-form"', body)
            self.assertNotIn('id="ai-question-input"', body)

    def test_sidebar_has_no_assistant_entry(self):
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        sidebar = body[body.index('<nav class="sidebar-nav"'):body.index("</nav>")]
        self.assertNotIn("AI Assistant", sidebar)

    def test_dashboard_has_no_separate_assistant_banner(self):
        self.make("Algebra")
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        self.assertNotIn("assist-banner", body)
        self.assertNotIn("Open assistant", body)

    def test_modal_without_subjects_points_at_adding_one(self):
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        self.assertIn("No subjects yet", body)
        self.assertNotIn('id="ai-assistant-form"', body)


class SubjectNavigationTests(TestCase):
    """Home answers "what was I just working on"; the subjects page is the
    full A-to-Z roster. They are different questions, so the two lists are
    not duplicates."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="nav", password="pass12345")
        self.client.force_login(self.user)

    def make(self, name):
        return Subject.objects.create(
            student=self.user, name=name, units=3, passing_average=50,
            class_standing_percent_share=70, major_exam_percent_share=30)

    def test_subject_list_is_alphabetical(self):
        for name in ("Zoology", "algebra", "Great Books"):
            self.make(name)
        rows = self.client.get(reverse("subjects:subject_list")).context["rows"]
        self.assertEqual([s.name for s, _ in rows], ["algebra", "Great Books", "Zoology"])

    def test_home_shows_most_recently_opened_first(self):
        a, b, c = self.make("Algebra"), self.make("Biology"), self.make("Chemistry")
        for subject in (a, b, c):
            self.client.get(reverse("subjects:subject_detail", args=[subject.pk]))
        # Re-open the first one; it should jump to the front.
        self.client.get(reverse("subjects:subject_detail", args=[a.pk]))

        rows = self.client.get(reverse("subjects:dashboard")).context["rows"]
        self.assertEqual([s.name for s, _ in rows], ["Algebra", "Chemistry", "Biology"])

    def test_home_omits_subjects_never_opened(self):
        opened = self.make("Opened")
        self.make("Never Opened")
        self.client.get(reverse("subjects:subject_detail", args=[opened.pk]))

        home = self.client.get(reverse("subjects:dashboard"))
        self.assertEqual([s.name for s, _ in home.context["rows"]], ["Opened"])
        # The full roster still lists both.
        rows = self.client.get(reverse("subjects:subject_list")).context["rows"]
        self.assertEqual(len(rows), 2)

    def test_home_caps_the_recent_list(self):
        for i in range(RECENT_SUBJECT_COUNT + 3):
            subject = self.make(f"Subject {i:02d}")
            self.client.get(reverse("subjects:subject_detail", args=[subject.pk]))
        rows = self.client.get(reverse("subjects:dashboard")).context["rows"]
        self.assertEqual(len(rows), RECENT_SUBJECT_COUNT)

    def test_subject_card_links_straight_to_the_subject(self):
        subject = self.make("Great Books")
        body = self.client.get(reverse("subjects:subject_list")).content.decode()
        self.assertIn(reverse("subjects:subject_detail", args=[subject.pk]), body)
        # The whole card is the link now, so the extra button is gone.
        self.assertNotIn("View Details", body)

    def test_subject_page_has_no_all_subjects_breadcrumb(self):
        subject = self.make("Great Books")
        body = self.client.get(reverse("subjects:subject_detail", args=[subject.pk])).content.decode()
        self.assertNotIn("All Subjects", body)

    def test_sidebar_subjects_link_points_at_the_roster(self):
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        self.assertIn(reverse("subjects:subject_list"), body)
        self.assertNotIn("#subjects-section", body)


class ModalDismissTests(TestCase):
    """The assistant modal is toggled by setting the `hidden` attribute. An
    author `display` rule outranks the browser's built-in
    [hidden]{display:none}, so without an explicit override the modal can
    never be dismissed -- it renders permanently over the page."""

    def test_modal_starts_hidden_in_the_markup(self):
        user = get_user_model().objects.create_user(username="dismiss", password="pass12345")
        self.client.force_login(user)
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        start = body.index('class="ai-modal"')
        opening_tag = body[body.rindex("<", 0, start):body.index(">", start)]
        self.assertIn("hidden", opening_tag)

    def test_stylesheet_honours_the_hidden_attribute(self):
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".ai-modal{", css.replace(" ", ""))
        # The override must exist, or `hidden` is cosmetically ignored.
        self.assertIn(".ai-modal[hidden]{display:none}", css.replace(" ", ""))

    def test_close_controls_are_present(self):
        user = get_user_model().objects.create_user(username="dismiss2", password="pass12345")
        self.client.force_login(user)
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        # Both the X and the backdrop dismiss the modal.
        self.assertGreaterEqual(body.count("data-ai-close"), 2)


class TemplateCommentTests(TestCase):
    """Django's {# #} comment is single-line only. Spanning lines with it does
    not raise -- the tag is simply rendered to the page as visible text, so a
    scan is the only thing that catches it."""

    def test_no_multiline_hash_comments_in_any_template(self):
        offenders = []
        for path in (settings.BASE_DIR / "templates").rglob("*.html"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "{#" in line and "#}" not in line:
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual(offenders, [], f"Use {{% comment %}} for multi-line: {offenders}")

    def test_rendered_pages_leak_no_comment_markers(self):
        user = get_user_model().objects.create_user(username="comments", password="pass12345")
        self.client.force_login(user)
        subject = Subject.objects.create(
            student=user, name="Great Books", units=3, passing_average=50,
            class_standing_percent_share=70, major_exam_percent_share=30)
        for url in (reverse("subjects:dashboard"),
                    reverse("subjects:subject_list"),
                    reverse("subjects:subject_detail", args=[subject.pk])):
            body = self.client.get(url).content.decode()
            self.assertNotIn("{#", body)
            self.assertNotIn("#}", body)
            self.assertNotIn("{% comment", body)


class AuthPageTests(TestCase):
    """The login and signup pages render their fields directly rather than
    through {{ form.as_p }}, which appends a label_suffix and emits markup
    this stylesheet does not control."""

    def test_login_labels_carry_no_colon_suffix(self):
        body = self.client.get(reverse("login")).content.decode()
        self.assertIn("Username", body)
        self.assertNotIn("Username:", body)
        self.assertNotIn("Password:", body)

    def test_login_page_renders_styled_fields(self):
        body = self.client.get(reverse("login")).content.decode()
        self.assertIn('class="auth-panel"', body)
        self.assertIn('class="auth-field', body)
        self.assertIn("csrfmiddlewaretoken", body)

    def test_signup_labels_carry_no_colon_suffix(self):
        body = self.client.get(reverse("signup")).content.decode()
        self.assertNotIn("Username:", body)
        self.assertNotIn("Password confirmation:", body)

    def test_invalid_login_shows_an_error_in_the_page(self):
        response = self.client.post(reverse("login"), {"username": "nope", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auth-alert")

    def test_signup_field_errors_render_next_to_the_field(self):
        response = self.client.post(reverse("signup"), {
            "username": "newuser", "password1": "abc", "password2": "xyz"})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("auth-field has-error", body)
        self.assertIn('class="auth-error"', body)

    def test_brand_is_not_overridden_to_the_body_colour(self):
        # `.nav a{color:inherit}` outranks a bare `.brand{color:#fff}`, which
        # rendered the wordmark dark-on-maroon and effectively invisible.
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".nav .brand{", css)


class StylesheetSanityTests(TestCase):
    """Cheap guards for CSS mistakes that render wrong without erroring."""

    def css(self):
        return (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")

    def test_radios_are_exempt_from_the_full_width_input_rule(self):
        # `input,select{width:100%;...}` turns a bare radio into a wide
        # bordered box unless it is explicitly excluded.
        css = self.css().replace(" ", "")
        self.assertIn("input[type=radio]", css)
        self.assertIn("input[type=checkbox],input[type=radio]{width:auto", css)

    def test_no_undefined_custom_properties(self):
        # var(--name, fallback) fails silently: an undefined variable just
        # uses the fallback, which is how an off-palette indigo slipped into
        # the weighting selector.
        import re
        css = self.css()
        declared = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
        used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
        self.assertEqual(sorted(used - declared), [])


class EqualPeriodWeightTests(TestCase):
    """With the per-exam weight field gone, every grading period is one equal
    share of the Major Exam component -- regardless of how many points that
    period's paper happens to be out of."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="weights2", password="pass12345")
        self.subject = Subject.objects.create(
            student=self.user, name="Great Books", units=3, passing_average=50,
            class_standing_percent_share=70, major_exam_percent_share=30)

    def exam(self, period, score, hps):
        return MajorExam.objects.create(
            subject=self.subject, grading_period=period, score=score, highest_possible_score=hps)

    def test_a_bigger_paper_does_not_count_for_more(self):
        # Prelim and Midterm are out of 50, the Final out of 100. Equal
        # shares give (90 + 92 + 100) / 3 = 94.00. Summing raw points would
        # give 95.50, because the Final would carry double the weight.
        self.exam("PRELIM", 45, 50)
        self.exam("MIDTERM", 46, 50)
        self.exam("FINAL", 100, 100)
        breakdown = major_exam_breakdown(list(self.subject.major_exams.all()))
        self.assertEqual(breakdown.current_average.quantize(Decimal("0.01")), Decimal("94.00"))

    def test_unscored_periods_are_excluded_from_the_current_average(self):
        self.exam("PRELIM", 45, 50)
        self.exam("MIDTERM", 46, 50)
        self.exam("FINAL", None, 100)
        breakdown = major_exam_breakdown(list(self.subject.major_exams.all()))
        # (90 + 92) / 2, not (90 + 92 + 0) / 3.
        self.assertEqual(breakdown.current_average.quantize(Decimal("0.01")), Decimal("91.00"))
        self.assertEqual(breakdown.max_average.quantize(Decimal("0.01")), Decimal("94.00"))

    def test_single_exam_is_the_whole_component(self):
        self.exam("PRELIM", 80, 100)
        breakdown = major_exam_breakdown(list(self.subject.major_exams.all()))
        self.assertEqual(breakdown.current_average.quantize(Decimal("0.01")), Decimal("80.00"))

    def test_weight_input_is_gone_from_the_forms(self):
        self.client.force_login(self.user)
        body = self.client.get(reverse("subjects:subject_detail", args=[self.subject.pk])).content.decode()
        self.assertNotIn('name="weight"', body)
        self.assertNotIn("Weight %", body)
        body = self.client.get(reverse("subjects:subject_create")).content.decode()
        self.assertNotIn("_exam_weight", body)


class MultipleRemainingExamTests(TestCase):
    """When two or more major exams are unscored, "a single score cannot be
    given" is true but useless. The average the remaining papers must reach
    together is exact and actionable, so that is what gets reported."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="multi", password="pass12345")
        self.client.force_login(self.user)
        self.subject = Subject.objects.create(
            student=self.user, name="Subj", units=3, passing_average=50,
            class_standing_percent_share=60, major_exam_percent_share=40)
        for name, period, score, hps in [
            ("Seatwork", "PRELIM", 20, 20), ("Seatwork 2", "PRELIM", 20, 20),
            ("Quiz", "MIDTERM", 92, 100)]:
            ClassStandingAssessment.objects.create(
                subject=self.subject, name=name, grading_period=period,
                score=score, highest_possible_score=hps)
        MajorExam.objects.create(subject=self.subject, grading_period="PRELIM",
                                 score=67, highest_possible_score=100)
        for period in ("MIDTERM", "FINAL"):
            MajorExam.objects.create(subject=self.subject, grading_period=period,
                                     score=None, highest_possible_score=100)
        self.cs = list(self.subject.class_standing_assessments.all())
        self.me = list(self.subject.major_exams.all())

    def rec(self, target="1.25"):
        ctx = ai_assistant.build_context(self.subject, self.cs, self.me, f"Can I still get {target}?")
        return ctx["target_analysis"]

    def test_required_average_across_remaining_exams_is_reported(self):
        me_rec = self.rec()["recommendation"]["major_exam"]
        self.assertEqual(me_rec["type"], "multiple_remaining_exams")
        self.assertEqual(me_rec["remaining_count"], 2)
        self.assertAlmostEqual(me_rec["required_average_across_remaining"], 84.36, places=2)

    def test_that_average_actually_reaches_the_target(self):
        required = minimum_computed_average_for_grade("1.25", self.subject.passing_average)
        needed = Decimal(str(self.rec()["recommendation"]["major_exam"]
                             ["required_average_across_remaining"]))
        for exam in self.me:
            if exam.score is None:
                exam.score = needed
        self.assertGreaterEqual(
            calculate_grade(self.subject, self.cs, self.me).computed_average, required)

    def test_heading_label_names_the_actual_outstanding_exams(self):
        # Hardcoding "Final Exam" is wrong whenever a Midterm is also due.
        me_rec = self.rec()["recommendation"]["major_exam"]
        self.assertEqual(me_rec["remaining_exam_labels"], ["Midterm", "Final"])
        self.assertEqual(me_rec["exam_section_label"], "Midterm and Final Exams")

    def test_status_does_not_claim_a_dead_class_standing_route(self):
        # Every class standing assessment is scored, so that component cannot
        # move. Saying "either route is enough" would point at a route that
        # does not exist.
        details = self.rec()["supporting_details"]
        self.assertEqual(details["status_line"], "Achievable, but only through your major exams")
        self.assertNotIn("either route", details["status_line"])

    def test_tip_names_the_remaining_exam_average(self):
        details = self.rec()["supporting_details"]
        self.assertIn("84.36", details["tip_text"])
        self.assertIn("2 remaining major exams", details["tip_text"])


class PasswordChangeTests(TestCase):
    """Password change uses Django's built-in views, which rotate the session
    auth hash on success -- so the student must stay signed in afterwards."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pwuser", password="OldPass!2345")
        self.client.force_login(self.user)

    def test_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_form_renders_with_styled_fields_and_no_label_colons(self):
        response = self.client.get(reverse("password_change"))
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="auth-field', body)
        self.assertIn("Old password", body)
        self.assertNotIn("Old password:", body)

    def test_successful_change_updates_the_password(self):
        response = self.client.post(reverse("password_change"), {
            "old_password": "OldPass!2345",
            "new_password1": "BrandNew!6789",
            "new_password2": "BrandNew!6789"})
        self.assertRedirects(response, reverse("password_change_done"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNew!6789"))
        self.assertFalse(self.user.check_password("OldPass!2345"))

    def test_user_stays_signed_in_after_changing_it(self):
        self.client.post(reverse("password_change"), {
            "old_password": "OldPass!2345",
            "new_password1": "BrandNew!6789",
            "new_password2": "BrandNew!6789"})
        # A logged-out client would be redirected away from Home.
        self.assertEqual(self.client.get(reverse("subjects:dashboard")).status_code, 200)

    def test_wrong_old_password_is_rejected_and_shown(self):
        response = self.client.post(reverse("password_change"), {
            "old_password": "NotMyPassword!1",
            "new_password1": "BrandNew!6789",
            "new_password2": "BrandNew!6789"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("auth-field has-error", response.content.decode())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPass!2345"))

    def test_mismatched_confirmation_is_rejected(self):
        response = self.client.post(reverse("password_change"), {
            "old_password": "OldPass!2345",
            "new_password1": "BrandNew!6789",
            "new_password2": "Different!6789"})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPass!2345"))

    def test_account_menu_holds_change_password_and_logout(self):
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        menu = body[body.index('id="user-menu"'):body.index("</aside>")]
        self.assertIn(reverse("password_change"), menu)
        self.assertIn(reverse("logout"), menu)
        self.assertIn("Change password", menu)
        self.assertIn("Log out", menu)

    def test_avatar_shows_the_username_initial(self):
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        start = body.index('class="user-avatar"')
        self.assertIn("P", body[start:start + 120])  # username is "pwuser"
        self.assertIn("pwuser", body)

    def test_account_menu_starts_closed(self):
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        start = body.index('id="user-menu"')
        opening_tag = body[body.rindex("<", 0, start):body.index(">", start)]
        self.assertIn("hidden", opening_tag)
        # An author `display` would defeat the attribute, as it did on the modal.
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".user-menu[hidden]{display:none}", css.replace(" ", ""))

    def test_logout_is_a_post_not_a_link(self):
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        menu = body[body.index('id="user-menu"'):body.index("</aside>")]
        self.assertIn('method="post"', menu)
        self.assertIn("csrfmiddlewaretoken", menu)

    def test_done_page_confirms_the_change(self):
        response = self.client.get(reverse("password_change_done"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password updated")


class LayoutCenteringTests(TestCase):
    """The content column sits beside a fixed sidebar. With a horizontal
    margin of 0 it hugs the left edge and all spare width collects on the
    right, which reads as a broken layout on a wide screen."""

    def css(self):
        return (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")

    def test_sidebar_content_column_is_centred(self):
        css = self.css().replace(" ", "").replace("\n", "")
        marker = ".has-sidebar.container{"
        start = css.index(marker)
        rule = css[start:css.index("}", start)]
        self.assertIn("margin:var(--sp-8)auto90px", rule)
        self.assertNotIn("margin:var(--sp-8)090px", rule)


class HomeFitsOneScreenTests(TestCase):
    """Home is a glance, not a list: three subjects, no page scroll. Nothing
    is lost, because My Subjects holds the full scrollable roster."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="fits", password="pass12345")
        self.client.force_login(self.user)

    def make_and_open(self, name):
        subject = Subject.objects.create(
            student=self.user, name=name, units=3, passing_average=50,
            class_standing_percent_share=70, major_exam_percent_share=30)
        self.client.get(reverse("subjects:subject_detail", args=[subject.pk]))
        return subject

    def test_home_shows_at_most_three(self):
        self.assertEqual(RECENT_SUBJECT_COUNT, 3)
        for i in range(6):
            self.make_and_open(f"Subject {i}")
        self.assertEqual(len(self.client.get(reverse("subjects:dashboard")).context["rows"]), 3)

    def test_my_subjects_still_lists_them_all(self):
        for i in range(6):
            self.make_and_open(f"Subject {i}")
        self.assertEqual(len(self.client.get(reverse("subjects:subject_list")).context["rows"]), 6)

    def test_home_carries_the_body_class_the_rule_targets(self):
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        self.assertIn("page-home", body)
        # The roster page must NOT be locked, or long lists become unreachable.
        self.assertNotIn("page-home", self.client.get(reverse("subjects:subject_list")).content.decode())

    def test_overflow_lock_is_scoped_to_large_windows(self):
        # On a short or narrow screen the page must still scroll.
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")
        index = css.index("body.page-home{overflow:hidden}")
        preceding = css[:index]
        guard = preceding.rindex("@media")
        self.assertIn("min-height:700px", preceding[guard:])
        self.assertIn("min-width:901px", preceding[guard:])

    def test_see_all_subjects_link_is_present_when_home_is_capped(self):
        for i in range(6):
            self.make_and_open(f"Subject {i}")
        body = self.client.get(reverse("subjects:dashboard")).content.decode()
        self.assertIn(reverse("subjects:subject_list"), body)
        self.assertIn("See all subjects", body)