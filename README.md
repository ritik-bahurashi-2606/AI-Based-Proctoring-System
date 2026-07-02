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
- OpenCV, dlib, TensorFlow, DeepFace
- YOLO model weights for object detection
- HTML, CSS, and JavaScript templates

## Prerequisites

Install these before running the project:

- Python 3.10 or newer
- MySQL Server
- Git LFS
- Visual C++ build tools may be required for packages such as `dlib` on Windows

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

Update `.env` with your local MySQL credentials, mail settings, and application secrets.

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

