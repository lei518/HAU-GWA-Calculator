from decimal import Decimal

from django import forms

from .models import Subject

# The two splits HAU actually uses, plus an escape hatch. Presets exist so the
# common case is one click and cannot be typo'd; "custom" keeps the form
# usable for any subject that follows neither split.
SHARE_PRESETS = {
    "70_30": (Decimal("70"), Decimal("30")),
    "60_40": (Decimal("60"), Decimal("40")),
}
SHARE_PRESET_CHOICES = [
    ("70_30", "70% Class Standing / 30% Major Examination"),
    ("60_40", "60% Class Standing / 40% Major Examination"),
    ("custom", "Custom split"),
]

def preset_for(cs_share, me_share):
    """Which preset a stored pair of shares corresponds to, so an edit form
    reopens on the button the subject was actually created with."""
    for key, (cs, me) in SHARE_PRESETS.items():
        if Decimal(cs_share) == cs and Decimal(me_share) == me:
            return key
    return "custom"

class SubjectForm(forms.ModelForm):
    share_preset = forms.ChoiceField(
        choices=SHARE_PRESET_CHOICES, required=False, initial="70_30",
        label="Grade weighting")

    class Meta:
        model = Subject
        fields = [
            "name", "units", "passing_average",
            "class_standing_percent_share", "major_exam_percent_share",
        ]
        widgets = {f: forms.NumberInput(attrs={"step": "0.01"}) for f in [
            "units", "passing_average", "class_standing_percent_share",
            "major_exam_percent_share",
        ]}

    def clean(self):
        cleaned = super().clean()
        preset = cleaned.get("share_preset")

        # A chosen preset always wins over whatever sits in the two number
        # inputs, so a stale or hand-edited value cannot survive a preset
        # click and quietly change the subject's weighting.
        if preset in SHARE_PRESETS:
            cs_share, me_share = SHARE_PRESETS[preset]
            cleaned["class_standing_percent_share"] = cs_share
            cleaned["major_exam_percent_share"] = me_share
            return cleaned

        cs_share = cleaned.get("class_standing_percent_share")
        me_share = cleaned.get("major_exam_percent_share")
        if cs_share is None or me_share is None:
            return cleaned

        for field, value in (("class_standing_percent_share", cs_share),
                             ("major_exam_percent_share", me_share)):
            if value < 0 or value > 100:
                self.add_error(field, "Must be between 0 and 100.")
        if self.errors:
            return cleaned

        # Without this the grading formula happily computes
        # 0.70 * class_standing + 0.40 * major_exam, which can exceed 100%
        # and hand back a transmuted value -- and therefore a grade -- that
        # the student never actually earned.
        total = cs_share + me_share
        if total != Decimal("100"):
            raise forms.ValidationError(
                "Class Standing % and Major Examination % must add up to 100 "
                f"(they currently add up to {total.normalize():f})."
            )
        return cleaned