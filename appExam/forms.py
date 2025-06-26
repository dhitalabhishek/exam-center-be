import os

from django import forms

from .models import Hall


class DocumentUploadForm(forms.Form):
    document = forms.FileField(
        label="Select Document",
        help_text="Upload a .csv file containing questions and answers",
        widget=forms.FileInput(attrs={
            "accept": ".csv",
            "class": "form-control",
        }),
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
            max_length=500,
            widget=forms.TextInput(
                attrs={"placeholder": "e.g. 13-A1-PT - 13-A5-PT, 14-B1-PH"},
            ),
            help_text="Enter comma-separated ranges or individual symbols.",
        )
