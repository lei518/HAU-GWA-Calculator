from django import forms
from .models import Subject

class SubjectForm(forms.ModelForm):
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
