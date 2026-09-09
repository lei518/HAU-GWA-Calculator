from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .grading import calculate_grade, minimum_computed_average_for_grade, transmuted_value
from .models import ClassStandingAssessment, MajorExam, Subject

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

    def add_exam(self, period, score=None, hps=100, weight="33.33"):
        return MajorExam.objects.create(
            subject=self.subject, grading_period=period, score=score,
            highest_possible_score=hps, weight=weight)

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
