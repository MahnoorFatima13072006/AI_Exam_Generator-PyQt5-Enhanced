from PyQt5.QtCore import QThread, pyqtSignal

import backend


class ExamWorker(QThread):
    """
    Runs backend.generate_exam() on a background thread, so the
    main window doesn't freeze while the AI is working.

    Signals:
    - finished_successfully: sent when generation completes with no errors
    - failed: sent if an error occurs, carrying the error message
    - status_update: sent to report progress messages as text
    """

    finished_successfully = pyqtSignal()
    failed = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, syllabus_path, exam_title, output_basename, subject,
                 num_mcqs, num_descriptive, difficulty):
        super().__init__()
        self.syllabus_path = syllabus_path
        self.exam_title = exam_title
        self.output_basename = output_basename
        self.subject = subject
        self.num_mcqs = num_mcqs
        self.num_descriptive = num_descriptive
        self.difficulty = difficulty

    def run(self):
        """
        This method runs automatically on the background thread
        when we call worker.start() from the main window.
        """
        try:
            self.status_update.emit("Generating exam questions, please wait...")

            backend.generate_exam(
                syllabus_path=self.syllabus_path,
                exam_title=self.exam_title,
                output_basename=self.output_basename,
                subject=self.subject,
                num_mcqs=self.num_mcqs,
                num_descriptive=self.num_descriptive,
                difficulty=self.difficulty
            )

            self.finished_successfully.emit()

        except Exception as e:
            self.failed.emit(str(e))

class QuestionBatchWorker(QThread):
    """
    Generates a batch of candidate questions (MCQs and/or descriptive)
    on a background thread, and sends them back as data — it does NOT
    save a PDF. Used for both the initial "Generate Questions" batch
    and the "Generate 1 More Question" button (just call it with
    num_mcqs=1, num_descriptive=0, or similar).

    Signals:
    - questions_ready: sent with the list of newly generated questions
    - failed: sent if an error occurs, carrying the error message
    - status_update: sent to report progress messages as text
    """

    questions_ready = pyqtSignal(list)
    failed = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, topics, num_mcqs, num_descriptive, difficulty, existing_descriptive_questions=None):
        super().__init__()
        self.topics = topics
        self.num_mcqs = num_mcqs
        self.num_descriptive = num_descriptive
        self.difficulty = difficulty
        # Plain-text list of descriptive questions already generated earlier
        # in this session (used for duplicate detection). Defaults to empty.
        self.existing_descriptive_questions = existing_descriptive_questions or []

    def run(self):
        try:
            new_questions = []

           # Generate descriptive questions one at a time, cycling through topics.
            # We keep a running list that includes both questions from earlier
            # in the session AND any new ones generated in this batch so far,
            # so duplicate-checking covers the full session history.
            all_descriptive_so_far = list(self.existing_descriptive_questions)

            for i in range(self.num_descriptive):
                self.status_update.emit(
                    f"Generating descriptive question {i + 1} of {self.num_descriptive}..."
                )
                topic = self.topics[i % len(self.topics)]
                question_text, is_valid = backend.generate_validated_descriptive_question(
                    topic, difficulty=self.difficulty, existing_questions=all_descriptive_so_far
                )
                if not is_valid:
                    self.status_update.emit(
                        f"Warning: question for topic '{topic}' may still resemble an existing question or MCQ after one retry."
                    )
                new_questions.append({"type": "descriptive", "data": question_text})
                all_descriptive_so_far.append(question_text)

            # Generate MCQs one at a time, cycling through topics
            for i in range(self.num_mcqs):
                self.status_update.emit(
                    f"Generating MCQ {i + 1} of {self.num_mcqs}..."
                )
                topic = self.topics[i % len(self.topics)]
                mcq_dict = backend.generate_mcq(topic, difficulty=self.difficulty)
                new_questions.append({"type": "mcq", "data": mcq_dict})

            self.questions_ready.emit(new_questions)

        except Exception as e:
            self.failed.emit(str(e))

class PdfSaveWorker(QThread):
    """
    Builds the final exam PDF (and text backup) from a list of already-
    generated MCQs and descriptive questions. Reuses backend.save_exam_paper
    and backend.create_exam_pdf exactly as they are — no new PDF logic.

    Signals:
    - finished_successfully: sent when saving completes with no errors
    - failed: sent if an error occurs, carrying the error message
    """

    finished_successfully = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, mcqs, descriptive_questions, exam_title, output_basename, subject):
        super().__init__()
        self.mcqs = mcqs
        self.descriptive_questions = descriptive_questions
        self.exam_title = exam_title
        self.output_basename = output_basename
        self.subject = subject

    def run(self):
        try:
            txt_filename = f"{self.output_basename}.txt"
            pdf_filename = f"{self.output_basename}.pdf"

            backend.save_exam_paper(
                self.mcqs, self.descriptive_questions, filename=txt_filename
            )
            backend.create_exam_pdf(
                self.mcqs, self.descriptive_questions,
                exam_title=self.exam_title, filename=pdf_filename,
                subject=self.subject
            )

            self.finished_successfully.emit()

        except Exception as e:
            self.failed.emit(str(e))