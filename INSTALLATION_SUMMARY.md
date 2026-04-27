# MyProctor.ai - Installation Summary

**Date:** March 31, 2026
**Status:** ✅ Installation Guide Complete

---

## Completed Setup Tasks

### 1. Virtual Environment
- ✅ Created: `venv/`
- ✅ Python packages installed

### 2. Python Dependencies
All required packages installed with Python 3.14 compatible versions:

**Core Flask Stack:**
- Flask 3.1.3
- Flask-WTF 1.2.2
- Flask-Mail 0.10.0
- Flask-MySQLdb 2.0.0
- Flask-Cors 6.0.2
- Werkzeug 3.1.7
- WTForms 3.2.1
- WTForms-Components 0.11.0

**AI/ML Stack:**
- TensorFlow 2.21.0
- DeepFace 0.0.99
- numpy 2.4.3
- pandas 3.0.1
- matplotlib 3.10.8

**Computer Vision:**
- opencv-contrib-python 4.13.0.92

**Utilities:**
- python-docx
- nltk 3.9.4
- stripe
- wget
- coolname 4.1.0
- Pillow
- six
- python-dotenv

### 3. AI Model Files

All required models are present in `models/` directory:

| File | Size | Purpose |
|------|------|---------|
| `yolov3.weights` | 237MB | Mobile phone detection (YOLOv3) |
| `opencv_face_detector_uint8.pb` | 2.7MB | Face detection (TensorFlow) |
| `opencv_face_detector.pbtxt` | 37KB | Face detection config |
| `pose_model/saved_model.pb` | 66KB | Facial landmark detection |
| `deploy.prototxt` | 30KB | Caffe model config (if needed) |
| `classes.TXT` | 703B | COCO class labels |

### 4. Configuration Files

| File | Description |
|------|-------------|
| `.env.example` | Template for environment variables - **COPY THIS TO `.env`** |
| `requirements.txt` | Updated to use flexible version constraints |
| `SETUP_GUIDE.md` | Comprehensive setup documentation |
| `setup.bat` | Windows automated setup script |

### 5. Code Updates

Modified files:
- `app.py` - Environment variable loading via `python-dotenv`
  - Added: `import os` and `from dotenv import load_dotenv`
  - Added: `load_dotenv()` at startup
  - Replaced hardcoded configs with `os.getenv()` calls
  - Updated secret key to use environment variable
- `camera.py` - Switched to TensorFlow quantized model
  - Changed: `face_model = get_face_detector(quantized=True)`
  - This uses the `.pb` model instead of `.caffemodel`

---

## Required User Actions

### 1. Create .env File
```bash
cp .env.example .env
```
Then edit `.env` with your actual credentials.

### 2. Set Up MySQL Database

**Option A: Using MySQL Command Line**
```bash
mysql -u root -p
CREATE DATABASE quizapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
exit
mysql -u root -p quizapp < DB/quizappstructure.sql
```

**Option B: Using phpMyAdmin**
1. Create database `quizapp`
2. Import `DB/quizappstructure.sql`

### 3. Configure Email Settings
Update `.env` with your SMTP credentials:
- For Gmail: Use App Password (enable 2FA first)
- For other providers: Check their SMTP settings

### 4. (Optional) Stripe Configuration
If using payments, add Stripe keys to `.env`

---

## Quick Start Commands

```bash
# 1. Activate virtual environment
cd MyProctor.ai-AI-BASED-SMART-ONLINE-EXAMINATION-PROCTORING-SYSYTEM
venv\Scripts\activate  # Windows
# OR: source venv/bin/activate  # Linux/Mac

# 2. Make sure .env is configured

# 3. Run the application
python app.py

# 4. Open browser
# http://localhost:5000
```

---

## Troubleshooting

### Python Version
**If you encounter pandas build errors:** Use Python 3.9-3.11 instead of 3.14

### Missing Model Files
All models are present. If `yolov3.weights` is missing (236MB), download from:
https://pjreddie.com/media/files/yolov3.weights

### MySQL Connection
- Check MySQL is running
- Verify port `3308` (or change to `3306` in .env)
- Grant permissions to user

### Port Conflicts
If port 5000 is in use, modify `app.py` or set `PORT` environment variable.

---

## File Checklist

- [x] `venv/` - Virtual environment
- [x] `requirements.txt` - Dependencies
- [x] `app.py` - Main application
- [x] `camera.py` - Proctoring module
- [x] `face_detector.py` - Face detection
- [x] `face_landmarks.py` - Landmarks
- [x] `objective.py` - Objective questions
- [x] `subjective.py` - Subjective questions
- [x] `models/yolov3.weights` ✅
- [x] `models/opencv_face_detector_uint8.pb` ✅
- [x] `models/opencv_face_detector.pbtxt` ✅
- [x] `models/pose_model/saved_model.pb` ✅
- [x] `gaze_tracking/` - Gaze module
- [x] `eye_tracking/` - Eye tracking utilities
- [x] `coco models/` - COCO models and labels
- [x] `DB/quizappstructure.sql` - Database schema
- [x] `static/` - CSS/JS/Images
- [x] `templates/` - HTML templates
- [x] `.env.example` - Config template
- [x] `SETUP_GUIDE.md` - Full documentation
- [x] `setup.bat` - Windows setup script
- [x] `SETUP_SUMMARY.md` - This file

---

## Next Steps After Installation

1. ✅ All dependencies installed
2. ⬜ Create `.env` file with your credentials
3. ⬜ Set up MySQL database
4. ⬜ Run `python app.py`
5. ⬜ Navigate to `http://localhost:5000`
6. ⬜ Register a user account
7. ⬜ Test proctoring features
8. ⬜ Configure email settings for full functionality

---

## Support Resources

- **README.md** - Original project documentation
- **SETUP_GUIDE.md** - Detailed setup instructions
- **Project Repo:** https://github.com/narender-rk10/MyProctor.ai-AI-BASED-SMART-ONLINE-EXAMINATION-PROCTORING-SYSYTEM
- **YouTube Demo:** https://youtu.be/E117db5VsTs

---

**All resources and dependencies are now ready for deployment!** 🚀
