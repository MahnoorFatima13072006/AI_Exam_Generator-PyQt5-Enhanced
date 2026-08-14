# AI Exam Generator

A desktop application that generates professional exam papers (MCQs and descriptive questions) from a curriculum file using AI, with a review-and-select workflow before producing the final PDF.

Built with **PyQt5** for the interface and the **Groq API** (Llama 3.3 70B) for question generation.

---

## Features

- **Upload a curriculum file** (`.txt`) and automatically split it into topics
- **Configurable generation** — choose the number of MCQs, number of descriptive questions, and difficulty level (Easy / Moderate / Hard)
- **Candidate question review** — generated questions appear as a checklist instead of being locked into the final paper immediately
- **Generate 1 More Question** — add a single additional question (MCQ or Descriptive, your choice) at any time without regenerating or losing existing questions or selections
- **Selective final exam** — only the questions you check are included in the final paper, with validation to ensure a minimum number are selected
- **Automatic PDF generation** — a polished, university-style exam paper (with name/roll no. fields, instructions, sectioned MCQs and descriptive questions, and page numbers), plus a plain-text backup
- **Background threading** — all AI generation and PDF building run on background threads so the interface never freezes
- **Quality control on descriptive questions:**
  - Detects and rejects descriptive questions that are actually disguised MCQs (lettered options, "which of the following," etc.)
  - Detects and rejects near-duplicate descriptive questions using text similarity, checked against the full session history
  - Each check allows exactly **one retry** — no infinite regeneration loops
- **Fresh session on new upload** — uploading a new curriculum file automatically resets all previous questions, selections, and topics, so nothing from a prior exam can leak into a new one

---

## Project Structure

```
├── main.py      # Application entry point
├── gui.py       # PyQt5 interface: layout, user interaction, state management
├── worker.py    # QThread workers that run AI generation and PDF saving in the background
├── backend.py   # Core logic: syllabus parsing, Groq API calls, question validation, PDF/text generation
```

### File responsibilities

| File | Responsibility |
|---|---|
| `main.py` | Launches the `QApplication` and shows the main window |
| `gui.py` | Builds the UI, handles button clicks, manages the candidate question list and checkbox state, resets session state on new uploads |
| `worker.py` | `QuestionBatchWorker` generates batches of candidate questions (and single additions) on a background thread; `PdfSaveWorker` builds the final PDF/text output in the background |
| `backend.py` | Loads and splits the curriculum, builds prompts and calls the Groq API, validates descriptive questions (MCQ-pattern and duplicate detection), and generates the final PDF/text exam using ReportLab |

---

## How It Works

1. **Upload Curriculum** — select a `.txt` file containing topics (separated by blank lines). The app resets any previous session state and loads the new topics.
2. **Configure** — set the number of MCQs, number of descriptive questions, and difficulty level.
3. **Generate Questions** — the app generates a batch of candidate questions in the background. Each descriptive question is automatically validated (not MCQ-shaped, not a duplicate of an earlier question) with one retry if it fails.
4. **Review** — candidate questions appear as a checklist. Select the ones you want.
5. **Generate 1 More Question** *(optional)* — pick a question type from the dropdown and add one more question without disturbing your existing selections.
6. **Generate Final PDF** — once you've selected at least the minimum required number of questions, the app builds a professional exam PDF (plus a `.txt` backup) containing only your selected questions.

---

## Setup

### Requirements

- Python 3.9+
- A [Groq API key](https://console.groq.com/)

### Installation

```bash
pip install PyQt5 groq reportlab
```

### API Key

The app reads your Groq API key from an environment variable — it is never hard-coded in the source.

**Windows (PowerShell):**
```powershell
$env:GROQ_API_KEY="your-api-key-here"
```

**macOS/Linux:**
```bash
export GROQ_API_KEY="your-api-key-here"
```

### Run

```bash
python main.py
```
