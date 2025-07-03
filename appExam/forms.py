import os

from django import forms
from django.contrib.admin.widgets import AdminSplitDateTime
from django.core.exceptions import ValidationError

from .models import ExamSession
from .models import Hall


class DocumentUploadForm(forms.Form):
    document = forms.FileField(
        label="Select Document",
        help_text="Upload a .csv, .txt, or .docx file containing questions and answers",
        widget=forms.FileInput(
            attrs={
                "accept": ".csv,.txt,.docx",
                "class": "form-control",
            },
        ),
    )

    # Format configuration fields
    file_format = forms.ChoiceField(
        label="Document Format",
        choices=[
            ("auto", "Auto-detect from file extension"),
            ("csv", "CSV Format"),
            ("text", "Text Format (Standard)"),
            ("docx", "Word Document Format"),
        ],
        initial="auto",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    # CSV Format Configuration
    csv_question_column = forms.CharField(
        label="Question Column Name",
        initial="QUESTION",
        help_text="Column name for questions in CSV",
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False,
    )

    csv_answer_column = forms.CharField(
        label="Answer Column Name",
        initial="ANSWER",
        help_text="Column name for answers in CSV",
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False,
    )

    csv_option_columns = forms.CharField(
        label="Option Column Names",
        initial="OPTIONS_A,OPTIONS_B,OPTIONS_C,OPTIONS_D",
        help_text="Comma-separated column names for options",
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False,
    )

    csv_answer_format = forms.ChoiceField(
        label="CSV Answer Format",
        choices=[
            ("letter", "Letter (a, b, c, d)"),
            ("text", "Full Answer Text"),
        ],
        initial="letter",
        widget=forms.Select(attrs={"class": "form-control"}),
        required=False,
    )

    # Text/DOCX Format Configuration
    text_question_prefix = forms.CharField(
        label="Question Prefix",
        initial="Q.",
        help_text="Prefix that identifies questions (e.g., 'Q.', 'Question:', etc.)",
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False,
    )

    text_option_prefixes = forms.CharField(
        label="Option Prefixes",
        initial="1.,2.,3.,4.",
        help_text="Comma-separated prefixes for options (e.g., '1.,2.,3.,4.' or 'A.,B.,C.,D.')",
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False,
    )

    text_answer_prefix = forms.CharField(
        label="Answer Prefix",
        initial="Answer:",
        help_text="Prefix that identifies the correct answer",
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False,
    )

    text_answer_format = forms.ChoiceField(
        label="Text Answer Format",
        choices=[
            ("text", "Full Answer Text"),
            ("number", "Option Number (1, 2, 3, 4)"),
        ],
        initial="text",
        widget=forms.Select(attrs={"class": "form-control"}),
        required=False,
    )

    def clean_document(self):
        document = self.cleaned_data.get("document")
        if document:
            # Check file extension
            allowed_extensions = [".csv", ".txt", ".docx"]
            file_extension = os.path.splitext(document.name)[1].lower()
            if file_extension not in allowed_extensions:
                raise ValidationError(
                    f"Unsupported file type. Please upload a file with these extensions: {', '.join(allowed_extensions)}",
                )

            # Check file size (10MB limit)
            if document.size > 10 * 1024 * 1024:
                raise ValidationError("File size must be less than 10MB")

        return document

    def clean_csv_option_columns(self):
        columns = self.cleaned_data.get("csv_option_columns", "")
        if columns:
            # Split and clean column names
            column_list = [col.strip() for col in columns.split(",") if col.strip()]
            if len(column_list) < 2:
                raise ValidationError("At least 2 option columns are required")
            return column_list
        return ["OPTIONS_A", "OPTIONS_B", "OPTIONS_C", "OPTIONS_D"]

    def clean_text_option_prefixes(self):
        prefixes = self.cleaned_data.get("text_option_prefixes", "")
        if prefixes:
            # Split and clean prefixes
            prefix_list = [
                prefix.strip() for prefix in prefixes.split(",") if prefix.strip()
            ]
            if len(prefix_list) < 2:
                raise ValidationError("At least 2 option prefixes are required")
            return prefix_list
        return ["1.", "2.", "3.", "4."]

    def get_format_config(self):
        """Returns a DocumentFormatConfig object based on form data"""
        from .utils.questionParser import DocumentFormatConfig

        config = DocumentFormatConfig()

        # CSV configuration
        config.csv_question_column = self.cleaned_data.get(
            "csv_question_column",
            "QUESTION",
        )
        config.csv_answer_column = self.cleaned_data.get("csv_answer_column", "ANSWER")
        config.csv_option_columns = self.cleaned_data.get(
            "csv_option_columns",
            ["OPTIONS_A", "OPTIONS_B", "OPTIONS_C", "OPTIONS_D"],
        )
        config.csv_answer_format = self.cleaned_data.get("csv_answer_format", "letter")

        # Text configuration
        config.text_question_prefix = self.cleaned_data.get(
            "text_question_prefix",
            "Q.",
        )
        config.text_option_prefixes = self.cleaned_data.get(
            "text_option_prefixes",
            ["1.", "2.", "3.", "4."],
        )
        config.text_answer_prefix = self.cleaned_data.get(
            "text_answer_prefix",
            "Answer:",
        )
        config.text_answer_format = self.cleaned_data.get("text_answer_format", "text")

        # DOCX configuration (same as text)
        config.docx_question_prefix = config.text_question_prefix
        config.docx_option_prefixes = config.text_option_prefixes
        config.docx_answer_prefix = config.text_answer_prefix
        config.docx_answer_format = config.text_answer_format

        return config


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
            widget=forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Eg 13-A1-PT | 13-A5-PT, 14-B1-PH, MG12XX10 | MG12XX99",  # noqa: E501
                    "class": "form-control form-control-lg",
                    "style": "resize:vertical;",  # optional for UX
                },
            ),
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
