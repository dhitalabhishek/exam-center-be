# appExam/question_admin_views.py
import logging
from pathlib import Path

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .forms import DocumentUploadForm
from .models import Answer
from .models import ExamSession
from .models import Question

logger = logging.getLogger(__name__)


def import_questions_view(self, request):
    exam_sessions = ExamSession.objects.all().order_by("-base_start")
    context = {
        **self.admin_site.each_context(request),
        "title": "Select Exam Session",
        "exam_sessions": exam_sessions,
        "opts": self.model._meta,  # noqa: SLF001
        "has_view_permission": True,
        "current_time": timezone.localtime(timezone.now()),
    }
    return TemplateResponse(
        request,
        "admin/appExam/question/select_session.html",
        context,
    )


def import_questions_document_view(self, request, session_id):
    session = get_object_or_404(ExamSession, id=session_id)

    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            document = request.FILES["document"]
            file_extension = Path(document.name).suffix.lower()

            # Validate file extension
            allowed_extensions = [".csv", ".txt", ".docx"]
            if file_extension not in allowed_extensions:
                messages.error(
                    request,
                    f"Unsupported file type. Only {', '.join(allowed_extensions)} files are supported.",
                )
                return redirect(
                    "admin:appExam_question_import_document",
                    session_id=session_id,
                )

            try:
                # Get format configuration from form
                config = form.get_format_config()

                # Determine file format
                file_format = form.cleaned_data.get("file_format", "auto")
                if file_format == "auto":
                    # Auto-detect based on extension
                    if file_extension == ".csv":  # noqa: SIM108
                        file_format = "csv"
                    else:  # .txt or .docx
                        file_format = (
                            "text"  # Will auto-detect MCQ format within the parser
                        )

                # Parse questions using the appropriate parser
                from .utils.questionParser import parse_questions_from_document

                parsed_questions = parse_questions_from_document(
                    document,
                    file_extension,
                    config,
                )

                if not parsed_questions:
                    messages.warning(
                        request,
                        "No valid questions were found in the document. Please check your format.",
                    )
                    return redirect(
                        "admin:appExam_question_import_document",
                        session_id=session_id,
                    )

                # Store parsed data in session
                request.session["parsed_questions"] = parsed_questions
                request.session["session_id"] = session_id
                request.session["document_name"] = document.name
                request.session["file_format"] = file_format

                context = {
                    **self.admin_site.each_context(request),
                    "title": f"Import Questions - {session}",
                    "session": session,
                    "document_name": document.name,
                    "file_format": file_format,
                    "questions": parsed_questions,
                    "total_questions": len(parsed_questions),
                    "opts": self.model._meta,
                    "has_view_permission": True,
                    "current_time": timezone.localtime(timezone.now()),
                }

                return TemplateResponse(
                    request,
                    "admin/appExam/question/parse_document.html",
                    context,
                )

            except Exception as e:
                messages.error(request, f"Error parsing document: {e!s}")
                return redirect(
                    "admin:appExam_question_import_document",
                    session_id=session_id,
                )
        else:
            # Form has errors, render with form errors
            context = {
                **self.admin_site.each_context(request),
                "title": f"Upload Document - {session}",
                "form": form,
                "session": session,
                "supported_formats": [".csv", ".txt", ".docx"],
                "opts": self.model._meta,
                "has_view_permission": True,
                "current_time": timezone.localtime(timezone.now()),
            }
            return TemplateResponse(
                request,
                "admin/appExam/question/upload_document.html",
                context,
            )
    else:
        form = DocumentUploadForm()

    context = {
        **self.admin_site.each_context(request),
        "title": f"Upload Document - {session}",
        "form": form,
        "session": session,
        "supported_formats": [".csv", ".txt", ".docx"],
        "opts": self.model._meta,
        "has_view_permission": True,
        "current_time": timezone.localtime(timezone.now()),
    }

    return TemplateResponse(
        request,
        "admin/appExam/question/upload_document.html",
        context,
    )


@method_decorator(csrf_exempt, name="dispatch")
def parse_questions_view(self, request):
    import random
    import traceback
    from collections import defaultdict

    from appExam.models import StudentExamEnrollment

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        session_id = request.session.get("session_id")
        parsed_questions = request.session.get("parsed_questions")

        if not session_id or not parsed_questions:
            messages.error(request, "Session expired or missing data.")
            return redirect("admin:appExam_question_import")

        session = get_object_or_404(ExamSession, id=session_id)

        logger.info("=== POST DATA DEBUG ===")
        for key, value in request.POST.items():
            logger.info(f"POST[{key}] = {value}")  # noqa: G004
        logger.info("=== END POST DATA ===")

        logger.info(f"Original parsed questions count: {len(parsed_questions)}")  # noqa: G004

        updated_questions = []

        question_numbers = set()
        for key in request.POST.keys():
            if key.startswith("question_"):
                try:
                    question_numbers.add(int(key.split("_")[1]))
                except ValueError:
                    continue

        question_numbers = sorted(question_numbers)
        logger.info(f"Question numbers found in POST: {question_numbers}")

        total_expected = len(parsed_questions)
        logger.info(
            f"Expected questions: {total_expected}, Found in POST: {len(question_numbers)}",
        )

        for question_num in range(1, total_expected + 1):
            logger.info(f"\n--- Processing Question {question_num} ---")

            question_text = request.POST.get(f"question_{question_num}", "").strip()
            logger.info(f"Question text length: {len(question_text)}")

            if not question_text:
                logger.warning(
                    f"Question {question_num}: Empty question text - SKIPPING",
                )
                continue

            correct_letter = (
                request.POST.get(f"correct_{question_num}", "").strip().lower()
            )
            logger.info(f"Correct letter: '{correct_letter}'")

            answers = []
            for letter in ["a", "b", "c", "d"]:
                option_text = request.POST.get(
                    f"option_{question_num}_{letter}",
                    "",
                ).strip()
                logger.info(
                    f"Option {letter}: '{option_text}' (length: {len(option_text)})",
                )

                if option_text:
                    answers.append(
                        {
                            "text": option_text,
                            "option_letter": letter.upper(),
                            "is_correct": (letter == correct_letter),
                        },
                    )

            logger.info(f"Question {question_num}: Created {len(answers)} answers")

            if answers:
                updated_questions.append(
                    {
                        "question": question_text,
                        "answers": answers,
                    },
                )
                logger.info(f"Question {question_num}: ADDED to updated_questions")
            else:
                logger.warning(f"Question {question_num}: No answers - SKIPPING")

        logger.info(f"\nFinal updated_questions count: {len(updated_questions)}")

        created_count = 0
        for idx, question_data in enumerate(updated_questions, 1):
            try:
                logger.info(f"Creating question {idx} in database...")
                question = Question.objects.create(
                    text=question_data["question"],
                    session=session,
                )
                logger.info(f"Question {idx} created with ID: {question.id}")

                answer_count = 0
                for answer_data in question_data["answers"]:
                    try:
                        Answer.objects.create(
                            question=question,
                            text=answer_data["text"],
                            is_correct=answer_data["is_correct"],
                        )
                        answer_count += 1
                        logger.info(
                            f"Answer created: {answer_data['text'][:50]}...",
                        )
                    except Exception as e:
                        logger.error(f"Failed to create answer: {e!s}")

                logger.info(f"Question {idx}: Created with {answer_count} answers")
                created_count += 1

            except Exception as e:
                logger.error(f"Failed to create question {idx}: {e!s}")
                logger.error(traceback.format_exc())

        # ======================================
        # ✅ Randomize questions and answers for each enrollment
        # ======================================
        logger.info("Starting randomization for all enrollments...")

        # Fetch all enrollments for this session
        enrollments = StudentExamEnrollment.objects.filter(session=session)

        # Fetch all question IDs for this session
        question_ids = list(
            Question.objects.filter(session=session).values_list("id", flat=True),
        )

        # Fetch all (question_id, answer_id) pairs
        all_pairs = Answer.objects.filter(question__session=session).values_list(
            "question_id",
            "id",
        )

        # Group answers by question_id
        grouped_answers = defaultdict(list)
        for qid, aid in all_pairs:
            grouped_answers[qid].append(aid)

        for enrollment in enrollments:
            # Shuffle questions
            randomized_questions = question_ids.copy()
            random.shuffle(randomized_questions)
            enrollment.question_order = randomized_questions

            # Shuffle answers per question
            answer_order = {}
            for qid in randomized_questions:
                answer_list = grouped_answers.get(qid, []).copy()
                random.shuffle(answer_list)
                answer_order[str(qid)] = answer_list

            enrollment.answer_order = answer_order
            enrollment.save()
            logger.info(f"Enrollment {enrollment.id}: randomized and saved.")

        logger.info("✅ Randomization completed for all enrollments.")

        # ======================================

        # Clear session data
        for key in ["parsed_questions", "session_id", "document_name"]:
            request.session.pop(key, None)

        logger.info(f"=== FINAL RESULT: Created {created_count} questions ===")

        messages.success(
            request,
            f"Successfully imported {created_count} question{'s' if created_count != 1 else ''} from document and randomized for all students.",
        )
        return redirect("admin:appExam_question_changelist")

    except Exception as e:
        logger.error(f"Error in parse_questions_view: {e!s}")
        logger.error(traceback.format_exc())
        messages.error(request, f"Failed to import questions: {e!s}")
        return redirect("admin:appExam_question_import")
