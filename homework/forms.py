from django import forms

from .models import HomeTask, HomeworkSubmission


class HomeTaskForm(forms.ModelForm):
    class Meta:
        model = HomeTask
        fields = ["title", "instructions"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Draw 3 support/resistance setups"}),
            "instructions": forms.Textarea(attrs={"rows": 4, "placeholder": "What should students do and submit?"}),
        }


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = HomeworkSubmission
        fields = ["answer_text"]
        widgets = {
            "answer_text": forms.Textarea(attrs={"rows": 4, "placeholder": "Write your answer (optional) and attach photos below."}),
        }