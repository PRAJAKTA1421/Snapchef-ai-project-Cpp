# SnapChef

SnapChef is a Flask web app for scanning fridge ingredients, saving recipes, tracking pantry activity, viewing nutrition info, and managing cooking history.

## Tech Stack

- Python
- Flask
- Flask-SQLAlchemy
- SQLite
- HTML/CSS/JavaScript

## Run Locally

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file and add your API key:

```env
MISTRAL_API_KEY=your_api_key_here
```

4. Start the app:

```bash
python app.py
```

## Push To GitHub

This project is already a git repository. After creating a GitHub repo, run:

```bash
git add .
git commit -m "Prepare SnapChef for GitHub"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

## Important Note About Hosting

GitHub can host your code repository, but GitHub Pages cannot run this Flask app because it only supports static sites.

For this project, the usual setup is:

- GitHub: store your source code
- Render / Railway / PythonAnywhere: run the Flask app

## Recommended Deployment Flow

1. Push this project to GitHub.
2. Create a new web service on Render or Railway.
3. Connect your GitHub repo.
4. Set the start command to:

```bash
gunicorn app:app
```

5. Add your `MISTRAL_API_KEY` in the hosting platform environment variables.

## Render Deployment

This repo now includes:

- `requirements.txt`
- `Procfile`
- `render.yaml`

Steps:

1. Push the code to GitHub.
2. Go to Render.
3. Create a new `Web Service`.
4. Connect your GitHub repository.
5. Render should detect the Python app automatically.
6. Add these environment variables:

```env
MISTRAL_API_KEY=your_api_key_here
SECRET_KEY=your_secret_here
```

7. Deploy.

## Important SQLite Note

This app currently uses SQLite. On many cloud hosts, local disk can be temporary, so your database may reset on redeploy or restart unless you attach persistent storage or move to PostgreSQL.

## Files Ignored From GitHub

The `.gitignore` excludes local-only files such as:

- `.env`
- `.venv`
- `__pycache__`
- `snapchef.db`
- uploaded files
