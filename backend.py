"""
backend.py

This file contains ALL the AI logic for the Exam Generator:
- Loading and splitting the curriculum
- Generating MCQs and descriptive questions using the Groq API
- Cleaning and saving the exam paper
- Building the final PDF

This file has NO GUI code in it at all. It doesn't know PyQt5 exists.
It only exposes functions that gui.py will call.

IMPORTANT: This logic is copied unchanged from the working notebook.
"""

import os
import re
import time
from difflib import SequenceMatcher

from groq import Groq
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors


# ---------------------------------------------------------------------------
# Groq client setup
# ---------------------------------------------------------------------------
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


# ---------------------------------------------------------------------------
# Load the syllabus file
# ---------------------------------------------------------------------------
def load_syllabus(file_path):
    """
    Reads the syllabus text file and returns its content as a single string.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return content


# ---------------------------------------------------------------------------
# Split the syllabus into individual topics
# ---------------------------------------------------------------------------
def split_into_topics(syllabus_text):
    """
    Splits the raw syllabus text into a list of individual topic strings.
    Assumes topics are separated by one or more blank lines.
    """
    text = syllabus_text.replace("Sample Topics/Syllabus:", "").strip()

    raw_topics = re.split(r"\n\s*\n", text)

    topics = []
    for topic in raw_topics:
        cleaned = " ".join(topic.split())
        if cleaned:
            topics.append(cleaned)

    return topics


# ---------------------------------------------------------------------------
# Descriptive question generation
# ---------------------------------------------------------------------------
def build_question_prompt(topic, difficulty="Moderate"):
    """
    Builds the instruction prompt sent to Groq for generating
    ONE medium-length, 5-mark descriptive exam question based on a given topic,
    written at the specified difficulty level.
    """
    difficulty_instructions = {
        "Easy": "Generate an EASY-level question only. Do NOT generate a moderate or hard question.",
        "Moderate": "Generate a MODERATE-level question only. Do NOT generate an easy or hard question.",
        "Hard": "Generate a HARD-level question only. Do NOT generate an easy or moderate question.",
    }
    difficulty_line = difficulty_instructions.get(difficulty, difficulty_instructions["Moderate"])

    prompt = f"""You are an experienced exam paper setter.

Topic: {topic}

Write exactly ONE exam question based on this topic, following these strict rules:
- The question must be worth 5 marks.
- Difficulty level: {difficulty_line}
- The question should be medium length: not a one-liner, and not a multi-part essay question. Aim for 1-3 sentences.
- Do NOT provide the answer or any explanation.
- Do NOT include the words "Answer:", solutions, or hints.
- Do NOT number the question or add extra commentary.
- Output ONLY the question text itself, nothing else.

Question:"""
    return prompt


def generate_question(topic, difficulty="Moderate", model="llama-3.3-70b-versatile"):
    """
    Sends the topic prompt to Groq's cloud API and returns
    a clean exam question (with any <think> reasoning removed, just in case).
    """
    prompt = build_question_prompt(topic, difficulty=difficulty)

    response = groq_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    raw_output = response.choices[0].message.content

    cleaned = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL)
    cleaned = cleaned.strip()

    return cleaned

def generate_all_questions(topics, num_questions=10, difficulty="Moderate", model="llama-3.3-70b-versatile"):
    """
    Generates one exam question per topic, up to num_questions, using
    validation with a single retry for each (see
    generate_validated_descriptive_question). Returns a list of question
    strings.
    """
    selected_topics = topics[:num_questions]
    questions = []

    for i, topic in enumerate(selected_topics, start=1):
        print(f"Generating question {i} of {num_questions}...")
        question, is_valid = generate_validated_descriptive_question(
            topic, difficulty=difficulty, model=model
        )
        if not is_valid:
            print(f"Warning: question for topic '{topic}' may still resemble an MCQ after one retry.")
        questions.append(question)
        time.sleep(1)

    return questions

# ---------------------------------------------------------------------------
# MCQ generation
# ---------------------------------------------------------------------------
def build_mcq_prompt(topic, difficulty="Moderate"):
    """
    Builds the instruction prompt sent to Groq for generating ONE multiple choice
    question (MCQ) with exactly four options (A-D), based on a given topic,
    written at the specified difficulty level.
    """
    difficulty_instructions = {
        "Easy": "Generate an EASY-level MCQ only. Do NOT generate a moderate or hard MCQ.",
        "Moderate": "Generate a MODERATE-level MCQ only. Do NOT generate an easy or hard MCQ.",
        "Hard": "Generate a HARD-level MCQ only. Do NOT generate an easy or moderate MCQ.",
    }
    difficulty_line = difficulty_instructions.get(difficulty, difficulty_instructions["Moderate"])

    prompt = f"""You are an experienced exam paper setter.

Topic: {topic}

Write exactly ONE multiple choice question (MCQ) based on this topic, following these strict rules:
- Difficulty level: {difficulty_line}
- The MCQ must have exactly four options labeled A), B), C), and D).
- Only one option should be the correct answer.
- Do NOT reveal or indicate which option is correct.
- Do NOT include the words "Answer:", solutions, or hints.
- Do NOT number the question.
- Format your response EXACTLY like this, with nothing else before or after:
Question: <the question text>
A) <option text>
B) <option text>
C) <option text>
D) <option text>
"""
    return prompt


def parse_mcq(raw_text):
    """
    Parses the raw MCQ text returned by Groq into a structured dictionary:
    {"question": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}}
    """
    # Remove <think>...</think> reasoning block if present, same safeguard as generate_question()
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()

    # Extract everything between "Question:" and the first option "A)"
    q_match = re.search(r"Question:\s*(.*?)(?=\n\s*A\))", cleaned, re.DOTALL)
    if q_match:
        question_text = q_match.group(1).strip()
    else:
        # Fallback in case the model slightly changes the format
        question_text = cleaned.split("A)")[0].replace("Question:", "").strip()

    # Extract each "A) ...", "B) ...", "C) ...", "D) ..." line
    options = {}
    for match in re.finditer(r"^\s*([A-D])\)\s*(.+)$", cleaned, re.MULTILINE):
        letter, text = match.groups()
        options[letter] = text.strip()

    return {"question": question_text, "options": options}


def generate_mcq(topic, difficulty="Moderate", model="llama-3.3-70b-versatile"):
    """
    Sends the MCQ prompt to Groq's cloud API and returns a parsed MCQ dictionary.
    """
    prompt = build_mcq_prompt(topic, difficulty=difficulty)

    response = groq_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    raw_output = response.choices[0].message.content
    return parse_mcq(raw_output)


def generate_all_mcqs(topics, num_questions=10, difficulty="Moderate", model="llama-3.3-70b-versatile"):
    """
    Generates one MCQ per topic, up to num_questions.
    Returns a list of parsed MCQ dictionaries.
    """
    selected_topics = topics[:num_questions]
    mcqs = []

    for i, topic in enumerate(selected_topics, start=1):
        print(f"Generating MCQ {i} of {num_questions}...")
        mcq = generate_mcq(topic, difficulty=difficulty, model=model)
        mcqs.append(mcq)
        time.sleep(1)

    return mcqs


# ---------------------------------------------------------------------------
# Cleaning and saving
# ---------------------------------------------------------------------------
def clean_question_text(question):
    """
    Removes common instruction-leak phrases that sometimes slip into
    the model's output, and tidies up formatting.
    """
    leak_phrases = [
        r"allocate exactly \d+ marks.*",
        r"worth \d+ marks.*",
        r"\(5 marks\)",
        r"\[5 marks\]",
    ]
    cleaned = question
    for pattern in leak_phrases:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

    # ---------------------------------------------------------------------------
# Descriptive question validation
# ---------------------------------------------------------------------------
def is_duplicate_question(new_question, existing_questions, similarity_threshold=0.8):
    """
    Checks whether new_question is too similar to any question already in
    existing_questions (a list of plain question-text strings). Uses
    difflib's SequenceMatcher to compute a similarity ratio between 0.0
    (completely different) and 1.0 (identical), with no external
    dependencies required.

    Returns True if new_question is a near-duplicate of any existing
    question (similarity >= similarity_threshold), False otherwise.
    """
    if not new_question or not existing_questions:
        return False

    new_question_normalized = new_question.strip().lower()

    for existing in existing_questions:
        existing_normalized = existing.strip().lower()
        similarity = SequenceMatcher(None, new_question_normalized, existing_normalized).ratio()
        if similarity >= similarity_threshold:
            return True

    return False
def is_valid_descriptive_question(question_text):
    """
    Checks whether a supposedly "descriptive" question is actually a
    disguised MCQ (has lettered options, or asks the reader to pick from
    choices). Returns True if the question looks like a genuine descriptive
    question, False if it looks like an MCQ in disguise.

    Designed to be conservative: it looks for clear MCQ structure/phrasing,
    not just the presence of the letters A, B, C, or D somewhere in normal
    text (which would cause false rejections of legitimate questions).
    """
    if not question_text or not question_text.strip():
        return False

    text = question_text.strip()

    # Pattern 1: lettered options like "A)" or "A." at the start of a line,
    # e.g. "A) Paris" or "A. Paris" — this is the clearest MCQ signal.
    # We require it to be at the start of a line (optionally after
    # whitespace) so we don't flag a normal sentence that happens to
    # contain "A." or "A)" mid-sentence.
    option_pattern = re.compile(r"(?m)^\s*[A-D][\).]\s+\S")
    option_matches = option_pattern.findall(text)

    # If we find 2 or more lettered options, this is almost certainly an MCQ
    if len(option_matches) >= 2:
        return False

    # Pattern 2: common MCQ-style instruction phrases
    mcq_phrases = [
        r"choose the correct answer",
        r"select the correct option",
        r"which of the following",
        r"select the correct answer",
        r"choose the correct option",
        r"pick the correct answer",
        r"select one of the following",
    ]
    for phrase in mcq_phrases:
        if re.search(phrase, text, re.IGNORECASE):
            return False

    return True

def generate_validated_descriptive_question(topic, difficulty="Moderate", model="llama-3.3-70b-versatile",
                                              existing_questions=None):
    """
    Generates a descriptive question and validates that it's (a) not a
    disguised MCQ, and (b) not a near-duplicate of any question already
    in existing_questions. If the first attempt fails either check,
    generates exactly ONE replacement and validates that too. Whatever
    question text results after that (valid or not) is returned, along
    with a flag telling the caller whether it passed validation.

    existing_questions: optional list of plain question-text strings
    already generated in this session, used for duplicate checking.
    Pass None or [] if there's nothing to compare against yet.

    Returns a tuple: (question_text, is_valid)
    - is_valid is True if the returned question passed both checks
    - is_valid is False if BOTH attempts failed a check (caller can
      then decide how to handle it gracefully, e.g. skip it or flag it)

    This does not create an infinite retry loop: at most 2 API calls
    are made (1 initial attempt + 1 retry).
    """
    if existing_questions is None:
        existing_questions = []

    def passes_all_checks(text):
        if not is_valid_descriptive_question(text):
            return False
        if is_duplicate_question(text, existing_questions):
            return False
        return True

    question_text = generate_question(topic, difficulty=difficulty, model=model)

    if passes_all_checks(question_text):
        return question_text, True

    # First attempt failed a check — generate exactly one replacement
    print(f"Descriptive question for topic '{topic}' failed validation (MCQ-like or duplicate). Retrying once...")
    retry_text = generate_question(topic, difficulty=difficulty, model=model)

    if passes_all_checks(retry_text):
        return retry_text, True

    # Retry also failed — stop here, do not retry again.
    # Return the retry's text anyway (best available), flagged as invalid.
    print(f"Replacement question for topic '{topic}' also failed validation. Accepting as-is after one retry.")
    return retry_text, False


def save_exam_paper(mcqs, descriptive_questions, filename="Generated_Exam.txt"):
    """
    Formats and saves the full exam paper (Section A: MCQs, Section B: Descriptive
    Questions) as a plain-text backup, alongside the PDF.
    """
    with open(filename, "w", encoding="utf-8") as f:
        f.write("EXAMINATION PAPER\n")
        f.write("=" * 60 + "\n")
        f.write(f"Section A: {len(mcqs)} MCQs (1 mark each) | "
                f"Section B: {len(descriptive_questions)} Descriptive Questions (5 marks each)\n")
        f.write("=" * 60 + "\n\n")

        f.write("SECTION A: Multiple Choice Questions\n\n")
        for i, mcq in enumerate(mcqs, start=1):
            f.write(f"Q{i}. {mcq['question']}\n")
            for letter in ["A", "B", "C", "D"]:
                f.write(f"   {letter}) {mcq['options'].get(letter, '')}\n")
            f.write("\n")

        f.write("\nSECTION B: Descriptive Questions\n\n")
        for i, q in enumerate(descriptive_questions, start=1):
            cleaned_q = clean_question_text(q)
            f.write(f"Q{i}. [5 Marks]\n{cleaned_q}\n\n")

    print(f"Exam paper (text backup) saved as '{filename}'")


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------
def create_exam_pdf(mcqs, descriptive_questions, exam_title, filename="Generated_Exam.pdf",
                     subject="General", total_time="90 minutes"):
    """
    Builds a professional, university-style exam paper PDF containing
    Section A (MCQs) and Section B (Descriptive Questions).
    """
    doc = SimpleDocTemplate(
        filename, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("ExamTitle", parent=styles["Title"], fontSize=18, spaceAfter=6)
    subtitle_style = ParagraphStyle("ExamSubtitle", parent=styles["Normal"], fontSize=11,
                                     alignment=TA_CENTER, textColor=colors.grey, spaceAfter=14)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=13,
                                    spaceBefore=14, spaceAfter=8, textColor=colors.HexColor("#1a1a1a"))
    instructions_style = ParagraphStyle("Instructions", parent=styles["Normal"], fontSize=9.5, leading=14)
    question_style = ParagraphStyle("Question", parent=styles["Normal"], fontSize=10.5, leading=15,
                                     spaceBefore=8, spaceAfter=2)
    option_style = ParagraphStyle("Option", parent=styles["Normal"], fontSize=10.5, leading=14, leftIndent=18)

    total_marks = len(mcqs) * 1 + len(descriptive_questions) * 5
    elements = []

    # Title block
    elements.append(Paragraph(exam_title, title_style))
    elements.append(Paragraph(
        f"Subject: {subject} &nbsp;|&nbsp; Time Allowed: {total_time} &nbsp;|&nbsp; Total Marks: {total_marks}",
        subtitle_style
    ))

    # Name / Roll No / Date fields
    info_table = Table(
        [["Name: ___________________________", "Roll No: ________________"],
         ["Date: ___________________________", "Section: ________________"]],
        colWidths=[9 * cm, 8 * cm]
    )
    info_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 10))

    # Instructions box
    instructions_text = (
        "<b>Instructions to Candidates:</b><br/>"
        "1. Attempt ALL questions in both sections.<br/>"
        "2. Section A carries 1 mark per question; Section B carries 5 marks per question.<br/>"
        "3. Write your answers clearly and legibly.<br/>"
        "4. No electronic devices are allowed during the examination."
    )
    elements.append(Paragraph(instructions_text, instructions_style))
    elements.append(Spacer(1, 6))

    # Section A: MCQs
    elements.append(Paragraph(
        f"Section A: Multiple Choice Questions ({len(mcqs)} x 1 = {len(mcqs)} Marks)", section_style
    ))
    for i, mcq in enumerate(mcqs, start=1):
        elements.append(Paragraph(f"Q{i}. {mcq['question']}", question_style))
        for letter in ["A", "B", "C", "D"]:
            elements.append(Paragraph(f"{letter}) {mcq['options'].get(letter, '')}", option_style))

    elements.append(PageBreak())

    # Section B: Descriptive Questions
    total_marks_b = len(descriptive_questions) * 5
    elements.append(Paragraph(
        f"Section B: Descriptive Questions ({len(descriptive_questions)} x 5 = {total_marks_b} Marks)", section_style
    ))
    for i, q in enumerate(descriptive_questions, start=1):
        cleaned_q = clean_question_text(q)
        elements.append(Paragraph(f"Q{i}. [5 Marks] {cleaned_q}", question_style))

    # Page numbers in the footer
    def add_page_number(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"Professional exam PDF saved as '{filename}'")


# ---------------------------------------------------------------------------
# Full pipeline (this is the ONE function the GUI will mainly call)
# ---------------------------------------------------------------------------
def generate_exam(syllabus_path, exam_title, output_basename, subject="General",
                   num_mcqs=10, num_descriptive=10, difficulty="Moderate",
                   model="llama-3.3-70b-versatile"):
    """
    Full pipeline: load syllabus -> split into topics -> generate MCQs and
    descriptive questions -> save text backup -> generate PDF exam paper.
    Reuses every function defined earlier in this file.
    """
    print(f"\n=== Generating exam for: {syllabus_path} ===")
    syllabus_text = load_syllabus(syllabus_path)
    topics = split_into_topics(syllabus_text)
    print(f"Found {len(topics)} topics.")

    print(f"\nGenerating {num_descriptive} descriptive question(s) at {difficulty} difficulty...")
    descriptive_questions = generate_all_questions(
        topics, num_questions=num_descriptive, difficulty=difficulty, model=model
    )

    print(f"\nGenerating {num_mcqs} MCQ(s) at {difficulty} difficulty...")
    mcqs = generate_all_mcqs(
        topics, num_questions=num_mcqs, difficulty=difficulty, model=model
    )

    txt_filename = f"{output_basename}.txt"
    pdf_filename = f"{output_basename}.pdf"

    save_exam_paper(mcqs, descriptive_questions, filename=txt_filename)
    create_exam_pdf(mcqs, descriptive_questions, exam_title=exam_title, filename=pdf_filename, subject=subject)

    return {"topics": topics, "descriptive_questions": descriptive_questions, "mcqs": mcqs}