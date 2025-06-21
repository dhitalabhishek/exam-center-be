import re
from typing import Any

import docx


def parse_questions_from_document(content: str) -> list[dict[str, Any]]:  # noqa: C901, PLR0912
    """
    Parse questions and answers from document content.
    Expected format:

    Question 1) Which of the following is the primary purpose of a centrifuge in a laboratory setting?
    A) To measure the pH of a solution
    B) To separate components of a mixture based on density
    C) To sterilize laboratory equipment
    D) To amplify DNA sequences
    Ans. To separate components of a mixture based on density

    Question 2) What is the most appropriate action to take if a chemical spill occurs in the laboratory?
    A) Ignore it and continue working
    B) Neutralize the spill with water immediately
    C) Follow the laboratory's spill response protocol and use appropriate PPE
    D) Open all windows to ventilate the area
    Ans. Follow the laboratory's spill response protocol and use appropriate PPE
    """  # noqa: E501
    questions = []

    # Split content by question patterns - now looking for "Question N)"
    question_pattern = r"Question\s+\d+\)\s*(.+?)(?=Question\s+\d+\)|$)"
    question_matches = re.finditer(question_pattern, content, re.DOTALL | re.IGNORECASE)

    for match in question_matches:
        question_block = match.group(1).strip()

        # Extract question text, options, and answer
        lines = question_block.split("\n")
        question_text = ""
        answers = []
        correct_answer_text = None

        current_section = "question"

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if it's an option line (A), B), C), D), etc.)
            option_match = re.match(r"^([A-Z])\)\s*(.+)", line)
            if option_match:
                current_section = "options"
                option_letter = option_match.group(1)
                option_text = option_match.group(2).strip()

                answers.append(
                    {
                        "text": option_text,
                        "is_correct": False,  # Will be set later based on answer
                        "option_letter": option_letter,
                    },
                )

            # Check if it's an answer line - now looking for "Ans."
            elif line.lower().startswith("ans."):
                correct_answer_text = line.split(".", 1)[1].strip()
                current_section = "answer"

            # If we're still in question section, add to question text
            elif current_section == "question":
                if question_text:
                    question_text += " " + line
                else:
                    question_text = line

        # Match the correct answer text with the options
        if correct_answer_text and answers:
            # Clean up the correct answer text for comparison
            correct_answer_clean = correct_answer_text.lower().strip()

            # Try to find matching option by comparing text
            best_match = None
            best_match_score = 0

            for answer in answers:
                answer_clean = answer["text"].lower().strip()

                # Check for exact match first
                if answer_clean == correct_answer_clean:
                    answer["is_correct"] = True
                    best_match = answer
                    break

                # Check if correct answer contains the option text or vice versa
                if (
                    answer_clean in correct_answer_clean
                    or correct_answer_clean in answer_clean
                ):
                    # Calculate similarity score (longer matches are better)
                    score = min(len(answer_clean), len(correct_answer_clean))
                    if score > best_match_score:
                        best_match_score = score
                        best_match = answer

            # If we found a best match, mark it as correct
            if best_match:
                best_match["is_correct"] = True

        # Ensure at least one answer is marked as correct if none are marked
        if answers and not any(answer["is_correct"] for answer in answers):
            answers[0]["is_correct"] = True  # Default to first option

        if question_text and answers:
            questions.append(
                {
                    "question": question_text,
                    "answers": answers,
                },
            )

    return questions


def parse_questions_from_docx(file_path: str) -> list[dict[str, Any]]:
    """Parse questions from a .docx file"""
    try:
        doc = docx.Document(file_path)
        content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        return parse_questions_from_document(content)
    except Exception as e:
        raise Exception(f"Error parsing DOCX file: {e!s}")


def validate_question_format(content: str) -> dict[str, Any]:
    """Validate if the document content follows the expected format"""
    # Updated patterns for new format
    question_pattern = r"Question\s+\d+\)"
    questions_found = len(re.findall(question_pattern, content, re.IGNORECASE))

    option_pattern = r"^[A-Z]\)\s*"
    options_found = len(re.findall(option_pattern, content, re.MULTILINE))

    answer_pattern = r"Ans\.\s*"
    answers_found = len(re.findall(answer_pattern, content, re.IGNORECASE))

    return {
        "is_valid": questions_found > 0 and options_found > 0,
        "questions_count": questions_found,
        "options_count": options_found,
        "answers_count": answers_found,
        "message": f"Found {questions_found} questions, {options_found} options, {answers_found} answer keys",
    }


def parse_questions_with_debug(content: str) -> dict[str, Any]:
    """
    Debug version that returns both parsed questions and debug info
    Useful for troubleshooting parsing issues
    """
    debug_info = {
        "raw_content_preview": content[:500] + "..." if len(content) > 500 else content,
        "question_matches": [],
        "parsing_errors": [],
    }

    try:
        questions = parse_questions_from_document(content)
        debug_info["questions_parsed"] = len(questions)
        debug_info["success"] = True

        # Add sample of parsed questions for debugging
        if questions:
            debug_info["sample_question"] = {
                "text": questions[0]["question"][:100] + "..."
                if len(questions[0]["question"]) > 100
                else questions[0]["question"],
                "answer_count": len(questions[0]["answers"]),
                "correct_answers": [
                    ans["text"] for ans in questions[0]["answers"] if ans["is_correct"]
                ],
            }

    except Exception as e:
        debug_info["success"] = False
        debug_info["parsing_errors"].append(str(e))
        questions = []

    return {"questions": questions, "debug_info": debug_info}
