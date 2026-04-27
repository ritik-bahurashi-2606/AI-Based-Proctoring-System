# MyProctor.ai - Setup Guide

This guide will help you set up and run the MyProctor.ai AI-based online examination proctoring system.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Structure](#project-structure)
3. [Installation Steps](#installation-steps)
4. [Database Setup](#database-setup)
5. [Configuration](#configuration)
6. [Running the Application](#running-the-application)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Python 3.8 - 3.11** (Recommended: Python 3.9 or 3.10)
  - Note: The project may have compatibility issues with Python 3.14 due to package version constraints
- MySQL Database (MySQL 8.0 recommended)
- Git (optional)

---

## Project Structure

```
MyProctor.ai-AI-BASED-SMART-ONLINE-EXAMINATION-PROCTORING-SYSYTEM/
├── app.py                      # Main Flask application
├── camera.py                   # Proctoring and camera processing
├── face_detector.py           # Face detection models
├── face_landmarks.py          # Facial landmark detection
├── objective.py               # Objective test generation
├── subjective.py              # Subjective test generation
├── requirements.txt           # Python dependencies
├── .env.example              # Environment variables template
├── venv/                    # Virtual environment (auto-created)
├── models/                  # AI/ML model files
│   ├── classes.TXT
│   ├── deploy.prototxt
│   ├── opencv_face_detector.pbtxt
│   ├── opencv_face_detector_uint8.pb
│   ├── yolov3.weights           # YOLOv3 for mobile detection
│   ├── pose_model/              # Face landmark model
│   └── res10_300x300_ssd_iter_140000.caffemodel (optional)
├── gaze_tracking/            # Gaze tracking module
├── eye_tracking/             # Eye tracking utilities
├── coco models/              # COCO dataset models
├── DB/                       # Database schemas
│   └── quizappstructure.sql
├── static/                   # Static assets (CSS, JS, images)
└── templates/                # HTML templates
```

---

## Installation Steps

### 1. Create Virtual Environment (if not already created)

```bash
cd MyProctor.ai-AI-BASED-SMART-ONLINE-EXAMINATION-PROCTORING-SYSYTEM

# For Windows:
python -m venv venv

# For Linux/Mac:
python3 -m venv venv
```

### 2. Activate Virtual Environment

```bash
# For Windows (Command Prompt):
venv\Scripts\activate.bat

# For Windows (PowerShell):
venv\Scripts\Activate.ps1

# For Linux/Mac:
source venv/bin/activate
```

### 3. Upgrade pip

```bash
pip install --upgrade pip setuptools wheel
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

**Note:** If you encounter issues with pandas on Python 3.14+, consider using Python 3.9-3.11 instead, or install compatible versions:
```bash
pip install "pandas>=1.1.5" "numpy>=1.16.0" "Flask>=1.1.2" ...
```

### 5. Download Required Model Files

The following model files should be present in the `models/` directory:

- ✅ `yolov3.weights` (236MB) - For mobile phone detection
- ✅ `opencv_face_detector_uint8.pb` + `opencv_face_detector.pbtxt` - Face detection (TensorFlow)
- ✅ `pose_model/saved_model.pb` - Facial landmark detection
- ✅ `deploy.prototxt` + `classes.TXT`

**Already downloaded:**
- yolov3.weights ✅
- opencv_face_detector_uint8.pb ✅
- opencv_face_detector.pbtxt ✅
- pose_model/saved_model.pb ✅
- deploy.prototxt ✅
- classes.TXT ✅

If any files are missing, you can download them from:
- YOLOv3 weights: https://pjreddie.com/media/files/yolov3.weights
- OpenCV face detector: https://github.com/opencv/opencv_3rdparty/tree/opencv_face_detector

---

## Database Setup

### 1. Install MySQL

Download and install MySQL from https://dev.mysql.com/downloads/installer/

Default configuration:
- Port: 3308 (as specified in app.py)
- Username: root
- Password: Set your own password

### 2. Create Database

```sql
-- Open MySQL Command Line or MySQL Workbench
CREATE DATABASE quizapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE quizapp;

-- Import the database schema
SOURCE path/to/quizappstructure.sql;
```

### 3. Verify Database Connection

Update the database credentials in your `.env` file (see Configuration section).

---

## Configuration

### 1. Create .env file

Copy the example environment file and customize it:

```bash
cp .env.example .env
```

Edit the `.env` file with your settings:

```ini
# Flask Configuration
SECRET_KEY=your-secret-key-here-change-this

# MySQL Database Configuration
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_PORT=3308
MYSQL_DB=quizapp
MYSQL_CURSORCLASS=DictCursor

# Flask-Mail Configuration (for email notifications)
MAIL_SERVER=smtp.gmail.com  # or your SMTP provider
MAIL_PORT=587
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password  # Use app-specific password for Gmail
MAIL_USE_TLS=True
MAIL_USE_SSL=False
MAIL_DEFAULT_SENDER=your-email@gmail.com

# Stripe Configuration (for payments, optional)
STRIPE_SECRET_KEY=your_stripe_secret_key
STRIPE_PUBLISHABLE_KEY=your_stripe_publishable_key

# Application Settings
SESSION_TYPE=filesystem
SESSION_COOKIE_SAMESITE=None
TEMPLATES_AUTO_RELOAD=True
YOUR_DOMAIN=http://localhost:5000
```

**Important:** Change the default values, especially:
- `SECRET_KEY` - Generate a strong random secret key
- `MYSQL_PASSWORD` - Your actual MySQL password
- Mail settings - Configure your SMTP server for email functionality

### 2. Configure Webhooks for PayPal/Stripe (Optional)

If payment functionality is needed:
- Set up Stripe webhook endpoints
- Update webhook secret keys in .env

---

## Running the Application

### Development Mode

```bash
cd MyProctor.ai-AI-BASED-SMART-ONLINE-EXAMINATION-PROCTORING-SYSYTEM
source venv/Scripts/activate  # or venv\Scripts\activate on Windows
python app.py
```

The application will start at: `http://localhost:5000`

### Production Mode (using Gunicorn/Waitress)

For Windows production:
```bash
pip install waitress
waitress-serve --port=5000 app:app
```

For Linux/Mac:
```bash
pip install gunicorn
gunicorn -w 4 app:app
```

---

## Features

### For Professors:
- Create and manage exams (objective, subjective, practical)
- AI-generated questions and answers
- Live monitoring of exams
- View proctoring logs
- Publish results
- Recharge wallet

### For Students:
- Take exams with proctoring
- View exam history and results
- Real-time camera and screen monitoring
- Gaze tracking and head pose estimation
- Mobile phone detection
- Tab change detection
- Audio frequency monitoring

### Proctoring Features:
- Face recognition and verification
- Multiple person detection
- Gaze estimation
- Head movement tracking
- Eye blink detection
- Mobile phone detection using YOLOv3
- Cut/copy/paste prevention
- VM and screen-sharing detection

---

## Troubleshooting

### 1. Import Errors

**Problem:** `ModuleNotFoundError: No module named 'xxx'`

**Solution:** Ensure virtual environment is activated and all dependencies are installed:
```bash
source venv/Scripts/activate  # Windows
pip install -r requirements.txt
```

### 2. MySQL Connection Failed

**Problem:** Can't connect to MySQL database

**Solution:**
- Check MySQL service is running: `sudo service mysql start` (Linux) or check Windows Services
- Verify credentials in `.env` file
- Confirm port (default: 3308, standard: 3306)
- Grant permissions: `GRANT ALL ON quizapp.* TO 'root'@'localhost';`

### 3. TensorFlow/Keras Errors

**Problem:** TensorFlow not working or model loading errors

**Solution:**
- Ensure TensorFlow 2.x is installed
- Check `models/pose_model/saved_model.pb` exists
- Use Python 3.8-3.11 for best compatibility

### 4. OpenCV Issues

**Problem:** OpenCV camera/performance issues

**Solution:**
- Install `opencv-contrib-python` (included in requirements)
- Update graphics drivers
- Check webcam permissions

### 5. Email Not Sending

**Problem:** Mail server connection fails

**Solution:**
- For Gmail, enable 2-factor auth and use App Password
- Check `MAIL_SERVER` and `MAIL_PORT` settings
- Allow less secure apps (if not using 2FA)

### 6. Session Issues

**Problem:** Sessions not persisting

**Solution:**
- Ensure `SESSION_TYPE=filesystem` in .env
- Check directory permissions for session files
- Set `SESSION_COOKIE_SAMESITE=None` for external access

### 7. Model Download Failed

The `yolov3.weights` file (236MB) may fail to download due to network issues.

**Solution:** Manual download:
1. Visit: https://pjreddie.com/media/files/yolov3.weights
2. Download the file
3. Place it in the `models/` directory

---

## Testing the Installation

### Test Database Connection

```bash
python -c "from app import mysql; print('Database connection OK' if mysql else 'Failed')"
```

### Test Flask App

```bash
python app.py
# Visit http://localhost:5000
```

### Test Proctoring Module

```bash
python -c "import camera; print('Camera module loaded successfully')"
```

---

## Security Notes

1. **Change all default passwords and secret keys**
2. Use HTTPS in production
3. Regularly update dependencies: `pip list --outdated`
4. Configure CORS appropriately for your domain
5. Implement rate limiting for exam endpoints
6. Store `.env` file securely and add to `.gitignore`

---

## Support

For issues and feature requests, please refer to the project repository:
[https://github.com/narender-rk10/MyProctor.ai-AI-BASED-SMART-ONLINE-EXAMINATION-PROCTORING-SYSYTEM](https://github.com/narender-rk10/MyProctor.ai-AI-BASED-SMART-ONLINE-EXAMINATION-PROCTORING-SYSYTEM)

---

## License

This project is licensed under the Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License (CC BY-NC-ND 4.0).
