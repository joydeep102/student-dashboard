from django import forms
from django.db.models import Q

from courses.models import Batch, Plan

from .models import VideoSubmission


class VideoSubmissionForm(forms.ModelForm):
    class Meta:
        model = VideoSubmission
        fields = ["batch", "title", "description", "required_plan", "video_file"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "e.g. Reading Candlestick Charts"}),
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "What does this video cover?"}),
            "video_file": forms.ClearableFileInput(attrs={"accept": "video/*"}),
        }

    def __init__(self, *args, trainer=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Trainers post to batches of the courses they teach; fall back to all
        # active batches so the portal is usable even before assignment.
        batches = Batch.objects.filter(is_active=True).select_related("course")
        own = (
            batches.filter(Q(instructor=trainer) | Q(course__instructor=trainer)).distinct()
            if trainer else batches.none()
        )
        self.fields["batch"].queryset = own if own.exists() else batches
        self.fields["batch"].empty_label = None
        self.fields["required_plan"].queryset = Plan.objects.filter(is_active=True)
        self.fields["required_plan"].required = False
        self.fields["required_plan"].help_text = "Leave blank so everyone in the batch can watch."
