AI-Powered Student Engagement & Attendance System
A production-ready system designed to automate student attendance and track engagement using AI-based facial recognition and emotion detection.

🚀 Features
Automated Attendance: Real-time facial recognition to mark attendance seamlessly.

Emotion Analysis: Utilizes DeepFace to track engagement levels within the classroom.

FastAPI Backend: High-performance API architecture for real-time data processing.

Dashboard Support: Structured to work with data logging for reporting.

🛠 Tech Stack
Backend: FastAPI

AI Engine: DeepFace (TensorFlow/Keras)

Data Storage: CSV logging

Interface: RESTful API (Swagger UI integrated)

📋 How to Run Locally
1.  Clone the repository:

Bash
git clone https://github.com/iMarkhany/AI-Attendance-Monitoring-System.git
cd AI-Attendance-Monitoring-System

2.  Setup Virtual Environment:

Bash
python -m venv .venv
.venv\Scripts\activate

3.  Install Dependencies:

Bash
pip install -r requirements.txt

4.  Run the Application:

Bash
uvicorn main:app --reload

5.  Access API Documentation:
Open your browser and visit: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
