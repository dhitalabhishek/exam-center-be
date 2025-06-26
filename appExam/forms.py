import os

from django import forms


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
