# Hostel Face Recognition

A local Flask application for hostel student records, browser webcam recognition,
daily attendance, and face-encoding refresh. Student records and attendance are
stored in SQLite; the original CSV and photo folder are retained as import sources.

## What the original project did

The two original Python scripts were near-duplicate Tkinter desktop applications.
Each read CSV rows into a people dictionary, loaded face images, generated 128-value
`face_recognition` encodings, and selected the nearest stored vector by Euclidean
distance. The match was accepted under a fixed `0.5` threshold. Paths were tied to
specific Windows desktops, the saved encodings used row-number IDs (one encoding
was missing), CSV columns did not match the displayed details, and exceptions could
be swallowed while saving the cache.

## Data migration notes

On the first run, all distinct named rows in `FaceDetectionDataset.csv` are imported
once into `database/hostel.sqlite3`. Photos are matched by the image filename in
each CSV row, using the local `Hostel Student` directory rather than the stale
absolute path. The ten named rows map to ten files. The extra
`WhatsApp Image 2025-10-15 at 23.33.14_174f4a85.jpg` does not identify a CSV student
and is reported as unmatched; it is not assigned or removed.

The source contains `age`, `contact`, and `notes`, not registration number, room
number, department, or guardian contact. The app preserves phone, age, and notes
where available and leaves those unavailable fields blank. No missing student
information is fabricated. New/edited records are managed in the app database.

Face encodings are regenerated from the matched student photos into `encodings.json`.
An image must contain exactly one detectable face to receive an encoding; failed
images appear in the data-quality warning panel. Unmatched photos are not encoded.
In the supplied images, `Ihsan.jpg` currently produces no detected face and therefore
has no encoding. Replace it with a clearer, front-facing photo in the app to enroll
that student for recognition; the existing image is retained.
The recognition percentage is a threshold-derived match score, not a calibrated
probability.
Student profile attendance percentage is measured against dates that have at least
one recorded check-in; it is not an academic attendance rate because the source has
no scheduled-day calendar.

## Setup (Windows)

Python 3.10–3.12 is recommended for the `face-recognition`/dlib dependency on
Windows. A compatible prebuilt dlib installation may be needed before installing
`face-recognition`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Before launching, set a private administrator password for the local sign-in:

```powershell
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "choose-a-long-private-password"
$env:FLASK_SECRET_KEY = "set-a-random-secret-for-this-machine"
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). Webcam access requires the
browser to allow camera access; localhost is treated as a secure context by modern
browsers.

## Features

- Dashboard counters, seven-day attendance chart, recent activity, and data-quality
  warnings.
- Live browser-camera recognition, student details, match score, success feedback,
  daily attendance marking, and unknown-face snapshots.
- Searchable/filterable student table, profiles, add/edit/delete forms, and photo
  uploads or webcam capture.
- Attendance log with date selection, CSV export, and browser print-to-PDF.
- Dark/light theme switch; layout adapts to mobile, tablet, and desktop screens.
- "Re-train / Refresh encodings" control and automatic refresh after student changes.

Student deletion removes the database record and associated attendance rows but
does not delete the source photo. Unknown snapshots and uploaded photos are stored
under `static/uploads/`; remove them manually only after reviewing retention needs.

## Data and privacy

Face images, face embeddings, phone numbers, and attendance records are sensitive.
Use only with appropriate consent and access controls, and define a retention
policy for snapshots. The local development server binds to `127.0.0.1`.

## Deploying to Vercel

The Vercel project uses the Flask Python preset, Python 3.12, and a Neon Postgres
database connected through the Vercel Marketplace. `DATABASE_URL` is supplied by
the Neon integration. The first application start copies the checked-in SQLite
records into Postgres, preserves their IDs and attendance history, imports any
remaining legacy CSV entries, and moves photos and face encodings into persistent
database storage. Keep the legacy data files available through this first start.

Vercel SSO protection is enabled for the deployment, and the application also
requires its administrator username and password. Set `ADMIN_USERNAME`,
`ADMIN_PASSWORD`, and `FLASK_SECRET_KEY` in Vercel for both Production and Preview.
Do not add a custom domain unless its requests are protected too. Uploaded photos,
unknown-face snapshots, and generated face encodings are stored in Postgres rather
than the function's temporary filesystem.

Static assets are served from `public/assets/`. Run the app locally with SQLite as
described above; set `DATABASE_URL` only when intentionally connecting to the
Postgres deployment.

## Compatibility

`face_recognition_app.py` remains as a compatibility entry point and starts the
Flask app. The misspelled `FaceRecognetion.py.py` has been renamed to `face_engine.py`.
