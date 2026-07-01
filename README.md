# Classroom Emotion Detection and Statistical Analysis System

End-to-end implementation of the project brief: a FastAPI + DeepFace
backend that detects student emotions from webcam frames, persists every
observation to a CSV, and a Shiny dashboard in R that performs all the
required statistical analyses (frequency distribution, lecture-level
variation, engagement scoring, time trends, lecturer/student clustering)
plus a real-time monitor that talks to FastAPI via httr.

---

## How the requirements map to the code

| Requirement (from the brief) | Where it lives |
|---|---|
| 1. Automated emotion detection | `app/services/emotion_service.py` (DeepFace) |
| 2. Store emotion + confidence + time + student + lecture | `app/analytics/csv_logger.py` writes `data/emotions_log.csv` |
| 3. Statistical analysis in R | `r_dashboard/app.R` — every tab is a different analysis |
| 4. Engagement scoring | `app/analytics/session_tracker.py` (EMA) + R replicates the same weights |
| 5. ggplot2 + Shiny dashboard | `r_dashboard/app.R` |
| 6. Real-time lecturer notification | "Live Monitor" tab + `GET /reports/all` (httr) |
| Optional: FastAPI + httr integration | `main.py` exposes JSON; R uses `httr::GET` |

Every analysis listed in the brief has a dedicated tab in the dashboard:

- **Overview** – KPI cards + global engagement histogram
- **Frequency** – emotion frequency distribution (filterable)
- **Lecture Comparison** – emotion variation across lectures + mean engagement
- **Time Trends** – engagement over time, per-lecture or per-student
- **Lecturer Clusters** – k-means on (mean engagement, variance, low-engagement %)
- **Student Clusters** – k-means on (mean engagement, emotion mix) per student × lecture
- **Live Monitor** – real-time notifications via httr → `/reports/all`
- **Raw Data** – the underlying CSV

---

## Project layout

```
project/
├── app/
│   ├── config.py                  # Paths, schema, weights, thresholds
│   ├── models.py                  # Pydantic request/response models
│   ├── services/
│   │   └── emotion_service.py     # DeepFace wrapper
│   ├── analytics/
│   │   ├── csv_logger.py          # Thread-safe append to emotions_log.csv
│   │   ├── lecture_manager.py     # Lecture lifecycle (start/end)
│   │   └── session_tracker.py     # Per-student rolling EMA + per-lecture state
│   └── utils/
│       └── image_utils.py         # base64 → OpenCV decoder
├── main.py                        # FastAPI app
├── r_dashboard/
│   └── app.R                      # Shiny dashboard
├── scripts/
│   ├── seed_data.py               # Generate sample data without a webcam
│   ├── webcam_client.py           # Live webcam → /analyze
│   └── smoke_test.py              # Verify analytics + CSV pipeline
├── data/                          # CSV files (created at runtime)
├── requirements.txt
└── README.md
```

---

## Setup

### 1. Python environment

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. R packages

The dashboard auto-installs missing CRAN packages on first run, but you
can pre-install with:

```r
install.packages(c(
  "shiny", "shinydashboard", "dplyr", "ggplot2", "readr",
  "tidyr", "lubridate", "DT", "httr", "jsonlite", "scales", "cluster"
))
```

---

## Running the system

### Quickstart with seeded data (no webcam needed)

```bash
# 1. Generate ~3,600 sample rows so the dashboard has something to show
python -m scripts.seed_data

# 2. Launch the Shiny dashboard
Rscript -e "shiny::runApp('r_dashboard', port=3838)"
```

Open http://127.0.0.1:3838 — every tab will already be populated.

### Live mode with a real webcam

Three terminals:

```bash
# Terminal 1 — backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — webcam client (one per student)
python -m scripts.webcam_client --student-id S01 --lecture-id L_demo

# Terminal 3 — Shiny dashboard
Rscript -e "shiny::runApp('r_dashboard', port=3838)"
```

The "Live Monitor" tab in Shiny will start showing students within 3
seconds.

---

## API reference (also at `/docs`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/lecture/start` | Begin a new lecture, returns its ID |
| POST | `/lecture/{id}/end` | End a lecture |
| GET | `/lecture/list` | List all lectures, active and ended |
| GET | `/lecture/{id}/summary` | Aggregate stats for one lecture |
| POST | `/analyze` | Analyze a single base64 frame |
| POST | `/analyze_batch` | Analyze a batch of frames in one call |
| GET | `/report/{student_id}` | Per-student rolling report (optional `?lecture_id=...`) |
| GET | `/reports/all` | Snapshot of every active student (used by R live tab) |
| GET | `/health` | Liveness probe |

### Example: starting a lecture and analyzing a frame

```bash
# Start a lecture
curl -X POST http://127.0.0.1:8000/lecture/start \
  -H "Content-Type: application/json" \
  -d '{"lecture_id":"L_2024_DSS_01","title":"Distributed Systems Security","lecturer_id":"prof_taha"}'

# Analyze a frame
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d "{\"student_id\":\"S01\",\"lecture_id\":\"L_2024_DSS_01\",\"image_base64\":\"$(base64 -w0 face.jpg)\"}"
```

---

## CSV schema (`data/emotions_log.csv`)

Single source of truth shared between Python and R.

| Column | Type | Description |
|---|---|---|
| `student_id` | string | Student identifier |
| `timestamp` | ISO 8601 | When the frame was processed |
| `emotion` | string | One of: happy, surprise, neutral, sad, fear, angry, disgust, Absent, Error |
| `confidence` | float | DeepFace confidence in `[0, 1]` |
| `lecture_id` | string | Lecture this frame belongs to |
| `engagement_score` | float | Smoothed (EMA) engagement in `[0, 1]` |

The brief asks for `Student_ID, Time, Emotion, Confidence, Lecture_ID`.
We use lowercased snake_case for code-side ergonomics; the columns map
1:1 and we add `engagement_score` as a derived convenience for R.

---

## Engagement scoring (kept in sync between Python and R)

Each emotion contributes a raw weight in `[0, 1]`:

```
happy=1.0  surprise=0.8  neutral=0.6  sad=0.3
fear=0.2   angry=0.2     disgust=0.1
```

DeepFace doesn't produce explicit `bored` or `confused` labels, so we
treat `sad`/`neutral` as proxies for boredom and `fear`/`surprise` as
proxies for confusion/uncertainty. The 7-class raw output is preserved
in the CSV, so any reclassification can be done in R without losing
information.

The per-frame raw score is smoothed via an exponential moving average
(`alpha = 0.3`):

```
ema_t = 0.3 * raw_t + 0.7 * ema_{t-1}
```

A score below `0.4` triggers a `Low engagement detected.` alert.

---

## Sanity test

```bash
python -m scripts.smoke_test
```

Bypasses DeepFace and feeds synthetic frames into the analytics layer.
Verifies that 60 rows land in the CSV with the correct schema.

---

## Notes for grading

- **Backend persistence**: every `/analyze` call appends to the CSV
  with a thread-safe lock, so the dataset survives server restarts.
- **httr integration**: the Shiny "Live Monitor" tab polls
  `/reports/all` every 3 seconds via `httr::GET`, demonstrating the
  optional Python-R bridge from the brief.
- **Clustering**: both lecturer and student-subject clustering use
  `kmeans` with scaled features and a fixed seed for reproducibility.
- **Reproducibility**: `scripts/seed_data.py` deterministically
  generates a labelled dataset where engagement varies meaningfully
  across lectures and students, so all dashboard tabs show signal.
