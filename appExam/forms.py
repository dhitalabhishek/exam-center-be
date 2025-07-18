import os

from django import forms
from django.contrib.admin.widgets import AdminSplitDateTime

from .models import ExamSession
from .models import Hall


class DocumentUploadForm(forms.Form):
    document = forms.FileField(
        label="Select Document",
        help_text="Upload a .csv file containing questions and answers",
        widget=forms.FileInput(
            attrs={
                "accept": ".csv",
                "class": "form-control",
            },
        ),
    )

    def clean_document(self):
        document = self.cleaned_data.get("document")
        if document:
            # Check file extension
            allowed_extensions = [".csv"]
            file_extension = os.path.splitext(document.name)[1].lower()  # noqa: PTH122

            if file_extension not in allowed_extensions:
                raise forms.ValidationError(  # noqa: TRY003
                    f"Unsupported file type. Please upload a file with this extensions: {', '.join(allowed_extensions)}",  # noqa: E501, EM102
                )

            # Check file size (optional - adjust as needed)
            if document.size > 10 * 1024 * 1024:  # 10MB limit
                raise forms.ValidationError("File size must be less than 10MB")  # noqa: EM101, TRY003

        return document

class EnrollmentRangeForm(forms.Form):
    def __init__(self, session_id, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["hall"] = forms.ModelChoiceField(
            queryset=Hall.objects.all(),
            label="Select Hall",
            help_text="Select the hall for the students to be assigned to.",
        )

        self.fields["range_string"] = forms.CharField(
            label="Symbol Number Range",
            widget=forms.Textarea(attrs={
                "rows": 5,
                "placeholder": "e.g. 13-A1-PT - 13-A5-PT, 14-B1-PH, MG12XX10 - MG12XX99",
                "class": "form-control form-control-lg",
                "style": "resize:vertical;",  # optional for UX
            }),
            help_text="Enter comma-separated ranges or individual symbols.",
        )


class CleanAdminSplitDateTime(AdminSplitDateTime):
    def __init__(self, attrs=None):
        widgets = (
            forms.DateInput(attrs={"type": "date", "class": "vDateField form-control"}),
            forms.TimeInput(
                format="%H:%M",
                attrs={"type": "time", "step": 60, "class": "vTimeField form-control"},
            ),
        )
        super().__init__(attrs)
        self.widgets = widgets


class ExamSessionForm(forms.ModelForm):
    class Meta:
        model = ExamSession
        fields = "__all__"  # noqa: DJ007
        widgets = {
            "base_start": CleanAdminSplitDateTime(),
        }

    def clean_base_start(self):
        dt = self.cleaned_data.get("base_start")
        if dt:
            return dt.replace(second=0, microsecond=0)
        return dt
