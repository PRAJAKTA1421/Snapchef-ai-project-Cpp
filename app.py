from flask import Flask, render_template, request, redirect, session, send_from_directory, g, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import re
import requests
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "snapchef_secret")

# ================= DATABASE CONFIG =================
# Use absolute path to avoid "instance" default path mismatch
database_path = os.path.join(app.root_path, "snapchef.db")
database_url = "sqlite:///" + database_path.replace('\\', '/')
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ================= MODELS =================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password = db.Column(db.String(255), nullable=False)
    dietary_preference = db.Column(db.String(100), nullable=True)  # veg/vegan/etc.
    allergies = db.Column(db.Text, nullable=True)  # comma-separated or text
    two_factor_enabled = db.Column(db.Boolean, default=False)
    app_rating = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship("Message", backref="user", lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username}>"

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    message_type = db.Column(db.String(10), nullable=False)  # 'user' or 'bot'
    text = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Message {self.id}>"

class Ingredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    health_analysis = db.Column(db.Text, nullable=True)  # Store health info

    def __repr__(self):
        return f"<Ingredient {self.name}>"

class SavedRecipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    recipe_text = db.Column(db.Text, nullable=False)
    liked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SavedRecipe {self.id} {self.user_id}>"

# ================= SCHEMA MIGRATION =================
def ensure_schema():
    db_file = db.engine.url.database

    if not os.path.exists(db_file):
        db.create_all()
        print("[INFO] Database initialized (new file created)")
        return

    with db.engine.connect() as conn:
        # Ensure all tables exist
        if conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='user'")).first() is None:
            print("[INFO] user table missing. Creating all tables...")
            db.create_all()
            return

        # Ingredient health_analysis column
        columns = conn.execute(text("PRAGMA table_info(ingredient) ")).fetchall()
        ingredient_cols = [row[1] for row in columns]
        if "health_analysis" not in ingredient_cols:
            print("[INFO] Adding missing column health_analysis to ingredient table...")
            conn.execute(text("ALTER TABLE ingredient ADD COLUMN health_analysis TEXT"))

        # User extra columns
        user_columns = conn.execute(text("PRAGMA table_info(user) ")).fetchall()
        user_col_names = [row[1] for row in user_columns]

        if "full_name" not in user_col_names:
            print("[INFO] Adding missing column full_name to user table...")
            conn.execute(text("ALTER TABLE user ADD COLUMN full_name TEXT"))

        if "email" not in user_col_names:
            print("[INFO] Adding missing column email to user table...")
            conn.execute(text("ALTER TABLE user ADD COLUMN email TEXT"))

        if "dietary_preference" not in user_col_names:
            print("[INFO] Adding missing column dietary_preference to user table...")
            conn.execute(text("ALTER TABLE user ADD COLUMN dietary_preference TEXT"))

        if "allergies" not in user_col_names:
            print("[INFO] Adding missing column allergies to user table...")
            conn.execute(text("ALTER TABLE user ADD COLUMN allergies TEXT"))

        if "two_factor_enabled" not in user_col_names:
            print("[INFO] Adding missing column two_factor_enabled to user table...")
            conn.execute(text("ALTER TABLE user ADD COLUMN two_factor_enabled BOOLEAN DEFAULT 0"))

        if "app_rating" not in user_col_names:
            print("[INFO] Adding missing column app_rating to user table...")
            conn.execute(text("ALTER TABLE user ADD COLUMN app_rating INTEGER"))

        print("[INFO] Schema is up to date.")

@app.before_request
def before_request_schema_check():
    if not hasattr(g, "schema_checked"):
        try:
            ensure_schema()
            g.schema_checked = True
        except OperationalError as e:
            print(f"[ERROR] OperationalError during before_request schema check: {e}")
            db.session.rollback()
            db.drop_all()
            db.create_all()
            g.schema_checked = True

# ================= CONFIG =================
UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# create uploads folder if not exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ================= AI FUNCTION =================
FOOD_KEYWORDS = {
    "recipe", "cook", "cooking", "meal", "dish", "breakfast", "lunch", "dinner",
    "snack", "ingredient", "ingredients", "nutrition", "healthy", "calories",
    "protein", "vitamin", "food", "eat", "eating", "kitchen", "salad", "soup",
    "rice", "pasta", "bread", "egg", "eggs", "milk", "paneer", "chicken",
    "vegetable", "veggie", "fruit"
}


def extract_ingredients_from_text(text):
    cleaned = re.sub(r"[^a-zA-Z,\n ]", " ", text.lower())
    parts = re.split(r"[\n,]", cleaned)
    ingredients = []

    for part in parts:
        item = " ".join(part.split()).strip()
        if not item or item in {"ingredients from image", "no saved ingredients yet"}:
            continue
        if len(item) > 40:
            continue
        ingredients.append(item)

    unique_items = []
    seen = set()
    for item in ingredients:
        if item not in seen:
            unique_items.append(item)
            seen.add(item)
    return unique_items[:8]


def build_local_recipe_response(prompt):
    match = re.search(r"Suggest 2 simple recipes using:\s*(.*?)(?:\.|$)", prompt, re.IGNORECASE)
    source_text = match.group(1) if match else prompt
    ingredients = extract_ingredients_from_text(source_text)
    ingredient_text = ", ".join(ingredients[:4]) if ingredients else "your available ingredients"
    first = ingredients[0] if ingredients else "mixed vegetables"
    second = ingredients[1] if len(ingredients) > 1 else "pantry staples"

    return (
        "Recipe Title: Quick Home-Style Saute\n"
        "Ingredients:\n"
        f"- {first}\n"
        f"- {second}\n"
        "- oil\n"
        "- salt\n"
        "- pepper or chili flakes\n"
        "Steps:\n"
        "1. Heat a little oil in a pan.\n"
        f"2. Add {ingredient_text} and cook for 4 to 6 minutes.\n"
        "3. Season well and serve hot.\n\n"
        "Recipe Title: Simple Comfort Bowl\n"
        "Ingredients:\n"
        f"- {first}\n"
        "- rice or bread\n"
        "- onion or garlic if available\n"
        "- salt\n"
        "- any favorite spices\n"
        "Steps:\n"
        "1. Cook the rice or toast the bread.\n"
        f"2. Saute {first} with onion or garlic and your spices.\n"
        "3. Serve together as a quick meal."
    )


def build_local_health_response(ingredient_name):
    safe_name = ingredient_name.strip() or "This ingredient"
    return (
        f"Health note for {safe_name}:\n"
        "- It can be part of a balanced diet when eaten in reasonable portions.\n"
        "- Fresh, minimally processed forms are usually the best choice.\n"
        "- If you have allergies, digestive issues, or take medication, double-check with a professional."
    )


def build_local_chatbot_reply(message, ingredients=None):
    ingredients = ingredients or []
    lower_message = message.lower()
    saved_text = ", ".join(ingredients[:6]) if ingredients else "no saved ingredients yet"

    if not any(keyword in lower_message for keyword in FOOD_KEYWORDS):
        return (
            "I can help with recipes, ingredient ideas, and nutrition tips. "
            f"Right now I can see {saved_text}. Tell me what you want to cook and I will help."
        )

    if ingredients:
        picks = ", ".join(ingredients[:3])
        return (
            f"You can make something simple with {picks}. "
            "Try a quick stir-fry, sandwich filling, or rice bowl. "
            "Tell me which ingredients you want to use and I will suggest a recipe."
        )

    return "Tell me the ingredients you have and I will suggest a quick recipe, snack idea, or nutrition tip."


def is_ai_error_text(text):
    if not text:
        return True

    lowered = text.lower()
    return (
        "httpsconnectionpool" in lowered
        or "read timed out" in lowered
        or "failed to establish a new connection" in lowered
        or "max retries exceeded" in lowered
        or "api error" in lowered
        or "please set your mistral_api_key" in lowered
        or "health analysis unavailable" in lowered
        or "could not analyze health info" in lowered
        or lowered.startswith("error:")
        or text.startswith("âš")
        or text.startswith("⚠")
    )


def get_recipe_from_ai(prompt):
    api_key = os.getenv("MISTRAL_API_KEY", "YOUR_API_KEY")
    
    # Check if API key is still a placeholder
    if api_key == "YOUR_API_KEY":
        return "⚠️ Please set your MISTRAL_API_KEY environment variable to enable AI recipes"
    
    url = "https://api.mistral.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "mistral-small",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"API Status Code: {response.status_code}")
        print(f"API Response: {response.text}")
        
        if response.status_code != 200:
            return f"⚠️ API Error {response.status_code}: {response.text}"
        
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI Error: {e}")
        return f"⚠️ Error: {str(e)}"

def get_health_analysis(ingredient_name):
    """Get health analysis for a specific ingredient"""
    api_key = os.getenv("MISTRAL_API_KEY", "YOUR_API_KEY")
    
    if api_key == "YOUR_API_KEY":
        return "⚠️ Please set your MISTRAL_API_KEY environment variable to enable health analysis"
    
    prompt = f"""Analyze the health benefits and potential concerns of the ingredient "{ingredient_name}". 
    Provide a balanced analysis covering:
    
    **Health Benefits:**
    - List 2-3 key nutritional benefits
    - Any specific health conditions it may help with
    
    **Potential Concerns:**
    - Any side effects or risks
    - Who should be cautious or avoid it
    - Any interactions with medications
    
    **Why these effects occur:**
    - Brief scientific explanation of the benefits and concerns
    
    Keep the response concise but informative. Use bullet points for clarity."""

    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "mistral-small",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"⚠️ Could not analyze health info for {ingredient_name}"
    except Exception as e:
        return f"⚠️ Health analysis unavailable: {str(e)}"

def get_recipe_from_ai(prompt):
    api_key = os.getenv("MISTRAL_API_KEY", "YOUR_API_KEY")
    if api_key == "YOUR_API_KEY":
        return build_local_recipe_response(prompt)

    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistral-small",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=20)
        print(f"API Status Code: {response.status_code}")
        print(f"API Response: {response.text}")
        if response.status_code != 200:
            print(f"AI API Error {response.status_code}: {response.text}")
            return build_local_recipe_response(prompt)

        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI Error: {e}")
        return build_local_recipe_response(prompt)


def get_health_analysis(ingredient_name):
    api_key = os.getenv("MISTRAL_API_KEY", "YOUR_API_KEY")
    if api_key == "YOUR_API_KEY":
        return build_local_health_response(ingredient_name)

    prompt = f"""Analyze the health benefits and potential concerns of the ingredient "{ingredient_name}". 
    Provide a balanced analysis covering:
    
    **Health Benefits:**
    - List 2-3 key nutritional benefits
    - Any specific health conditions it may help with
    
    **Potential Concerns:**
    - Any side effects or risks
    - Who should be cautious or avoid it
    - Any interactions with medications
    
    **Why these effects occur:**
    - Brief scientific explanation of the benefits and concerns
    
    Keep the response concise but informative. Use bullet points for clarity."""

    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistral-small",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=20)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]

        print(f"Health analysis API error for {ingredient_name}: {response.status_code}")
        return build_local_health_response(ingredient_name)
    except Exception as e:
        print(f"Health analysis error for {ingredient_name}: {e}")
        return build_local_health_response(ingredient_name)


def safe_get_recipe_response(prompt):
    try:
        ai_reply = get_recipe_from_ai(prompt)
    except Exception as e:
        print(f"Safe recipe fallback error: {e}")
        ai_reply = ""

    if not ai_reply:
        return build_local_recipe_response(prompt)

    lowered = ai_reply.lower()
    if (
        "httpsconnectionpool" in lowered
        or "read timed out" in lowered
        or "api error" in lowered
        or "please set your mistral_api_key" in lowered
        or ai_reply.startswith("âš")
    ):
        return build_local_recipe_response(prompt)

    return ai_reply


def safe_get_health_analysis(ingredient_name):
    try:
        ai_reply = get_health_analysis(ingredient_name)
    except Exception as e:
        print(f"Safe health fallback error for {ingredient_name}: {e}")
        ai_reply = ""

    if not ai_reply:
        return build_local_health_response(ingredient_name)

    lowered = ai_reply.lower()
    if (
        "httpsconnectionpool" in lowered
        or "read timed out" in lowered
        or "could not analyze health info" in lowered
        or "please set your mistral_api_key" in lowered
        or ai_reply.startswith("âš")
    ):
        return build_local_health_response(ingredient_name)

    return ai_reply


def safe_get_recipe_response(prompt):
    try:
        ai_reply = get_recipe_from_ai(prompt)
    except Exception as e:
        print(f"Safe recipe fallback error: {e}")
        ai_reply = ""

    if not ai_reply or is_ai_error_text(ai_reply):
        return build_local_recipe_response(prompt)
    return ai_reply


def safe_get_health_analysis(ingredient_name):
    try:
        ai_reply = get_health_analysis(ingredient_name)
    except Exception as e:
        print(f"Safe health fallback error for {ingredient_name}: {e}")
        ai_reply = ""

    if not ai_reply or is_ai_error_text(ai_reply):
        return build_local_health_response(ingredient_name)
    return ai_reply


def sanitize_message_text(text, message_type="bot"):
    if message_type == "bot" and is_ai_error_text(text):
        return build_local_recipe_response("Suggest 2 simple recipes using: your available ingredients.")
    return text


def get_chatbot_reply(user, message, ingredients=None):
    ingredients = ingredients or []
    ingredient_context = ", ".join(ingredients[:20]) if ingredients else "No saved ingredients yet"
    api_key = os.getenv("MISTRAL_API_KEY", "YOUR_API_KEY")

    if api_key == "YOUR_API_KEY":
        return build_local_chatbot_reply(message, ingredients)

    prompt = f"""You are SnapChef Assistant, a concise cooking helper inside a web app.

User: {user}
Saved ingredients: {ingredient_context}

User question: {message}

Instructions:
- Give a practical answer focused on cooking, ingredient usage, nutrition, or meal ideas.
- Keep it short and friendly.
- When helpful, mention ingredients from the saved list.
- Use simple bullets only if they improve readability.
- If the user asks something unrelated to food, gently steer back to SnapChef help."""

    reply = safe_get_recipe_response(prompt)
    if "Recipe Title:" in reply and "Steps:" in reply:
        return build_local_chatbot_reply(message, ingredients)
    return reply

# ================= HOME =================
@app.route("/")
def home():
    return redirect("/login")

# ================= SIGNUP =================
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        full_name = request.form.get("full_name", "")
        email = request.form.get("email", "")
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            return "Passwords do not match!"

        if User.query.filter_by(username=username).first():
            return "Username already exists!"

        if email and User.query.filter_by(email=email).first():
            return "Email already exists!"

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, full_name=full_name, email=email, password=hashed_password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            return redirect("/login")
        except Exception as e:
            db.session.rollback()
            return f"Error creating user: {str(e)}"

    return render_template("signup.html")

# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session["user"] = username
            session["user_id"] = user.id
            session.permanent = bool(request.form.get("remember"))
            session.modified = True
            return redirect("/dashboard")
        else:
            return "Invalid credentials"

    return render_template("login.html")

# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    recipe_count = SavedRecipe.query.filter_by(user_id=user_id).count()
    ingredient_count = Ingredient.query.filter_by(user_id=user_id).count()
    message_count = Message.query.filter_by(user_id=user_id).count()

    recent_recipes = SavedRecipe.query.filter_by(user_id=user_id).order_by(SavedRecipe.created_at.desc()).limit(5).all()
    recent_ingredients = Ingredient.query.filter_by(user_id=user_id).order_by(Ingredient.created_at.desc()).limit(5).all()
    recent_ratings = (
        User.query.filter(User.app_rating.isnot(None))
        .order_by(User.app_rating.desc(), User.username.asc())
        .limit(10)
        .all()
    )

    # Basic health-warnings count (contains some keyword)
    warnings = Ingredient.query.filter(Ingredient.user_id == user_id, Ingredient.health_analysis.ilike("%bad%") | Ingredient.health_analysis.ilike("%caution%") | Ingredient.health_analysis.ilike("%limit%") ).count()

    return render_template(
        "dashboard.html",
        user=session["user"],
        recipe_count=recipe_count,
        ingredient_count=ingredient_count,
        message_count=message_count,
        recent_recipes=recent_recipes,
        recent_ingredients=recent_ingredients,
        recent_ratings=recent_ratings,
        warnings=warnings,
    )

@app.route("/ingredients")
def ingredients():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    try:
        items = Ingredient.query.filter_by(user_id=user_id).order_by(Ingredient.name).all()
    except OperationalError as e:
        print(f"⚙️ OperationalError loading ingredients: {e}. Attempting schema repair.")
        with app.app_context():
            db.drop_all()
            db.create_all()
        items = []

    return render_template("ingredients.html", ingredients=items, user=session["user"])


@app.route("/saved")
def saved_recipes():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    recipes = SavedRecipe.query.filter_by(user_id=user_id).order_by(SavedRecipe.created_at.desc()).all()
    return render_template("saved.html", recipes=recipes, user=session["user"])


@app.route("/history")
def cooking_history():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    recipes = SavedRecipe.query.filter_by(user_id=user_id).order_by(SavedRecipe.created_at.desc()).all()

    def recipe_title(text):
        if not text:
            return "Untitled Recipe"
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        clean_line = first_line.replace("**", "").replace("#", "").strip(" -:")
        if len(clean_line) > 60:
            clean_line = clean_line[:57] + "..."
        return clean_line or "Untitled Recipe"

    for recipe in recipes:
        recipe.display_title = recipe_title(recipe.recipe_text)

    timeline = [
        {
            "title": recipe.display_title,
            "date": recipe.created_at.strftime("%d %b %Y"),
            "preview": recipe.recipe_text[:140].replace("\n", " ") + ("..." if len(recipe.recipe_text) > 140 else ""),
        }
        for recipe in recipes[:6]
    ]

    total_recipes = len(recipes)
    liked_recipes = sum(1 for recipe in recipes if recipe.liked)
    active_days = len({recipe.created_at.strftime("%Y-%m-%d") for recipe in recipes})
    this_month = datetime.utcnow().strftime("%Y-%m")
    monthly_recipes = sum(1 for recipe in recipes if recipe.created_at.strftime("%Y-%m") == this_month)
    latest_saved = recipes[0].created_at.strftime("%d %b") if recipes else None

    insight_points = []
    if total_recipes == 0:
        insight_points.append("No cooking activity yet. Start by saving a recipe you want to try.")
    else:
        insight_points.append(f"You have logged {total_recipes} recipe{'s' if total_recipes != 1 else ''} so far.")
        if liked_recipes:
            insight_points.append(f"{liked_recipes} recipe{'s are' if liked_recipes != 1 else ' is'} marked as liked, so your favorites are starting to stand out.")
        else:
            insight_points.append("You have not liked any saved recipes yet. Use likes to track your best dishes.")
        if monthly_recipes >= 3:
            insight_points.append("Your activity this month is strong. You are building a consistent cooking history.")
        else:
            insight_points.append("Save more recipes this month to build a clearer cooking pattern.")

    return render_template(
        "history.html",
        user=session["user"],
        recipes=recipes,
        timeline=timeline,
        total_recipes=total_recipes,
        liked_recipes=liked_recipes,
        active_days=active_days,
        monthly_recipes=monthly_recipes,
        latest_saved=latest_saved,
        insight_points=insight_points,
    )


@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    user_obj = User.query.get(user_id)
    ingredients = Ingredient.query.filter_by(user_id=user_id).order_by(Ingredient.name).all()
    total_ingredients = len(ingredients)
    warnings = Ingredient.query.filter(Ingredient.user_id == user_id, Ingredient.health_analysis.ilike("%bad%") | Ingredient.health_analysis.ilike("%caution%") | Ingredient.health_analysis.ilike("%limit%")).count()

    # Ingredient category breakdown for chart (simple keyword classification)
    categories = {
        "Vegetables": 0,
        "Protein": 0,
        "Dairy": 0,
        "Grains": 0,
        "Fruits": 0,
        "Spices": 0,
        "Other": 0,
    }

    proteins = ["chicken", "beef", "pork", "fish", "egg", "tofu", "lentil", "bean", "shrimp", "turkey"]
    veggies = ["spinach", "kale", "carrot", "broccoli", "potato", "pepper", "onion", "tomato", "cucumber", "lettuce"]
    dairy = ["milk", "cheese", "yogurt", "butter", "cream"]
    grains = ["rice", "pasta", "bread", "quinoa", "oats", "barley"]
    fruits = ["apple", "banana", "orange", "lemon", "berry", "mango", "grape"]
    spices = ["salt", "pepper", "turmeric", "cumin", "cinnamon", "ginger", "garlic", "paprika"]

    for ing in ingredients:
        name_lower = ing.name.lower()
        if any(token in name_lower for token in veggies):
            categories["Vegetables"] += 1
        elif any(token in name_lower for token in proteins):
            categories["Protein"] += 1
        elif any(token in name_lower for token in dairy):
            categories["Dairy"] += 1
        elif any(token in name_lower for token in grains):
            categories["Grains"] += 1
        elif any(token in name_lower for token in fruits):
            categories["Fruits"] += 1
        elif any(token in name_lower for token in spices):
            categories["Spices"] += 1
        else:
            categories["Other"] += 1

    chart_labels = list(categories.keys())
    chart_data = list(categories.values())

    return render_template(
        "profile.html",
        user=session["user"],
        full_name=user_obj.full_name,
        email=user_obj.email,
        dietary_preference=user_obj.dietary_preference,
        allergies=user_obj.allergies,
        total_ingredients=total_ingredients,
        warnings=warnings,
        ingredients=ingredients,
        chart_labels=chart_labels,
        chart_data=chart_data,
    )


@app.route("/nutrition")
def nutrition():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    user_obj = User.query.get(user_id)
    ingredients = Ingredient.query.filter_by(user_id=user_id).order_by(Ingredient.name).all()
    total_ingredients = len(ingredients)
    warnings = Ingredient.query.filter(
        Ingredient.user_id == user_id,
        Ingredient.health_analysis.ilike("%bad%")
        | Ingredient.health_analysis.ilike("%caution%")
        | Ingredient.health_analysis.ilike("%limit%")
    ).count()

    categories = {
        "Vegetables": 0,
        "Protein": 0,
        "Dairy": 0,
        "Grains": 0,
        "Fruits": 0,
        "Spices": 0,
        "Other": 0,
    }

    proteins = ["chicken", "beef", "pork", "fish", "egg", "tofu", "lentil", "bean", "shrimp", "turkey"]
    veggies = ["spinach", "kale", "carrot", "broccoli", "potato", "pepper", "onion", "tomato", "cucumber", "lettuce"]
    dairy = ["milk", "cheese", "yogurt", "butter", "cream", "dahi", "curd", "paneer"]
    grains = ["rice", "pasta", "bread", "quinoa", "oats", "barley", "flour"]
    fruits = ["apple", "banana", "orange", "lemon", "berry", "mango", "grape"]
    spices = ["salt", "pepper", "turmeric", "cumin", "cinnamon", "ginger", "garlic", "paprika", "masala"]

    classified_categories = {}

    for ing in ingredients:
        name_lower = ing.name.lower()
        category = "Other"
        if any(token in name_lower for token in veggies):
            category = "Vegetables"
        elif any(token in name_lower for token in proteins):
            category = "Protein"
        elif any(token in name_lower for token in dairy):
            category = "Dairy"
        elif any(token in name_lower for token in grains):
            category = "Grains"
        elif any(token in name_lower for token in fruits):
            category = "Fruits"
        elif any(token in name_lower for token in spices):
            category = "Spices"

        categories[category] += 1
        classified_categories[ing.id] = category

    highlight_points = []
    if categories["Vegetables"] >= 2:
        highlight_points.append("Vegetable coverage looks strong, which supports fiber and micronutrient intake.")
    else:
        highlight_points.append("Add more vegetables to improve fiber, vitamins, and overall meal balance.")

    if categories["Protein"] >= 1:
        highlight_points.append("You have protein sources available for satiety and muscle support.")
    else:
        highlight_points.append("Your pantry looks low on protein-rich items right now.")

    if categories["Fruits"] == 0:
        highlight_points.append("Consider adding fruit for antioxidants, hydration, and natural sweetness.")
    else:
        highlight_points.append("Fruit presence adds antioxidant and vitamin support to your ingredient mix.")

    if categories["Dairy"] == 0:
        highlight_points.append("Dairy or dairy alternatives could help round out calcium-rich options.")
    else:
        highlight_points.append("Dairy items in your pantry can contribute calcium and protein.")

    chart_labels = list(categories.keys())
    chart_data = list(categories.values())

    return render_template(
        "nutrition.html",
        user=session["user"],
        ingredients=ingredients,
        total_ingredients=total_ingredients,
        warnings=warnings,
        dietary_preference=user_obj.dietary_preference,
        allergies=user_obj.allergies,
        category_counts=categories,
        chart_labels=chart_labels,
        chart_data=chart_data,
        highlight_points=highlight_points,
        classified_categories=classified_categories,
    )


@app.route("/update_profile", methods=["POST"])
def update_profile():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id

    user_obj = User.query.get(user_id)
    if not user_obj:
        return redirect("/login")

    # Update profile fields
    user_obj.full_name = request.form.get("full_name", "").strip()
    user_obj.email = request.form.get("email", "").strip()
    user_obj.dietary_preference = request.form.get("dietary_preference", "").strip()
    user_obj.allergies = request.form.get("allergies", "").strip()

    try:
        db.session.commit()
        return redirect("/profile")
    except Exception as e:
        db.session.rollback()
        return f"Error updating profile: {str(e)}"


@app.route("/toggle_2fa", methods=["POST"])
def toggle_2fa():
    if "user" not in session:
        return jsonify({"success": False, "message": "Please log in first."}), 401

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return jsonify({"success": False, "message": "User not found."}), 404
        user_id = user_obj.id
        session["user_id"] = user_id

    user_obj = User.query.get(user_id)
    if not user_obj:
        return jsonify({"success": False, "message": "User not found."}), 404

    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get("enabled"))
    user_obj.two_factor_enabled = enabled
    db.session.commit()

    message = "2FA is now enabled for your account." if enabled else "2FA has been turned off."
    return jsonify({"success": True, "enabled": enabled, "message": message})


@app.route("/rate_app", methods=["POST"])
def rate_app():
    if "user" not in session:
        return jsonify({"success": False, "message": "Please log in first."}), 401

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return jsonify({"success": False, "message": "User not found."}), 404
        user_id = user_obj.id
        session["user_id"] = user_id

    user_obj = User.query.get(user_id)
    if not user_obj:
        return jsonify({"success": False, "message": "User not found."}), 404

    payload = request.get_json(silent=True) or {}
    rating = payload.get("rating")

    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Please choose a rating between 1 and 5."}), 400

    if rating < 1 or rating > 5:
        return jsonify({"success": False, "message": "Please choose a rating between 1 and 5."}), 400

    user_obj.app_rating = rating
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "rating": rating,
            "message": f"Thanks for rating SnapChef {rating}/5.",
        }
    )


@app.route("/save_recipe", methods=["POST"])
def save_recipe():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    recipe_text = request.form.get("recipe_text", "").strip()
    if recipe_text:
        existing = SavedRecipe.query.filter_by(user_id=user_id, recipe_text=recipe_text).first()
        if not existing:
            db.session.add(SavedRecipe(user_id=user_id, recipe_text=recipe_text))
            db.session.commit()

    return redirect("/saved")


@app.route("/like_recipe/<int:recipe_id>", methods=["POST"])
def like_recipe(recipe_id):
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    recipe = SavedRecipe.query.filter_by(id=recipe_id, user_id=user_id).first()
    if recipe:
        recipe.liked = not recipe.liked
        db.session.commit()

    return redirect("/saved")


@app.route("/add_ingredient", methods=["POST"])
def add_ingredient():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id

    ingredient_name = request.form.get("ingredient_name", "").strip()
    if ingredient_name:
        # Check if ingredient already exists for this user
        existing = Ingredient.query.filter_by(user_id=user_id, name=ingredient_name).first()
        if not existing:
            # Generate health analysis
            health_info = safe_get_health_analysis(ingredient_name)
            
            new_ingredient = Ingredient(
                user_id=user_id, 
                name=ingredient_name,
                health_analysis=health_info
            )
            db.session.add(new_ingredient)
            db.session.commit()

    return redirect("/ingredients")

@app.route("/delete_ingredient/<int:ingredient_id>", methods=["POST"])
def delete_ingredient(ingredient_id):
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id

    ingredient = Ingredient.query.filter_by(id=ingredient_id, user_id=user_id).first()
    if ingredient:
        db.session.delete(ingredient)
        db.session.commit()

    return redirect("/ingredients")

# ================= SERVE UPLOADS =================
@app.route("/uploads/<filename>")
def upload_file(filename):
    upload_path = os.path.join(app.root_path, app.config["UPLOAD_FOLDER"])
    return send_from_directory(upload_path, filename)


@app.route("/chatbot", methods=["POST"])
def chatbot():
    if "user" not in session:
        return jsonify({"reply": "Please log in to use the assistant."}), 401

    user = session["user"]
    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return jsonify({"reply": "I couldn't find your account. Please log in again."}), 401
        user_id = user_obj.id
        session["user_id"] = user_id
        session.modified = True

    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "Ask me about recipes, ingredients, or nutrition."}), 400

    ingredients = [
        item.name
        for item in Ingredient.query.filter_by(user_id=user_id).order_by(Ingredient.name).limit(20).all()
    ]
    reply = get_chatbot_reply(user=user, message=message, ingredients=ingredients)
    return jsonify({"reply": reply})

# ================= SCAN (CHAT) =================
# ================= SCAN (CHAT) =================
@app.route("/scan", methods=["GET", "POST"])
def scan():
    if "user" not in session:
        return redirect("/login")

    user = session["user"]
    
    # Get or retrieve user_id
    user_id = session.get("user_id")
    if not user_id:
        # Fallback: look up user by username
        user_obj = User.query.filter_by(username=user).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id
        session.modified = True

    if request.method == "POST":

        file = request.files.get("image")
        text = request.form.get("message", "").strip()

        image_path = None

        # ✅ IMAGE SAVE
        if file and file.filename != "":
            filename = secure_filename(file.filename)

            # 👉 absolute path fix
            upload_path = os.path.join(os.getcwd(), app.config["UPLOAD_FOLDER"])

            # ensure folder exists
            if not os.path.exists(upload_path):
                os.makedirs(upload_path)

            filepath = os.path.join(upload_path, filename)

            print("Saving at:", filepath)  # debug

            file.save(filepath)

            # 👉 store URL path for HTML
            image_path = f"/uploads/{filename}"

        # ✅ USER MESSAGE - Only add if text or image exists
        if text or image_path:
            user_message = Message(
                user_id=user_id,
                message_type="user",
                text=text if text else "Uploaded image",
                image=image_path
            )
            db.session.add(user_message)
            db.session.commit()

            # Save our ingredients from user text if provided
            if text:
                # typical input: "eggs, milk, spinach" or lines
                fragments = [item.strip() for item in text.replace('\n', ',').split(',') if item.strip()]
                for ingredient_name in fragments:
                    # Avoid duplicates (simple case-insensitive contain)
                    exists = Ingredient.query.filter_by(user_id=user_id, name=ingredient_name).first()
                    if not exists:
                        # Generate health analysis for new ingredient
                        health_info = safe_get_health_analysis(ingredient_name)
                        db.session.add(Ingredient(
                            user_id=user_id, 
                            name=ingredient_name,
                            health_analysis=health_info
                        ))
                db.session.commit()

            # 🤖 AI RESPONSE - Only generate if we have content
            recipe_query = text if text else 'ingredients from image'
            prompt = (
                f"Suggest 2 simple recipes using: {recipe_query}. "
                "Format each recipe as:\n"
                "Recipe Title: <title>\n"
                "Ingredients:\n- item1\n- item2\n...\n"
                "Steps:\n"
                "1. Step 1 description\n"
                "2. Step 2 description\n"
                "...\n"
                "Ensure clear labels and numbered steps."
            )
            ai_text = safe_get_recipe_response(prompt)

            bot_message = Message(
                user_id=user_id,
                message_type="bot",
                text=ai_text,
                image=None
            )
            db.session.add(bot_message)
            db.session.commit()

        return redirect("/scan")

    # Get messages from database
    messages = Message.query.filter_by(user_id=user_id).all()
    messages_data = [
        {
            "type": msg.message_type,
            "text": sanitize_message_text(msg.text, msg.message_type),
            "image": msg.image
        }
        for msg in messages
    ]

    return render_template("scan.html",
                           messages=messages_data,
                           user=user)
# ================= RECIPE SUGGESTIONS =================
@app.route("/suggestions")
def suggestions():
    if "user" not in session:
        return redirect("/login")

    user_id = session.get("user_id")
    if not user_id:
        user_obj = User.query.filter_by(username=session["user"]).first()
        if not user_obj:
            return redirect("/login")
        user_id = user_obj.id
        session["user_id"] = user_id

    # Static list of 25 recipes
    recipes = [
        {
            "title": "Classic Spaghetti Carbonara",
            "ingredients": "200g spaghetti, 100g pancetta, 2 eggs, 50g parmesan, black pepper",
            "instructions": "1. Cook spaghetti in salted water. 2. Fry pancetta until crispy. 3. Whisk eggs with parmesan. 4. Drain pasta, mix with pancetta, then add egg mixture off heat. 5. Season with pepper.",
            "time": "20 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Chicken Caesar Salad",
            "ingredients": "300g chicken breast, romaine lettuce, croutons, parmesan, caesar dressing",
            "instructions": "1. Grill chicken breast until cooked. 2. Chop lettuce and slice chicken. 3. Toss with croutons, parmesan, and dressing. 4. Serve immediately.",
            "time": "15 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Beef Tacos",
            "ingredients": "500g ground beef, taco shells, lettuce, tomato, cheese, salsa",
            "instructions": "1. Brown ground beef with seasoning. 2. Warm taco shells. 3. Fill with beef, lettuce, tomato, cheese. 4. Top with salsa.",
            "time": "20 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Vegetable Stir Fry",
            "ingredients": "Mixed vegetables (broccoli, carrots, bell peppers), tofu, soy sauce, garlic, ginger",
            "instructions": "1. Heat oil in wok. 2. Add garlic and ginger. 3. Add vegetables and tofu. 4. Stir fry for 5-7 mins. 5. Add soy sauce and serve.",
            "time": "15 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Chocolate Chip Cookies",
            "ingredients": "2 cups flour, 1 cup butter, 3/4 cup sugar, 1 cup chocolate chips, 1 egg",
            "instructions": "1. Cream butter and sugar. 2. Add egg and vanilla. 3. Mix in flour and chocolate chips. 4. Drop onto baking sheet. 5. Bake at 350°F for 10-12 mins.",
            "time": "25 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Grilled Salmon",
            "ingredients": "4 salmon fillets, lemon, olive oil, salt, pepper, herbs",
            "instructions": "1. Season salmon with salt, pepper, and herbs. 2. Brush with olive oil. 3. Grill for 4-5 mins per side. 4. Squeeze lemon juice over top. 5. Serve hot.",
            "time": "15 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Mushroom Risotto",
            "ingredients": "200g arborio rice, 300g mushrooms, 1L vegetable stock, onion, white wine, parmesan",
            "instructions": "1. Sauté onion and mushrooms. 2. Add rice and toast. 3. Add wine and reduce. 4. Gradually add stock, stirring constantly. 5. Finish with parmesan.",
            "time": "40 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Chicken Curry",
            "ingredients": "500g chicken, curry paste, coconut milk, onion, garlic, rice",
            "instructions": "1. Sauté onion and garlic. 2. Add curry paste and chicken. 3. Pour in coconut milk. 4. Simmer for 20 mins. 5. Serve with rice.",
            "time": "30 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Caprese Salad",
            "ingredients": "Tomatoes, mozzarella, basil, olive oil, balsamic vinegar",
            "instructions": "1. Slice tomatoes and mozzarella. 2. Arrange alternately on plate. 3. Add basil leaves. 4. Drizzle with oil and vinegar. 5. Season with salt and pepper.",
            "time": "10 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Beef Stir Fry",
            "ingredients": "400g beef strips, broccoli, carrots, soy sauce, garlic, ginger",
            "instructions": "1. Marinate beef in soy sauce. 2. Stir fry beef until browned. 3. Add vegetables and garlic. 4. Cook until tender. 5. Serve over rice.",
            "time": "20 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Pancakes",
            "ingredients": "2 cups flour, 2 eggs, 1.5 cups milk, butter, maple syrup",
            "instructions": "1. Mix dry ingredients. 2. Whisk eggs and milk. 3. Combine and rest. 4. Cook on griddle until bubbles form. 5. Flip and cook through. 6. Serve with syrup.",
            "time": "20 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Shakshuka",
            "ingredients": "4 eggs, tomatoes, onion, bell peppers, cumin, paprika, bread",
            "instructions": "1. Sauté onion and peppers. 2. Add tomatoes and spices. 3. Simmer until thickened. 4. Crack eggs into sauce. 5. Cook until eggs set. 6. Serve with bread.",
            "time": "25 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Greek Salad",
            "ingredients": "Cucumber, tomatoes, feta, olives, red onion, olive oil, oregano",
            "instructions": "1. Chop vegetables. 2. Crumble feta. 3. Combine all ingredients. 4. Dress with oil and oregano. 5. Toss gently.",
            "time": "10 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Chicken Parmesan",
            "ingredients": "4 chicken breasts, breadcrumbs, parmesan, marinara sauce, mozzarella, pasta",
            "instructions": "1. Bread chicken breasts. 2. Fry until golden. 3. Top with sauce and cheese. 4. Bake until cheese melts. 5. Serve with pasta.",
            "time": "35 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Vegetable Soup",
            "ingredients": "Mixed vegetables, vegetable stock, onion, garlic, herbs",
            "instructions": "1. Sauté onion and garlic. 2. Add vegetables and stock. 3. Simmer for 20 mins. 4. Blend if desired. 5. Season and serve.",
            "time": "30 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Beef Burgers",
            "ingredients": "500g ground beef, burger buns, lettuce, tomato, cheese, condiments",
            "instructions": "1. Form beef into patties. 2. Season and grill. 3. Add cheese to melt. 4. Assemble on buns with toppings. 5. Serve immediately.",
            "time": "20 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Pad Thai",
            "ingredients": "Rice noodles, shrimp, tofu, bean sprouts, peanuts, tamarind sauce",
            "instructions": "1. Soak noodles. 2. Stir fry shrimp and tofu. 3. Add noodles and sauce. 4. Toss with bean sprouts. 5. Top with peanuts.",
            "time": "25 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Roast Chicken",
            "ingredients": "Whole chicken, potatoes, carrots, herbs, olive oil",
            "instructions": "1. Season chicken inside and out. 2. Place vegetables around chicken. 3. Roast at 375°F for 1.5 hours. 4. Rest before carving.",
            "time": "90 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Quinoa Bowl",
            "ingredients": "Quinoa, chickpeas, avocado, cherry tomatoes, feta, lemon dressing",
            "instructions": "1. Cook quinoa. 2. Roast chickpeas. 3. Assemble bowl with ingredients. 4. Dress with lemon vinaigrette. 5. Serve fresh.",
            "time": "25 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Lasagna",
            "ingredients": "Lasagna noodles, ground beef, ricotta, mozzarella, marinara sauce",
            "instructions": "1. Cook noodles. 2. Brown beef and make sauce. 3. Layer noodles, meat, cheese. 4. Bake for 45 mins. 5. Let rest before serving.",
            "time": "60 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Fish Tacos",
            "ingredients": "White fish, corn tortillas, cabbage slaw, lime, cilantro",
            "instructions": "1. Season and grill fish. 2. Warm tortillas. 3. Fill with fish and slaw. 4. Squeeze lime and add cilantro. 5. Serve immediately.",
            "time": "20 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Miso Soup",
            "ingredients": "Miso paste, tofu, seaweed, green onions, dashi stock",
            "instructions": "1. Heat dashi stock. 2. Add miso paste. 3. Add tofu and seaweed. 4. Simmer gently. 5. Garnish with green onions.",
            "time": "10 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Chicken Fajitas",
            "ingredients": "Chicken strips, bell peppers, onion, fajita seasoning, tortillas",
            "instructions": "1. Marinate chicken in seasoning. 2. Sauté chicken and vegetables. 3. Warm tortillas. 4. Fill and serve with toppings.",
            "time": "25 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Ratatouille",
            "ingredients": "Eggplant, zucchini, tomatoes, onion, garlic, herbs",
            "instructions": "1. Sauté vegetables separately. 2. Layer in baking dish. 3. Bake covered for 40 mins. 4. Uncover and bake more. 5. Serve hot or cold.",
            "time": "60 mins",
            "difficulty": "Medium"
        },
        {
            "title": "Breakfast Burrito",
            "ingredients": "Tortillas, eggs, potatoes, cheese, salsa, avocado",
            "instructions": "1. Scramble eggs. 2. Cook potatoes. 3. Warm tortillas. 4. Fill with ingredients. 5. Roll and serve.",
            "time": "20 mins",
            "difficulty": "Easy"
        },
        {
            "title": "Thai Green Curry",
            "ingredients": "Green curry paste, coconut milk, chicken, vegetables, basil, rice",
            "instructions": "1. Fry curry paste. 2. Add coconut milk. 3. Add chicken and vegetables. 4. Simmer until cooked. 5. Add basil and serve with rice.",
            "time": "30 mins",
            "difficulty": "Medium"
        }
    ]

    return render_template("suggestions.html",
                         recipes=recipes,
                         user=session["user"])

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.pop("user", None)
    session.pop("user_id", None)
    return redirect("/login")

# ================= RUN =================
if __name__ == "__main__":
    with app.app_context():
        try:
            ensure_schema()
        except OperationalError as e:
            print(f"⚠️ OperationalError during startup schema check: {e}. Recreating tables.")
            db.session.rollback()
            db.drop_all()
            db.create_all()

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
