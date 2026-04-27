# MyProctor.ai - AI Based Online Examination & Proctoring System

MyProctor.ai is a state-of-the-art online examination platform equipped with powerful AI proctoring. It monitors students in real-time, detecting suspicious activities such as mobile phone usage, multiple people in the frame, and suspicious eye/head movements.

## 🚀 Features

- **AI Proctoring:** Real-time object detection (Mobile phones), person counting, and gaze tracking.
- **Instant Alerts:** Real-time warnings sent to students if misbehavior is detected.
- **Professor Dashboard:** Comprehensive cheating reports with risk scores and timeline analysis.
- **Question Management:** Automated question generation and manual question creation (Objective, Subjective, and Practical).
- **Security:** Built-in copy-paste protection, window-switching detection, and print-screen blocking.

---

## 🛠️ Setup Instructions for Team Members

Follow these steps exactly to run the project on your local machine:

### 1. Prerequisites
- **Python 3.10+** installed.
- **MySQL Server** installed and running.
- **Git LFS** (Very Important!): Download and install from [git-lfs.github.com](https://git-lfs.github.com/).

### 2. Clone and Initialize LFS
```bash
git clone <YOUR_REPO_URL>
cd MyProctor.ai-AI-BASED-SMART-ONLINE-EXAMINATION-PROCTORING-SYSYTEM
git lfs install
git lfs pull
```

### 3. Setup Virtual Environment
```bash
python -m venv venv
venv\Scripts\activate      # On Windows
source venv/bin/activate   # On Linux/Mac
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Setup Environment Variables
- Copy `.env.example` to a new file named `.env`.
- Open `.env` and fill in your local MySQL credentials (`MYSQL_PASSWORD`) and Gmail settings.
```bash
copy .env.example .env
```

### 6. Setup Database
- Open MySQL Workbench or your favorite SQL client.
- Import the SQL schema from: `DB/quizappstructure.sql`.
- Ensure the database name in your `.env` matches the one you created (`myproctor`).

### 7. Run the Application
```bash
python app.py
```
Go to `http://localhost:5000` in your browser.

---

## 🛡️ Proctoring Logic
The application captures snapshots every **2 seconds** during an active exam. The AI engine (YOLOv3) processes these snapshots on the server to detect:
- 📱 **Mobile Phones**
- 👤 **Multiple People**
- ↔️ **Suspicious Head Movements**
- 👁️ **Eye Gaze Deviations**

Cheating logs are saved to the `proctoring_log` table and displayed to professors in the **Cheating Report** dashboard.
