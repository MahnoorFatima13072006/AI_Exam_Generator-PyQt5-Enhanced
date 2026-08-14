from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QLabel, QFileDialog, QMessageBox,
    QSpinBox, QComboBox, QScrollArea, QCheckBox
)

from worker import ExamWorker, QuestionBatchWorker, PdfSaveWorker
import backend

class MainWindow(QMainWindow):
    """
    Main application window for the AI Exam Generator.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Exam Generator")
        self.resize(500, 500)
        self.syllabus_path = None
        self.worker = None  # will hold our background worker while it's running
        self.candidate_questions = [] # holds all generated question dicts, e.g. {"type": "mcq"/"descriptive", "data": ...}
        self.topics = []  # holds the list of topics extracted from the uploaded syllabus
        self.MIN_SELECTED_QUESTIONS = 1  # minimum number of questions the user must select before generating the PDF
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Upload button
        self.upload_button = QPushButton("Upload Curriculum")
        self.upload_button.clicked.connect(self.browse_file)
        layout.addWidget(self.upload_button)

        # File name label
        self.file_label = QLabel("No file selected")
        layout.addWidget(self.file_label)

        # Number of MCQs
        self.mcq_count_label = QLabel("Number of MCQs:")
        layout.addWidget(self.mcq_count_label)

        self.mcq_count_input = QSpinBox()
        self.mcq_count_input.setMinimum(1)
        self.mcq_count_input.setMaximum(30)
        self.mcq_count_input.setValue(10)
        layout.addWidget(self.mcq_count_input)

        # Number of Descriptive Questions
        self.descriptive_count_label = QLabel("Number of Descriptive Questions:")
        layout.addWidget(self.descriptive_count_label)

        self.descriptive_count_input = QSpinBox()
        self.descriptive_count_input.setMinimum(1)
        self.descriptive_count_input.setMaximum(30)
        self.descriptive_count_input.setValue(10)
        layout.addWidget(self.descriptive_count_input)

        # Difficulty Level dropdown
        self.difficulty_label = QLabel("Difficulty Level:")
        layout.addWidget(self.difficulty_label)

        self.difficulty_input = QComboBox()
        self.difficulty_input.addItems(["Easy", "Moderate", "Hard"])
        self.difficulty_input.setCurrentText("Moderate")
        layout.addWidget(self.difficulty_input)

        # Generate Questions button (renamed from "Generate Exam" — this now
        # generates CANDIDATE questions for review, not the final PDF directly)
        self.generate_button = QPushButton("Generate Questions")
        self.generate_button.clicked.connect(self.generate_exam_clicked)
        layout.addWidget(self.generate_button)

        # Status label, shows progress messages
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # --- Candidate questions checklist area ---
        self.questions_area_label = QLabel("Candidate Questions:")
        self.questions_area_label.setVisible(False)
        layout.addWidget(self.questions_area_label)

        self.questions_scroll_area = QScrollArea()
        self.questions_scroll_area.setWidgetResizable(True)
        self.questions_scroll_area.setVisible(False)

        self.questions_container = QWidget()
        self.questions_layout = QVBoxLayout()
        self.questions_container.setLayout(self.questions_layout)
        self.questions_scroll_area.setWidget(self.questions_container)

        layout.addWidget(self.questions_scroll_area)

        # List that keeps a reference to each checkbox we create, in the
        # same order as self.candidate_questions, so we can check which
        # ones are ticked later
        self.question_checkboxes = []

        # Dropdown to choose which type of question "Generate 1 More" should add
        self.more_question_type_label = QLabel("Type for next question:")
        self.more_question_type_label.setVisible(False)
        layout.addWidget(self.more_question_type_label)

        self.more_question_type_input = QComboBox()
        self.more_question_type_input.addItems(["Descriptive", "MCQ"])
        self.more_question_type_input.setVisible(False)
        layout.addWidget(self.more_question_type_input)

        # "Generate 1 More Question" button — hidden until we have results
        self.generate_more_button = QPushButton("Generate 1 More Question")
        self.generate_more_button.setVisible(False)
        self.generate_more_button.clicked.connect(self.generate_one_more_clicked)
        layout.addWidget(self.generate_more_button)

        # "Generate Final PDF" button — hidden until we have results
        self.generate_pdf_button = QPushButton("Generate Final PDF")
        self.generate_pdf_button.setVisible(False)
        self.generate_pdf_button.clicked.connect(self.generate_final_pdf_clicked)
        layout.addWidget(self.generate_pdf_button)

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Curriculum File",
            "",
            "Text Files (*.txt)"
        )

        if file_path:
            # A new curriculum is being loaded — reset all state tied to the
            # previous curriculum/exam before processing the new file, so
            # nothing from the old session leaks into the new one
            self.reset_exam_state()

            self.syllabus_path = file_path
            self.file_label.setText(f"Selected: {file_path}")

            # Load and split the syllabus into topics right away, so they're
            # ready to use as soon as the user clicks "Generate Questions"
            try:
                syllabus_text = backend.load_syllabus(file_path)
                self.topics = backend.split_into_topics(syllabus_text)
            except Exception as e:
                self.topics = []
                QMessageBox.critical(
                    self,
                    "Error Reading File",
                    f"Could not read the curriculum file:\n{e}"
                )
    def reset_exam_state(self):
        """
        Clears all temporary state tied to the previous curriculum/exam
        session, so a newly uploaded curriculum starts completely fresh.
        Does NOT touch user preferences (MCQ/Descriptive counts, difficulty,
        or MIN_SELECTED_QUESTIONS) since those should persist.
        """
        # Clear the stored questions and topics from the previous curriculum
        self.candidate_questions = []
        self.topics = []

        # Remove the old checkbox widgets from the screen
        for checkbox in self.question_checkboxes:
            checkbox.setParent(None)
        self.question_checkboxes = []

        # Hide the checklist area and related buttons again, since there
        # are no questions yet for the new curriculum
        self.questions_area_label.setVisible(False)
        self.questions_scroll_area.setVisible(False)
        self.more_question_type_label.setVisible(False)
        self.more_question_type_input.setVisible(False)
        self.generate_more_button.setVisible(False)
        self.generate_pdf_button.setVisible(False)

        # Clear the leftover status message from the previous session
        self.status_label.setText("")

    def get_existing_descriptive_texts(self):
        """
        Returns a plain list of the text of every descriptive question
        already in self.candidate_questions, for duplicate-checking
        against newly generated ones. MCQs are not included since
        duplicate-checking is only for descriptive questions.
        """
        return [
            q["data"] for q in self.candidate_questions
            if q["type"] == "descriptive"
        ]
    def generate_exam_clicked(self):
        """
        Runs when "Generate Questions" is clicked. Generates a batch of
        candidate questions (using the counts/difficulty the user chose)
        and displays them as a checklist, instead of immediately building
        a PDF.
        """
        if not self.syllabus_path:
            QMessageBox.warning(
                self,
                "No File Selected",
                "Please upload a curriculum file first."
            )
            return

        if not self.topics:
            QMessageBox.warning(
                self,
                "No Topics Found",
                "No topics could be found in the uploaded curriculum file."
            )
            return

        # Read the current values from our controls
        num_mcqs = self.mcq_count_input.value()
        num_descriptive = self.descriptive_count_input.value()
        difficulty = self.difficulty_input.currentText()

        # Disable inputs while generating, so the user can't change anything mid-run
        self.upload_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.mcq_count_input.setEnabled(False)
        self.descriptive_count_input.setEnabled(False)
        self.difficulty_input.setEnabled(False)
        self.status_label.setText("Starting...")

       # Create the batch worker with all the details it needs
        self.worker = QuestionBatchWorker(
            topics=self.topics,
            num_mcqs=num_mcqs,
            num_descriptive=num_descriptive,
            difficulty=difficulty,
            existing_descriptive_questions=self.get_existing_descriptive_texts()
        )
        # Connect the worker's signals to our own methods
        self.worker.status_update.connect(self.on_status_update)
        self.worker.questions_ready.connect(self.on_initial_questions_ready)
        self.worker.failed.connect(self.on_generation_failed)

        # Start the background thread (this triggers worker.run())
        self.worker.start()

    def on_initial_questions_ready(self, new_questions):
        """
        Called when the QuestionBatchWorker finishes generating the FIRST
        batch of candidate questions. Stores them and displays them as
        checkboxes.
        """
        self.candidate_questions.extend(new_questions)
        self.refresh_question_checkboxes()

        self.status_label.setText(f"Generated {len(new_questions)} candidate question(s).")
        self.upload_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.mcq_count_input.setEnabled(True)
        self.descriptive_count_input.setEnabled(True)
        self.difficulty_input.setEnabled(True)

    def refresh_question_checkboxes(self):
        """
        Rebuilds the checklist display from self.candidate_questions.
        Called any time the list changes (after initial generation, or
        after "Generate 1 More Question"). Preserves which questions
        were checked before the rebuild.
        """
        # Remember which question INDEXES were checked before we rebuild,
        # so we can re-check the same ones afterward
        previously_checked_indexes = set()
        for i, checkbox in enumerate(self.question_checkboxes):
            if checkbox.isChecked():
                previously_checked_indexes.add(i)

        # Clear out any existing checkboxes first
        for checkbox in self.question_checkboxes:
            checkbox.setParent(None)
        self.question_checkboxes = []

        # Build one checkbox per candidate question
        for i, question in enumerate(self.candidate_questions):
            display_number = i + 1
            if question["type"] == "mcq":
                label_text = f"Q{display_number} (MCQ): {question['data']['question']}"
            else:
                label_text = f"Q{display_number} (Descriptive): {question['data']}"

            checkbox = QCheckBox(label_text)

            # Re-check this box if it was checked before the rebuild
            if i in previously_checked_indexes:
                checkbox.setChecked(True)

            self.questions_layout.addWidget(checkbox)
            self.question_checkboxes.append(checkbox)

        # Reveal the checklist area and the new buttons now that we have questions
        self.questions_area_label.setVisible(True)
        self.questions_scroll_area.setVisible(True)
        self.more_question_type_label.setVisible(True)
        self.more_question_type_input.setVisible(True)
        self.generate_more_button.setVisible(True)
        self.generate_pdf_button.setVisible(True)
    def generate_one_more_clicked(self):
        """
        Runs when "Generate 1 More Question" is clicked. Generates exactly
        one additional candidate question (of the type chosen in the
        dropdown) and appends it to the existing list, without touching
        the questions already generated.
        """
        difficulty = self.difficulty_input.currentText()
        chosen_type = self.more_question_type_input.currentText()  # "Descriptive" or "MCQ"

        # Disable buttons while generating, so the user can't click again mid-run
        self.generate_button.setEnabled(False)
        self.generate_more_button.setEnabled(False)
        self.generate_pdf_button.setEnabled(False)
        self.status_label.setText(f"Generating one more {chosen_type} question...")

        if chosen_type == "MCQ":
            self.worker = QuestionBatchWorker(
                topics=self.topics,
                num_mcqs=1,
                num_descriptive=0,
                difficulty=difficulty,
                existing_descriptive_questions=self.get_existing_descriptive_texts()
            )
        else:
            self.worker = QuestionBatchWorker(
                topics=self.topics,
                num_mcqs=0,
                num_descriptive=1,
                difficulty=difficulty,
                existing_descriptive_questions=self.get_existing_descriptive_texts()
            )

        self.worker.status_update.connect(self.on_status_update)
        self.worker.questions_ready.connect(self.on_one_more_question_ready)
        self.worker.failed.connect(self.on_generation_failed)

        self.worker.start()

    def on_one_more_question_ready(self, new_questions):
        """
        Called when the QuestionBatchWorker finishes generating the ONE
        extra question. Appends it (without removing existing ones) and
        refreshes the checklist.
        """
        self.candidate_questions.extend(new_questions)
        self.refresh_question_checkboxes()

        self.status_label.setText("Added 1 new question.")
        self.generate_button.setEnabled(True)
        self.generate_more_button.setEnabled(True)
        self.generate_pdf_button.setEnabled(True)
    def generate_final_pdf_clicked(self):
        """
        Runs when "Generate Final PDF" is clicked. Collects only the
        questions whose checkbox is ticked, validates there are enough
        of them, asks where to save, and builds the PDF using the
        existing backend PDF-generation code.
        """
        # Match each checkbox back to its question by position, since
        # question_checkboxes and candidate_questions are built in the same order
        selected_questions = [
            question for question, checkbox in zip(self.candidate_questions, self.question_checkboxes)
            if checkbox.isChecked()
        ]

        if len(selected_questions) < self.MIN_SELECTED_QUESTIONS:
            QMessageBox.warning(
                self,
                "Not Enough Questions Selected",
                f"Please select at least {self.MIN_SELECTED_QUESTIONS} question(s) "
                f"before generating the final PDF.\n\n"
                f"Currently selected: {len(selected_questions)}"
            )
            return

        # Ask the user where to save the PDF
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Exam PDF As",
            "Generated_Exam.pdf",
            "PDF Files (*.pdf)"
        )
        if not save_path:
            return

        if save_path.lower().endswith(".pdf"):
            output_basename = save_path[:-4]
        else:
            output_basename = save_path

        # Split the selected questions back into separate MCQ / descriptive
        # lists, since that's what create_exam_pdf() and save_exam_paper() expect
        selected_mcqs = [q["data"] for q in selected_questions if q["type"] == "mcq"]
        selected_descriptive = [q["data"] for q in selected_questions if q["type"] == "descriptive"]

        # Disable buttons while saving
        self.generate_button.setEnabled(False)
        self.generate_more_button.setEnabled(False)
        self.generate_pdf_button.setEnabled(False)
        self.status_label.setText("Building final PDF...")

        self.worker = PdfSaveWorker(
            mcqs=selected_mcqs,
            descriptive_questions=selected_descriptive,
            exam_title="Sample Examination",
            output_basename=output_basename,
            subject="General"
        )

        self.worker.finished_successfully.connect(self.on_pdf_success)
        self.worker.failed.connect(self.on_pdf_failed)

        self.worker.start()

    def on_pdf_success(self):
        """Called when PdfSaveWorker finishes successfully."""
        self.status_label.setText("Final PDF generated successfully!")
        self.generate_button.setEnabled(True)
        self.generate_more_button.setEnabled(True)
        self.generate_pdf_button.setEnabled(True)

        QMessageBox.information(
            self,
            "Success",
            "Your final exam PDF has been generated and saved successfully!"
        )

    def on_pdf_failed(self, error_message):
        """Called if PdfSaveWorker runs into an error."""
        self.status_label.setText("PDF generation failed.")
        self.generate_button.setEnabled(True)
        self.generate_more_button.setEnabled(True)
        self.generate_pdf_button.setEnabled(True)

        QMessageBox.critical(
            self,
            "Error",
            f"Something went wrong while generating the final PDF:\n{error_message}"
        )
    def on_status_update(self, message):
        """Called whenever the worker sends a status_update signal."""
        self.status_label.setText(message)

    def on_generation_failed(self, error_message):
        """Called if the worker runs into an error."""
        self.status_label.setText("Failed.")
        self.upload_button.setEnabled(True)
        self.generate_button.setEnabled(True)
        self.mcq_count_input.setEnabled(True)
        self.descriptive_count_input.setEnabled(True)
        self.difficulty_input.setEnabled(True)

        QMessageBox.critical(
            self,
            "Error",
            f"Something went wrong while generating the exam:\n{error_message}"
        )