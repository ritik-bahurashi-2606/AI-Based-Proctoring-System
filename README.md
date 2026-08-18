# AI-Based Proctoring System

AI-Based Proctoring System is a Flask web application for conducting online examinations with automated proctoring. It combines exam management, student authentication, live camera monitoring, face validation, gaze/head movement checks, object detection, and instructor-facing malpractice reports.

## Features

- Online exam workflow for students and professors
- Objective, subjective, and practical question support
- AI-based proctoring with face, gaze, head movement, and mobile-phone detection
- Multiple-person detection during active exams
- Liveness and face verification support
- Copy-paste, tab/window switching, and screenshot/print-screen protection
- Cheating logs, risk scoring, and timeline reports for professors
- MySQL-backed data storage
- Git LFS support for large model files

## Tech Stack

- Python and Flask
- MySQL
- OpenCV, dlib/dlib-bin, TensorFlow, DeepFace, InsightFace
- YOLOv3 weights plus optional Ultralytics YOLO models for object detection
- HTML, CSS, and JavaScript templates

## Prerequisites

Install these before running the project:

- Python 3.10 or newer
- MySQL Server
- Git LFS
- Python 3.10 is recommended on Windows because TensorFlow 2.10 is the last TensorFlow release with Windows CPU wheels

## Setup

Clone the repository:

```bash
git clone https://github.com/ritikbahurashi25-a11y/AI-Based-Proctoring-System.git
cd AI-Based-Proctoring-System
```

Install and pull Git LFS files:

```bash
git lfs install
git lfs pull
```

Create and activate a virtual environment:

```bash
python -m venv venv
venv\Scripts\activate
```

On macOS/Linux:

```bash
python -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the environment file:

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

Update `.env` with your local MySQL credentials, mail settings, application secrets, and optional model backend settings.

## Model Backend Configuration

The model backend framework is configured with environment variables in `.env`.
All backend variables default to `auto`, which selects the upgraded backend when
its dependency/model is available and falls back to the legacy implementation
when initialization fails.

| Variable | Default | Supported values | Purpose |
| --- | --- | --- | --- |
| `PROCTOR_FACE_BACKEND` | `auto` | `auto`, `mediapipe`, `retinaface`, `opencv` | Face box detection during proctoring |
| `PROCTOR_LANDMARK_BACKEND` | `auto` | `auto`, `mediapipe`, `tensorflow` | Face landmark detection for head/gaze signals |
| `PROCTOR_FACE_MATCH_BACKEND` | `auto` | `auto`, `insightface`, `deepface` | Student login face matching |
| `PROCTOR_OBJECT_BACKEND` | `auto` | `auto`, `ultralytics`, `yolov8`, `yolov11`, `yolov3` | Person/mobile object detection |

Custom Ultralytics object models can be configured with:

```env
PROCTOR_OBJECT_BACKEND=ultralytics
PROCTOR_OBJECT_MODEL_PATH=models/custom-proctor-model.pt
```

If `PROCTOR_OBJECT_MODEL_PATH` is empty or does not point to an existing file,
the application uses `PROCTOR_OBJECT_MODEL_NAME` instead:

```env
PROCTOR_OBJECT_MODEL_NAME=yolov8n.pt
```

`yolov8n.pt` is the default model name and may be downloaded by Ultralytics on
first use. Downloaded runtime model caches such as `yolov8n.pt` and
`models/models/` are intentionally ignored by Git; commit only source code,
configuration templates, and intentionally managed model assets.

Invalid or unavailable upgraded backends fail gracefully by returning to the
legacy OpenCV/TensorFlow/YOLOv3 path where that path exists. Face matching uses
InsightFace first in `auto` mode and falls back to DeepFace if embeddings cannot
be produced.

## Database Setup

1. Create a MySQL database for the application.
2. Import the schema from `DB/quizappstructure.sql`.
3. Make sure the database name and credentials match your `.env` file.

## Run

Start the Flask application:

```bash
python app.py
```

Open the app in your browser:

```text
http://localhost:5000
```

## Important Notes

- Do not commit `.env`; use `.env.example` for shared configuration names.
- Large model files are tracked with Git LFS. Run `git lfs pull` after cloning.
- Runtime folders such as `flask_session`, `registration_tokens`, and generated evidence should stay untracked.

## Project Structure

```text
app.py                    Main Flask application
camera.py                 Camera and monitoring helpers
face_verifier.py          Face verification logic
proctoring_policy.py      Proctoring rules and scoring support
DB/                       Database schema and related files
models/                   AI model assets
gaze_tracking/            Gaze tracking code and trained models
templates/                HTML templates
static/                   Static frontend assets
requirements.txt          Python dependencies
.env.example              Example environment configuration
```

## License

This project is intended for academic and educational use. Add a license file before public production use.

