from flask import Flask, render_template, request, redirect, url_for, session, flash ,jsonify
import sqlite3
import os
import uuid
from datetime import datetime 
from datetime import timedelta
import numpy as np
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import requests
from geopy.geocoders import Nominatim
from werkzeug.utils import secure_filename
from groq import Groq
import base64
import cv2
import io
import re
from PIL import Image
from flask_cors import CORS
from flask_caching import Cache
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import lru_cache

from deep_translator import GoogleTranslator
import json
import os
from translation import register_translation_handlers
from translation import test_translation_service
import pandas as pd
import numpy as np

# import seaborn as sns
# import matplotlib.pyplot as plt
# from sklearn.model_selection import train_test_split
# from sklearn.ensemble import RandomForestClassifier
# from sklearn.metrics import accuracy_score, classification_report, confusion_matrix




# Initialize Flask app (ONLY ONCE at the top)
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True           # Force template reload
app.jinja_env.cache = None 

app.secret_key = "farmadvisorapp2025"  # Set secret key here
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
app.config['SESSION_TYPE'] = 'filesystem'  # Or 'redis' for production
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)

@app.after_request
def add_no_cache_headers(response):
    """Kill all caching for dynamic pages"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
    SESSION_REFRESH_EACH_REQUEST=True
)

register_translation_handlers(app)

# Enable CORS
CORS(app)

# Configure Flask-Caching (SimpleCache for development)
cache = Cache(app, config={
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 300  # 5 minutes
})

# Configure Groq client
groq_client = Groq(api_key="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")
GROQ_MODEL = "llama3-70b-8192"  # or another appropriate model

load_dotenv()
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
GROQ_API_KEY="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"

OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
if not OPENWEATHERMAP_API_KEY:
    raise ValueError("Missing OPENWEATHERMAP_API_KEY in environment variables")

# Location-based data retrieval functions
def get_coordinates(location):
    geolocator = Nominatim(user_agent="farm_advisor_app", timeout=10)
    location_data = geolocator.geocode(location)
    if location_data:
        return {
            "Latitude": round(location_data.latitude, 2),
            "Longitude": round(location_data.longitude, 2),
            "Location": location
        }
    else:
        return None
    
def get_weather(location):
    coordinates = get_coordinates(location)
    if not coordinates:
        return None

    lat, lon = coordinates["Latitude"], coordinates["Longitude"]
    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHERMAP_API_KEY}&units=metric"

    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        return {
            **coordinates,
            "Temperature": round(data.get("main", {}).get("temp", 0), 2),
            "Humidity": data.get("main", {}).get("humidity", 50),
            "Rainfall": data.get("rain", {}).get("1h", 0) or 0  # Default to 0 if no rain data
        }
    else:
        return None

def get_soil_data(lat, lon):
    url = f"https://rest.isric.org/soilgrids/v2.0/properties/query?lon={lon}&lat={lat}"
    
    properties = ["phh2o", "sand", "clay", "silt", "ocd", "nitrogen"]
    response = requests.get(url)

    if response.status_code == 200:
        soil_data = response.json()
        soil_info = {
            "Latitude": lat, 
            "Longitude": lon,
            "Nitrogen": 50,  # Default values in case API doesn't return these
            "Phosphorus": 50,
            "Potassium": 50,
            "pH": 7.0
        }
        
        for layer in soil_data.get("properties", {}).get("layers", []):  
            prop_name = layer.get("name", "")
            if prop_name in properties:
                try:
                    value = layer["depths"][0]["values"]["mean"]

                    if value is not None:
                        # Adjust pH scale
                        if prop_name == "phh2o":
                            value /= 10
                            soil_info["pH"] = round(value, 2)
                        # Estimate NPK values based on soil composition
                        elif prop_name == "nitrogen":
                            soil_info["Nitrogen"] = min(140, max(0, round(value * 0.8, 2)))
                        elif prop_name == "silt":
                            # Phosphorus often correlates with silt content
                            soil_info["Phosphorus"] = min(145, max(0, round(value * 0.5, 2)))
                        elif prop_name == "clay":
                            # Potassium often correlates with clay content
                            soil_info["Potassium"] = min(205, max(0, round(value * 0.7, 2)))
                except KeyError:
                    pass
        
        return soil_info
    else:
        # Return default values if API fails
        return {
            "Latitude": lat,
            "Longitude": lon,
            "Nitrogen": 50,
            "Phosphorus": 50,
            "Potassium": 50,
            "pH": 7.0
        }

# Groq API integration
def get_groq_prediction(input_data):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""
    Based on the following soil and weather parameters, recommend the best crop to grow:
    
    Nitrogen: {input_data['Nitrogen']} mg/kg
    Phosphorus: {input_data['Phosphorus']} mg/kg
    Potassium: {input_data['Potassium']} mg/kg
    pH: {input_data['pH']}
    Rainfall: {input_data['Rainfall']} mm
    Temperature: {input_data['Temperature']} °C
    Humidity: {input_data['Humidity']} %
    
    Please provide a detailed recommendation including:
    1. Top 3 recommended crops based on these parameters
    2. Brief explanation of why these crops are suitable
    3. Basic care instructions for the recommended crops
    4. Any warnings or special considerations
    """
    
    payload = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", 
                               json=payload, 
                               headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"Error: Unable to get crop recommendation. Status code: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

def get_db_connection():
    conn = sqlite3.connect('farm_advisor.db', timeout=10)  # Increase timeout
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")  # Enable WAL mode here
    return conn

def init_db():
    conn = sqlite3.connect('farm_advisor.db')
    cursor = conn.cursor()

    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        farmer_id TEXT DEFAULT NULL,
        location TEXT NOT NULL DEFAULT 'Unknown',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Create reports table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        report_id TEXT UNIQUE NOT NULL,
        crop_recommendation TEXT,
        soil_n REAL,
        soil_p REAL,
        soil_k REAL,
        soil_ph REAL,
        rainfall REAL,
        temperature REAL,
        humidity REAL,
        leaf_analysis TEXT,
        fertilizer_recommendation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    conn.commit()
    conn.close()

# Initialize the database
init_db()

# File upload configuration
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Add favicon to static folder to avoid 404 errors
if not os.path.exists('static'):
    os.makedirs('static')

# ----------------------------------------------------------------------------------------


@app.route('/test_translation')
def test_translation():
    test_text = {
        'en': 'Hello World',
        'ta': translate_text('Hello World', 'en', 'ta'),
        'hi': translate_text('Hello World', 'en', 'hi'),
        'te': translate_text('Hello World', 'en', 'te')
    }
    return jsonify(test_text)

# Make sure session['language'] is available in all templates
@app.context_processor
def inject_language():
    return {'language': session.get('language', 'en')}

# Initialize translator with multiple fallback servers
translator = GoogleTranslator(service_urls=[
    'translate.google.com',
    'translate.google.co.kr',
    'translate.google.co.in',
])

# Create a translations cache directory if it doesn't exist
os.makedirs('translations_cache', exist_ok=True)

# Dictionary to store translations in memory
translation_cache = {}

# Load existing translations from files to reduce API calls
def load_cached_translations():
    global translation_cache
    try:
        for lang in ['hi', 'ta', 'te']:
            cache_file = f'translations_cache/{lang}.json'
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    lang_cache = json.load(f)
                    translation_cache[lang] = lang_cache
                    print(f"Loaded {len(lang_cache)} cached translations for {lang}")
    except Exception as e:
        print(f"Error loading translation cache: {e}")
        translation_cache = {'hi': {}, 'ta': {}, 'te': {}}

# Save translations to file
def save_translations_to_cache():
    for lang, translations in translation_cache.items():
        try:
            with open(f'translations_cache/{lang}.json', 'w', encoding='utf-8') as f:
                json.dump(translations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving translation cache for {lang}: {e}")

# Load cached translations on startup
load_cached_translations()

@lru_cache(maxsize=100)

def translate_text(text, source_lang="en", target_lang="hi"):
    print(f"TRANSLATION REQUEST: {text} => {target_lang}")  # Debug
    if not text or not text.strip() or source_lang == target_lang:
        return text
    
    text = str(text)
    
    # Check cache first
    if target_lang in translation_cache and text in translation_cache[target_lang]:
        print(f"CACHE HIT: {translation_cache[target_lang][text]}")  # Debug
        return translation_cache[target_lang][text]
    
    try:
        # Actual translation happens here
        translated = translator.translate(text, src=source_lang, dest=target_lang).text
        print(f"TRANSLATION RESULT: {translated}")  # Debug
        
        # Update cache
        if target_lang not in translation_cache:
            translation_cache[target_lang] = {}
        translation_cache[target_lang][text] = translated
        
        return translated
    except Exception as e:
        print(f"TRANSLATION ERROR: {str(e)}")
        return text

def register_translation_handlers(app):
    """Register translation handlers with the Flask app"""
    
    @app.template_filter('translate')
    def translate_filter(text):
        current_lang = session.get('language', 'en')
        print(f"Translating '{text}' to {current_lang}")  # Debug
        if current_lang == 'en':
            return text
        return translate_text(str(text), 'en', current_lang)
    
    @app.route('/translate', methods=['POST'])
    def translate_route():
        print(f"Current session: {dict(session)}")  # Debug current session
        if 'user_id' not in session:
            return jsonify({"success": False, "error": "Not logged in"}), 401
        
        lang = request.args.get('lang', 'en')
        print(f"Setting language to: {lang}")  # Debug
        
        if lang not in ['en', 'hi', 'ta', 'te']:
            return jsonify({"success": False, "error": "Unsupported language"}), 400
        
        session['language'] = lang
        session.modified = True  # Explicitly mark session as modified
        print(f"Session after setting: {dict(session)}")  # Debug
        
        return jsonify({"success": True, "language": lang})
    
    @app.route('/test_session')
    def test_session():
        session['test'] = session.get('test', 0) + 1
        return f"Session test value: {session['test']}"
# -------------------------------------------------------------------------------------------

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Function to connect to database
def get_db_connection():
    conn = sqlite3.connect('farm_advisor.db')
    conn.row_factory = sqlite3.Row  # Return dictionary-like rows
    return conn

@app.route('/test_translator')
def test_translator():
    return test_translation_service()

# Routes
@app.route('/')
def home():
    return render_template('login.html')


# Registration route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        farmer_id = request.form.get('farmer_id', None)
        location = request.form['location']

        # Hash password for security
        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, password, email, farmer_id, location) VALUES (?, ?, ?, ?, ?)',
                         (username, hashed_password, email, farmer_id, location))
            conn.commit()
            conn.close()
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists!', 'error')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid username or password'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    username = session.get('username')  # Fetch the stored username

    if not username:
        return redirect(url_for('login'))

    return render_template('dashboard.html', username=username)


@app.route('/input_form')
def input_form():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Create a new report session
    report_id = str(uuid.uuid4())
    session['report_id'] = report_id
    
    return render_template('input_form.html')

@app.route('/process_input', methods=['POST'])
def process_input():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Get form data
        nitrogen = float(request.form['nitrogen'])
        phosphorus = float(request.form['phosphorus'])
        potassium = float(request.form['potassium'])
        ph = float(request.form['ph'])
        rainfall = float(request.form['rainfall'])
        temperature = float(request.form['temperature'])
        humidity = float(request.form['humidity'])
        location = request.form.get('location', 'Not Available')  # Get location if available

        # Store data in session
        soil_data = {
            'Location': location,
            'Nitrogen': nitrogen,
            'Phosphorus': phosphorus,
            'Potassium': potassium,
            'pH': ph,
            'Rainfall': rainfall,
            'Temperature': temperature,
            'Humidity': humidity
        }
        session['soil_data'] = soil_data

        # Get AI-based crop recommendation from Groq API
        crop_recommendation = get_groq_prediction(soil_data)

        # Store recommendation in session
        session['crop_recommendation'] = crop_recommendation
        print(crop_recommendation)

        # Parse the recommendation text into structured data
        structured_recommendation = parse_crop_recommendation(crop_recommendation)

        # Save to SQLite database
        report_id = session.get('report_id', str(uuid.uuid4()))

        conn = sqlite3.connect('farm_advisor.db')
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO reports 
        (user_id, report_id, crop_recommendation, soil_n, soil_p, soil_k, soil_ph, rainfall, temperature, humidity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            session['user_id'],
            report_id,
            crop_recommendation,
            nitrogen,
            phosphorus,
            potassium,
            ph,
            rainfall,
            temperature,
            humidity
        ))
        conn.commit()
        conn.close()

        # Pass both raw and structured data to the template
        return render_template('results_page.html', 
                              crop_recommendation=crop_recommendation,
                              structured_recommendation=structured_recommendation,
                              soil_data=soil_data)

    return redirect(url_for('input_form'))

def parse_crop_recommendation(recommendation_text):
    """
    Robust parser that handles various crop recommendation text formats and extracts
    structured data for use in templates.
    """
    # Create a structured format for the recommendations
    structured_data = {
        'introduction': '',
        'top_crops': [],
        'suitability': [],
        'care_instructions': {},
        'warnings': [],
        'conclusion': ''
    }
    
    # Split by lines and remove empty lines
    lines = [line.strip() for line in recommendation_text.split('\n') if line.strip()]
    
    # Process introduction (everything before "Top 3 Recommended Crops:")
    intro_lines = []
    i = 0
    
    # Look for the Top 3 Crops header
    while i < len(lines) and "*Top 3 Recommended Crops:*" not in lines[i]:
        intro_lines.append(lines[i])
        i += 1
    
    structured_data['introduction'] = ' '.join(intro_lines)
    
    # Process Top Recommended Crops section
    if i < len(lines) and "*Top 3 Recommended Crops:*" in lines[i]:
        i += 1  # Skip the section header
        
        # Process each numbered crop
        while i < len(lines) and lines[i].strip().startswith(('1.', '2.', '3.')):
            line = lines[i].strip()
            
            # Handle crop entries with or without descriptions
            if '**' in line:
                parts = line.split('**')
                number = parts[0].split('.')[0].strip()
                name = parts[1].strip()
                description = parts[2].strip() if len(parts) > 2 else ""
                
                # Clean up description (remove parentheses if they're part of the name)
                if description.startswith('(') and ')' in description:
                    description = description.split(')', 1)[1].strip()
                
                structured_data['top_crops'].append({
                    'number': number,
                    'name': name,
                    'description': description
                })
            i += 1
    
    # Process "Why these crops are suitable" section
    suitability_header_variations = ["*Why these crops are suitable:*", "Why these crops are suitable:"]
    
    found_suitability = False
    for header in suitability_header_variations:
        i_temp = i
        while i_temp < len(lines) and header not in lines[i_temp]:
            i_temp += 1
        
        if i_temp < len(lines) and header in lines[i_temp]:
            i = i_temp
            found_suitability = True
            break
    
    if found_suitability:
        i += 1  # Skip the section header
        
        # Collect bullet points
        while i < len(lines) and lines[i].startswith('*'):
            suitability_item = lines[i][1:].strip()
            structured_data['suitability'].append(suitability_item)
            i += 1
    
    # Process Basic Care Instructions section
    care_header_variations = [
        "*Basic Care Instructions for Recommended Crops:*", 
        "*Basic Care Instructions:*", 
        "Basic Care Instructions:"
    ]
    
    found_care = False
    for header in care_header_variations:
        i_temp = i
        while i_temp < len(lines) and header not in lines[i_temp]:
            i_temp += 1
        
        if i_temp < len(lines) and header in lines[i_temp]:
            i = i_temp
            found_care = True
            break
    
    if found_care:
        i += 1  # Skip the section header
        
        # Handle "For all three crops:" format
        if i < len(lines) and "For all" in lines[i]:
            crop_group = "General Care"
            structured_data['care_instructions'][crop_group] = []
            i += 1
            
            # Collect bullet points for general care
            while i < len(lines) and lines[i].strip().startswith('*'):
                instruction = lines[i].strip()[1:].strip()
                structured_data['care_instructions'][crop_group].append(instruction)
                i += 1
        
        # Process care instructions with numbered crops
        current_crop = None
        
        # Check if there's a Crop-Specific Care section
        crop_specific_variations = ["*Crop-Specific Care:*", "Crop-Specific Care:"]
        found_specific = False
        
        for header in crop_specific_variations:
            i_temp = i
            while i_temp < len(lines) and header not in lines[i_temp]:
                i_temp += 1
            
            if i_temp < len(lines) and header in lines[i_temp]:
                i = i_temp + 1  # Skip the section header
                found_specific = True
                break
        
        if found_specific:
            # Process crop-specific bullet points
            while i < len(lines) and (not lines[i].startswith("*") or "*Crop-Specific" in lines[i]):
                line = lines[i].strip()
                
                if line.startswith('*'):
                    # Handle format: "* Crop: instruction"
                    parts = line[1:].strip().split(':', 1)
                    if len(parts) > 1:
                        crop_name = parts[0].strip()
                        instruction = parts[1].strip()
                        
                        if crop_name not in structured_data['care_instructions']:
                            structured_data['care_instructions'][crop_name] = []
                        
                        structured_data['care_instructions'][crop_name].append(instruction)
                
                i += 1
        else:
            # Try to process numbered crop instructions format
            while i < len(lines) and (not lines[i].startswith("**") or "Care" in lines[i]):
                line = lines[i].strip()
                
                # Identify crop headers (numbered entries)
                if line.startswith(('1.', '2.', '3.')):
                    if '**' in line:
                        # Format: "1. *Crop Name:*"
                        parts = line.split('**')
                        if len(parts) > 1:
                            current_crop = parts[1].strip().rstrip(':')
                            structured_data['care_instructions'][current_crop] = []
                    else:
                        # Format: "1. Crop Name:"
                        parts = line.split(':', 1)
                        if len(parts) > 0:
                            crop_part = parts[0].split('.', 1)
                            if len(crop_part) > 1:
                                current_crop = crop_part[1].strip()
                                structured_data['care_instructions'][current_crop] = []
                # Add instructions for the current crop
                elif line.startswith('*') and current_crop:
                    instruction = line[1:].strip()
                    structured_data['care_instructions'][current_crop].append(instruction)
                
                i += 1
    
    # Process Warnings section
    warning_header_variations = [
        "*Warnings or Special Considerations:*", 
        "*Warnings and Special Considerations:*",
        "Warnings and Special Considerations:",
        "*Warnings:*"
    ]
    
    found_warnings = False
    for header in warning_header_variations:
        i_temp = i
        while i_temp < len(lines) and header not in lines[i_temp]:
            i_temp += 1
        
        if i_temp < len(lines) and header in lines[i_temp]:
            i = i_temp
            found_warnings = True
            break
    
    if found_warnings:
        i += 1  # Skip the section header
        
        # Collect warnings until the end or until we hit a conclusion section
        while i < len(lines) and "Overall" not in lines[i]:
            line = lines[i].strip()
            
            if line.startswith('*'):
                warning = line[1:].strip()
                structured_data['warnings'].append(warning)
            
            i += 1
    
    # Process conclusion (if any)
    if i < len(lines):
        conclusion_lines = []
        while i < len(lines):
            conclusion_lines.append(lines[i].strip())
            i += 1
        
        if conclusion_lines:
            structured_data['conclusion'] = ' '.join(conclusion_lines)
    print(structured_data)

    return structured_data

@app.route('/process_location', methods=['POST'])
def process_location():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        location = request.form['location']
        
        # Get weather data
        weather_data = get_weather(location)
        if not weather_data:
            return render_template('error.html', message="Unable to fetch weather data. Please check the location.")
        
        # Get soil data
        soil_data = get_soil_data(weather_data["Latitude"], weather_data["Longitude"])
        if not soil_data:
            return render_template('error.html', message="Unable to fetch soil data. Please try again later.")
        
        # Combine data
        combined_data = {
            'Nitrogen': soil_data["Nitrogen"],
            'Phosphorus': soil_data["Phosphorus"],
            'Potassium': soil_data["Potassium"],
            'pH': soil_data["pH"],
            'Rainfall': weather_data["Rainfall"],
            'Temperature': weather_data["Temperature"],
            'Humidity': weather_data["Humidity"],
            'Location': weather_data["Location"]
        }
        
        # Store in session
        session['soil_data'] = combined_data
        
        # Get AI recommendation
        raw_crop_recommendation = get_groq_prediction(combined_data)
        
        # Parse the recommendation
        parsed_recommendation = parse_crop_recommendation_location(raw_crop_recommendation)
        
        # No longer need to format the recommendation here as it's done in the template
        
        # Store recommendations in session
        session['raw_crop_recommendation'] = raw_crop_recommendation
        session['parsed_recommendation'] = parsed_recommendation
        
        # Save to database
        report_id = str(uuid.uuid4())
        session['report_id'] = report_id
        
        try:
            conn = sqlite3.connect('farm_advisor.db')
            cursor = conn.cursor()
            
            # Try to insert with location column
            try:
                cursor.execute('''
                INSERT INTO reports 
                (user_id, report_id, crop_recommendation, soil_n, soil_p, soil_k, soil_ph, rainfall, temperature, humidity, location)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session['user_id'],
                    report_id,
                    raw_crop_recommendation,
                    combined_data['Nitrogen'],
                    combined_data['Phosphorus'],
                    combined_data['Potassium'],
                    combined_data['pH'],
                    combined_data['Rainfall'],
                    combined_data['Temperature'],
                    combined_data['Humidity'],
                    combined_data['Location']
                ))
            except sqlite3.OperationalError:
                # If location column doesn't exist, insert without it
                cursor.execute('''
                INSERT INTO reports 
                (user_id, report_id, crop_recommendation, soil_n, soil_p, soil_k, soil_ph, rainfall, temperature, humidity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session['user_id'],
                    report_id,
                    raw_crop_recommendation,
                    combined_data['Nitrogen'],
                    combined_data['Phosphorus'],
                    combined_data['Potassium'],
                    combined_data['pH'],
                    combined_data['Rainfall'],
                    combined_data['Temperature'],
                    combined_data['Humidity']
                ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Database error: {str(e)}")
            # Continue even if database insert fails
        
        # Add checking for potential parsing issues
        if not parsed_recommendation or not all(key in parsed_recommendation for key in ['top_recommendations', 'suitability_reasons', 'care_instructions', 'warnings']):
            # If the parsing failed or data is incomplete, prepare basic fallback data
            print("Warning: Parsed recommendation data is incomplete or invalid")
            
            # We'll still use the template's fallback content in this case
            
        # Show results with fetched data - now passing the parsed_recommendation directly
        return render_template('location_results.html', 
                            parsed_recommendation=parsed_recommendation,
                            soil_data=combined_data)

def parse_crop_recommendation_location(recommendation_text):
    """
    Parse the crop recommendation text into a structured format with enhanced error handling
    
    Args:
        recommendation_text (str): The raw text from the AI recommendation
        
    Returns:
        dict: A structured dictionary with parsed recommendation data
    """
    # Initialize the structure for parsed recommendation
    result = {
        'top_recommendations': [],
        'suitability_reasons': [],
        'care_instructions': [],
        'warnings': []
    }
    
    # Safety check - if input is empty or not a string
    if not recommendation_text or not isinstance(recommendation_text, str):
        print("Warning: Invalid recommendation text input")
        return result
    
    # Extract sections using the headings as delimiters
    sections = {}
    current_section = None
    section_content = []
    
    # Check if text is in the new format or old format
    is_new_format = '*Crop Recommendations*' in recommendation_text
    
    try:
        lines = recommendation_text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
                
            # Check for main section headers in different formats
            if '*Top 3 Recommendations:' in line or ('Top Recommendations:*' in line):
                if current_section and section_content:
                    sections[current_section] = section_content
                current_section = 'recommendations'
                section_content = []
            elif '*Why these crops are suitable:*' in line:
                if current_section and section_content:
                    sections[current_section] = section_content
                current_section = 'suitability'
                section_content = []
            elif '*Basic Care Instructions:' in line or ('*Basic care instructions for the recommended crops:*' in line):
                if current_section and section_content:
                    sections[current_section] = section_content
                current_section = 'care_instructions'
                section_content = []
            elif '*Warnings and Special Considerations:' in line or ('*Warnings or special considerations:*' in line):
                if current_section and section_content:
                    sections[current_section] = section_content
                current_section = 'warnings'
                section_content = []
            elif current_section:
                # For lines that are part of a section
                section_content.append(line)
            elif '*Crop Recommendations*' in line:
                # Skip header line in new format
                pass
            i += 1
        
        # Add the last section
        if current_section and section_content:
            sections[current_section] = section_content
        
        # Process recommendations section
        if 'recommendations' in sections:
            for line in sections['recommendations']:
                if line.strip() == '*':
                    # Skip empty bullet points
                    continue
                    
                if '**' in line and ')' in line:
                    # Old format: "1. *Sorghum* (Sorghum bicolor)"
                    parts = line.split('**')
                    if len(parts) >= 2:
                        crop_name = parts[1].strip()
                        scientific_name = None
                        
                        # Try to extract scientific name
                        if '(' in line and ')' in line:
                            sci_part = line.split('(')[1]
                            if ')' in sci_part:
                                scientific_name = sci_part.split(')')[0].strip()
                        
                        result['top_recommendations'].append({
                            'name': crop_name,
                            'scientific_name': scientific_name
                        })
                elif line.startswith('') and not line.strip() == '':
                    # Extract crop names from bullet points if not empty bullet
                    crop_line = line.replace('*', '', 1).strip()
                    if crop_line and crop_line not in ['', ' ']:
                        result['top_recommendations'].append({
                            'name': crop_line,
                            'scientific_name': None
                        })
                # Additional format checking: capture numbered items without **
                elif re.match(r'^\d+\.\s+\w+', line):
                    # Format: "1. Crop name"
                    crop_name = re.sub(r'^\d+\.\s+', '', line).strip()
                    result['top_recommendations'].append({
                        'name': crop_name,
                        'scientific_name': None
                    })
        
        # Process suitability reasons
        if 'suitability' in sections:
            for line in sections['suitability']:
                if line.startswith('*'):
                    if '**' in line:
                        # New format with bolded category: "* *Soil pH*: All three crops..."
                        parts = line.split('**')
                        if len(parts) >= 3:
                            category = parts[1].strip()
                            text = parts[2].strip()
                            if text.startswith(':'):
                                text = text[1:].strip()
                            reason = f"{category}: {text}"
                            result['suitability_reasons'].append(reason)
                    else:
                        # Old format: "* The soil has a balanced..."
                        reason = line.replace('*', '', 1).strip()
                        result['suitability_reasons'].append(reason)
                # Also catch non-bulleted lines if they look like suitability reasons
                elif line and not line.startswith('#') and not line.startswith('**'):
                    result['suitability_reasons'].append(line)
        
        # Process care instructions - handle both formats
        if 'care_instructions' in sections:
            current_crop = None
            crop_instructions = []
            general_instructions = []
            
            for line in sections['care_instructions']:
                if line.startswith('*'):
                    # New format - just bullet points
                    instruction = line.replace('*', '', 1).strip()
                    general_instructions.append(instruction)
                elif '**' in line and ':' in line:
                    # Old format with crop names
                    if current_crop and crop_instructions:
                        result['care_instructions'].append({
                            'crop': current_crop,
                            'instructions': crop_instructions
                        })
                    
                    current_crop = line.split('**')[1].split(':')[0].strip()
                    crop_instructions = []
                elif line.startswith('-') and current_crop:
                    # Handle dash bullet points
                    instruction = line.replace('-', '', 1).strip()
                    crop_instructions.append(instruction)
                elif line.startswith('*') and current_crop:
                    instruction = line.replace('*', '', 1).strip()
                    crop_instructions.append(instruction)
                # Check for headers that might indicate crop names
                elif re.match(r'^[A-Z][a-z]+:$', line) or line.endswith(':'):
                    if current_crop and crop_instructions:
                        result['care_instructions'].append({
                            'crop': current_crop,
                            'instructions': crop_instructions
                        })
                    current_crop = line.rstrip(':').strip()
                    crop_instructions = []
            
            # Add the last crop instructions
            if current_crop and crop_instructions:
                result['care_instructions'].append({
                    'crop': current_crop,
                    'instructions': crop_instructions
                })
            
            # If we only have general instructions (new format), group them by crops
            if general_instructions and not result['care_instructions']:
                # First, check for any crop names in the general instructions
                crop_instructions_map = {}
                current_crop = "General"
                
                for instruction in general_instructions:
                    # Check if this line might be a crop name (short and ends with colon)
                    if ':' in instruction and len(instruction.split(':')[0]) < 20:
                        current_crop = instruction.split(':')[0].strip()
                        instruction_content = instruction.split(':', 1)[1].strip()
                        if current_crop not in crop_instructions_map:
                            crop_instructions_map[current_crop] = []
                        if instruction_content:
                            crop_instructions_map[current_crop].append(instruction_content)
                    else:
                        if current_crop not in crop_instructions_map:
                            crop_instructions_map[current_crop] = []
                        crop_instructions_map[current_crop].append(instruction)
                
                # Convert the map to the expected format
                for crop, instructions in crop_instructions_map.items():
                    result['care_instructions'].append({
                        'crop': crop,
                        'instructions': instructions
                    })
                
                # If still no structured instructions, try to group them by sets of 3
                if not result['care_instructions']:
                    # Try to group instructions by sets of 3 (assuming 3 crops with 3 instructions each)
                    if len(general_instructions) >= 9 and len(result['top_recommendations']) == 3:
                        for i in range(3):
                            if i * 3 < len(general_instructions):
                                crop_name = result['top_recommendations'][i]['name'] if i < len(result['top_recommendations']) else f"Crop {i+1}"
                                result['care_instructions'].append({
                                    'crop': crop_name,
                                    'instructions': general_instructions[i*3:i*3+3]
                                })
                    else:
                        # If we can't group them, just add them as general instructions
                        result['care_instructions'].append({
                            'crop': "General",
                            'instructions': general_instructions
                        })
        
        # Process warnings
        if 'warnings' in sections:
            current_warning = None
            warning_text = ''
            
            for line in sections['warnings']:
                if line.startswith('') and '*' in line:
                    # New format: "* *Irrigation*: While the crops..."
                    # If we have a previous warning, save it
                    if current_warning and warning_text:
                        result['warnings'].append({
                            'type': current_warning,
                            'text': warning_text.strip()
                        })
                    
                    # Parse the new warning
                    parts = line.replace('', '', 1).strip().split('*')
                    if len(parts) >= 3:
                        current_warning = parts[1].strip()
                        warning_text = parts[2].strip()
                        if warning_text.startswith(':'):
                            warning_text = warning_text[1:].strip()
                elif line.startswith('*') and ':' in line:
                    # Old format: "* Irrigation: Although these crops..."
                    # If we have a previous warning, save it
                    if current_warning and warning_text:
                        result['warnings'].append({
                            'type': current_warning,
                            'text': warning_text.strip()
                        })
                    
                    # Start a new warning
                    parts = line.split(':', 1)
                    current_warning = parts[0].replace('*', '', 1).strip()
                    warning_text = parts[1].strip() if len(parts) > 1 else ''
                elif current_warning and line:
                    warning_text += ' ' + line
                # Also catch lines that look like warnings with colons
                elif ':' in line and not line.startswith('#') and not line.startswith('**'):
                    parts = line.split(':', 1)
                    warning_type = parts[0].strip()
                    warning_text = parts[1].strip() if len(parts) > 1 else ''
                    if warning_type and warning_text and len(warning_type) < 25:  # Reasonable length for a warning type
                        result['warnings'].append({
                            'type': warning_type,
                            'text': warning_text
                        })
            
            # Add the last warning
            if current_warning and warning_text:
                result['warnings'].append({
                    'type': current_warning,
                    'text': warning_text.strip()
                })
        
        # Add the conclusion paragraph if it exists
        if 'warnings' in sections and sections['warnings']:
            conclusion = sections['warnings'][-1]
            if conclusion.startswith('By following'):
                result['conclusion'] = conclusion
    
    except Exception as e:
        print(f"Error parsing crop recommendation: {str(e)}")
        # Continue with what we have so far
    
    # If we don't have any recommendations, add default ones
    if not result['top_recommendations']:
        # Add some fallback recommendations
        result['top_recommendations'] = [
            {'name': 'Sesame', 'scientific_name': None},
            {'name': 'Peanut', 'scientific_name': None},
            {'name': 'Okra', 'scientific_name': None}
        ]
    
    # Make sure each section has at least some content
    if not result['suitability_reasons']:
        result['suitability_reasons'] = [
            "Suitable for the provided soil and climate conditions."
        ]
    
    if not result['care_instructions']:
        result['care_instructions'] = [
            {
                'crop': "General",
                'instructions': [
                    "Prepare soil properly before planting.",
                    "Ensure adequate water supply based on crop requirements.",
                    "Monitor regularly for pests and diseases."
                ]
            }
        ]
    
    if not result['warnings']:
        result['warnings'] = [
            {
                'type': 'General',
                'text': "Monitor local weather conditions and adjust care practices accordingly."
            }
        ]
    
    return result

def format_recommendation_for_display(parsed_recommendation):
    """
    Format the parsed recommendation data into HTML-friendly format
    
    Args:
        parsed_recommendation (dict): The parsed recommendation data
        
    Returns:
        str: HTML-formatted recommendation content
    """
    html_content = []
    
    # Add top recommendations
    html_content.append("<h4>Top Recommendations:</h4>")
    html_content.append("<ul class='list-group mb-4'>")
    for i, crop in enumerate(parsed_recommendation['top_recommendations']):
        if crop['scientific_name']:
            html_content.append(f"<li class='list-group-item'><strong>{i+1}. {crop['name']}</strong> ({crop['scientific_name']})</li>")
        else:
            html_content.append(f"<li class='list-group-item'><strong>{i+1}. {crop['name']}</strong></li>")
    html_content.append("</ul>")
    
    # Add suitability reasons
    html_content.append("<h4>Why these crops are suitable:</h4>")
    html_content.append("<ul class='list-group mb-4'>")
    for reason in parsed_recommendation['suitability_reasons']:
        html_content.append(f"<li class='list-group-item'>{reason}</li>")
    html_content.append("</ul>")
    
    # Add care instructions
    html_content.append("<h4>Basic Care Instructions:</h4>")
    html_content.append("<div class='care-instructions mb-4'>")
    
    # Handle both new and old format of care instructions
    if isinstance(parsed_recommendation['care_instructions'], list):
        # New format - list of dicts with crop and instructions
        for care_item in parsed_recommendation['care_instructions']:
            html_content.append(f"<h5>{care_item['crop']}:</h5>")
            html_content.append("<ul class='list-group mb-3'>")
            for instruction in care_item['instructions']:
                html_content.append(f"<li class='list-group-item'>{instruction}</li>")
            html_content.append("</ul>")
    else:
        # Old format - dict with crop keys and instruction list values
        for crop, instructions in parsed_recommendation['care_instructions'].items():
            html_content.append(f"<h5>{crop}:</h5>")
            html_content.append("<ul class='list-group mb-3'>")
            for instruction in instructions:
                html_content.append(f"<li class='list-group-item'>{instruction}</li>")
            html_content.append("</ul>")
    
    html_content.append("</div>")
    
    # Add warnings
    html_content.append("<h4>Warnings and Special Considerations:</h4>")
    html_content.append("<ul class='list-group mb-4'>")
    for warning in parsed_recommendation['warnings']:
        html_content.append(f"<li class='list-group-item warning-item'><strong>{warning['type']}:</strong> {warning['text']}</li>")
    html_content.append("</ul>")
    
    # Add conclusion if it exists
    if 'conclusion' in parsed_recommendation:
        html_content.append(f"<p class='mt-4'>{parsed_recommendation['conclusion']}</p>")
    
    return "\n".join(html_content)

@app.route('/manual_soil')
def manual_soil():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Create a new report session
    report_id = str(uuid.uuid4())
    session['report_id'] = report_id
    
    return render_template('manual_soil.html')

@app.route('/location-form')
def location_form():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Create a new report session
    report_id = str(uuid.uuid4())
    session['report_id'] = report_id
    
    return render_template('location-form.html')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/leaf_analysis')
def leaf_analysis():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('leaf_analysis.html')

@app.route('/process_leaf', methods=['POST'])
def process_leaf():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'leaf_image' not in request.files:
            flash('No file selected', 'danger')
            return redirect(url_for('leaf_analysis'))
        
        file = request.files['leaf_image']
        
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(url_for('leaf_analysis'))
        
        if file and allowed_file(file.filename):
            try:
                # Secure filename and save
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                # First validate it's actually a leaf image
                if not is_leaf_image(file_path):
                    os.remove(file_path)  # Delete non-leaf image
                    flash('The uploaded image does not appear to be a plant leaf', 'danger')
                    return redirect(url_for('leaf_analysis'))
                
                # Process with Groq API
                analysis_result = analyze_leaf_with_groq(file_path)
                
                # Validate API response
                if analysis_result['health_status'] == 'Analysis Failed':
                    flash('Leaf analysis failed. Please try again with a clearer image.', 'warning')
                    return redirect(url_for('leaf_analysis'))
                
                # Store results
                session['leaf_analysis'] = {
                    'leaf_color': analysis_result['leaf_color'],
                    'leaf_color_name': analysis_result['leaf_color_name'],
                    'health_status': analysis_result['health_status'],
                    'deficiencies': analysis_result['deficiencies']
                }
                
                # Get recommendations
                fertilizer_recommendation = get_fertilizer_recommendation(
                    analysis_result['health_status'])
                
                # Update database
                conn = sqlite3.connect('farm_advisor.db')
                cursor = conn.cursor()
                cursor.execute('''
                UPDATE reports 
                SET leaf_analysis = ?, fertilizer_recommendation = ?
                WHERE report_id = ?
                ''', (
                    f"{analysis_result['leaf_color_name']}: {analysis_result['health_status']}",
                    fertilizer_recommendation['primary_fertilizer_name'],
                    session.get('report_id', 0)
                ))
                conn.commit()
                conn.close()
                
                return render_template('fertilizer_recommendation.html',
                                    leaf_color=analysis_result['leaf_color'],
                                    leaf_color_name=analysis_result['leaf_color_name'],
                                    health_status=analysis_result['health_status'],
                                    deficiencies=analysis_result['deficiencies'],
                                    **fertilizer_recommendation)
                
            except Exception as e:
                print(f"Error processing leaf: {str(e)}")
                flash('An error occurred during analysis. Please try again.', 'danger')
                return redirect(url_for('leaf_analysis'))
    
    return redirect(url_for('leaf_analysis'))

def is_leaf_image(image_path):
    """Validate if the uploaded image is actually a leaf"""
    try:
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            return False
            
        # Convert to HSV color space
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Define green color range (typical for leaves)
        lower_green = np.array([35, 50, 50])
        upper_green = np.array([85, 255, 255])
        
        # Threshold the HSV image
        mask = cv2.inRange(hsv, lower_green, upper_green)
        
        # Calculate percentage of green pixels
        green_pixels = cv2.countNonZero(mask)
        total_pixels = img.shape[0] * img.shape[1]
        green_percent = (green_pixels / total_pixels) * 100
        
        # Consider it a leaf if at least 15% green (adjust threshold as needed)
        return green_percent > 15
        
    except Exception as e:
        print(f"Error validating leaf image: {str(e)}")
        return False

def analyze_leaf_with_groq(image_path):
    """Analyze leaf image using Groq API with enhanced validation"""
    try:
        # Validate image first
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError("Invalid image file")
            
        # Get dominant color
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        resized_img = cv2.resize(img, (100, 100))
        pixels = resized_img.reshape(-1, 3)
        avg_color = np.mean(pixels, axis=0)
        hex_color = '#{:02x}{:02x}{:02x}'.format(*avg_color.astype(int))
        
        # Enhanced prompt with strict instructions
        prompt = f"""
        You are an agricultural expert analyzing plant leaf images. 
        The uploaded image has a dominant color of {hex_color}.
        
        IMPORTANT INSTRUCTIONS:
        1. If this doesn't appear to be a plant leaf, respond with health_status "Not a leaf"
        2. For actual leaves, provide:
           - leaf_color: The hex color code
           - leaf_color_name: Descriptive name (e.g., "Yellowing", "Healthy Green")
           - health_status: Diagnosis ("Healthy", "Nitrogen Deficiency", etc.)
           - deficiencies: Detailed explanation
        
        Response MUST be valid JSON with exactly these keys.
        """
        
        # Call Groq API with timeout
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise agricultural analysis assistant."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            timeout=30  # 30 second timeout
        )
        
        # Parse and validate response
        result = json.loads(response.choices[0].message.content)
        
        if not all(key in result for key in ['leaf_color', 'leaf_color_name', 'health_status', 'deficiencies']):
            raise ValueError("Invalid API response format")
            
        if result['health_status'].lower() == "not a leaf":
            return {
                'leaf_color': hex_color,
                'leaf_color_name': 'Invalid',
                'health_status': 'Not a leaf',
                'deficiencies': 'The uploaded image does not appear to be a plant leaf'
            }
            
        return result
        
    except Exception as e:
        print(f"Error in leaf analysis: {str(e)}")
        return {
            'leaf_color': '#000000',
            'leaf_color_name': 'Analysis Error',
            'health_status': 'Analysis Failed',
            'deficiencies': f'Unable to analyze image: {str(e)}'
        }
    
# def analyze_leaf_with_groq(image_path):
#     # First try specialized plant API
#     try:
#         plant_api_result = call_plant_disease_api(image_path)
#         if plant_api_result['is_leaf']:
#             return format_plant_api_result(plant_api_result)
#     except Exception as e:
#         print(f"Plant API error: {str(e)}")
    
#     # Fallback to Groq analysis
#     return analyze_with_groq_fallback(image_path)

def get_fertilizer_recommendation(health_status):
    """
    Get fertilizer recommendations based on leaf health status
    """
    if health_status == "Healthy":
        return {
            'primary_fertilizer_name': "Balanced NPK Fertilizer",
            'primary_fertilizer_npk': "20-20-20",
            'primary_fertilizer_rate': "5 kg per acre",
            'primary_fertilizer_description': "A balanced fertilizer to maintain overall plant health and growth.",
            'alt_fertilizer_name': "Slow-Release Fertilizer",
            'alt_fertilizer_npk': "15-15-15",
            'alt_fertilizer_description': "Provides nutrients over a longer period with less frequent application.",
            'organic_fertilizer_name': "Compost",
            'organic_fertilizer_description': "Rich in organic matter to improve soil structure and fertility."
        }
    elif health_status == "Nitrogen Deficiency":
        return {
            'primary_fertilizer_name': "High Nitrogen Fertilizer",
            'primary_fertilizer_npk': "46-0-0",
            'primary_fertilizer_rate': "7 kg per acre",
            'primary_fertilizer_description': "Urea fertilizer to quickly address nitrogen deficiency.",
            'alt_fertilizer_name': "Ammonium Sulfate",
            'alt_fertilizer_npk': "21-0-0",
            'alt_fertilizer_description': "Provides nitrogen and sulfur, good for acidic soils.",
            'organic_fertilizer_name': "Blood Meal",
            'organic_fertilizer_description': "Organic nitrogen source that releases slowly into the soil."
        }
    elif health_status == "Potassium Deficiency":
        return {
            'primary_fertilizer_name': "Potash Fertilizer",
            'primary_fertilizer_npk': "0-0-60",
            'primary_fertilizer_rate': "6 kg per acre",
            'primary_fertilizer_description': "High potassium fertilizer to address deficiency and improve crop quality.",
            'alt_fertilizer_name': "NPK with high K",
            'alt_fertilizer_npk': "10-10-40",
            'alt_fertilizer_description': "Balanced fertilizer with emphasis on potassium.",
            'organic_fertilizer_name': "Wood Ash",
            'organic_fertilizer_description': "Natural source of potassium and other micronutrients."
        }
    elif "Disease" in health_status:
        return {
            'primary_fertilizer_name': "Fungicide + Fertilizer Mix",
            'primary_fertilizer_npk': "10-10-10 + Copper",
            'primary_fertilizer_rate': "4 kg per acre",
            'primary_fertilizer_description': "Combined treatment for disease control and plant nutrition.",
            'alt_fertilizer_name': "Fungicide Spray",
            'alt_fertilizer_npk': "N/A",
            'alt_fertilizer_description': "Targeted treatment for fungal diseases.",
            'organic_fertilizer_name': "Neem Cake",
            'organic_fertilizer_description': "Natural fungicide with mild fertilizer properties."
        }
    else:
        # Default or unknown condition
        return {
            'primary_fertilizer_name': "Balanced NPK Fertilizer",
            'primary_fertilizer_npk': "10-10-10",
            'primary_fertilizer_rate': "5 kg per acre",
            'primary_fertilizer_description': "General purpose fertilizer suitable for most crops.",
            'alt_fertilizer_name': "Soil Test Recommended",
            'alt_fertilizer_npk': "Varies",
            'alt_fertilizer_description': "Consider a soil test for more accurate recommendations.",
            'organic_fertilizer_name': "Compost",
            'organic_fertilizer_description': "Improves soil health and provides balanced nutrition."
        }
    
@app.route('/reports')
def reports():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('farm_advisor.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
    SELECT report_id, crop_recommendation, created_at 
    FROM reports 
    WHERE user_id = ? 
    ORDER BY created_at DESC
    """, (session['user_id'],))
    
    reports = cursor.fetchall()
    conn.close()
    
    return render_template('reports.html', reports=reports)

@app.route('/view_report/<report_id>')
def view_report(report_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('farm_advisor.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM reports 
    WHERE user_id = ? AND report_id = ?
    """, (session['user_id'], report_id))
    
    report = cursor.fetchone()
    conn.close()
    
    if not report:
        flash('Report not found!', 'danger')
        return redirect(url_for('reports'))
    
    return render_template('view_report.html', report=report)

@app.route('/download_report/<report_id>')
def download_report(report_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('farm_advisor.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM reports 
    WHERE user_id = ? AND report_id = ?
    """, (session['user_id'], report_id))
    
    report = cursor.fetchone()
    conn.close()
    
    if not report:
        flash('Report not found!', 'danger')
        return redirect(url_for('reports'))
    
    # Generate PDF or other format here
    # For simplicity, we'll just render a printable page
    return render_template('printable_report.html', report=report)

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('farm_advisor.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],))
    
    user = cursor.fetchone()
    conn.close()
    
    return render_template('profile.html', user=user)

@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Updated to use correct field names from your form
        username = request.form.get('username')
        email = request.form.get('email')
        location = request.form.get('location', 'Unknown')

        if not username or not email:
            flash('Username and Email cannot be empty!', 'warning')
            return redirect(url_for('profile'))

        conn = sqlite3.connect('farm_advisor.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET username = ?, email = ?, location = ? WHERE id = ?", 
                      (username, email, location, session['user_id']))
        conn.commit()
        conn.close()
        
        session['username'] = username
        flash('Profile updated successfully!', 'success')
    
    return redirect(url_for('profile'))


  
# This would be in your app.py file
@app.route('/weather_data')
def weather_data():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # We'll pass the current date/time to the template
    # The actual weather data will be fetched via JavaScript
    return render_template('weather.html', now=datetime.now)

@app.route('/api/weather')
@cache.cached(timeout=15*60)  # Cache for 15 minutes
def get_weather_data():
    try:
        # Get coordinates from the request with better defaults
        lat = request.args.get('lat', default=40.7128, type=float)  # Default to New York
        lon = request.args.get('lon', default=-74.0060, type=float)
        
        # Verify API key is properly set
        api_key = os.environ.get('OPENWEATHERMAP_API_KEY')
        if not api_key:
            app.logger.error("OpenWeatherMap API key not configured")
            return jsonify({'error': 'Weather service is currently unavailable'}), 500
        
        # Get current weather
        current_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
        current_response = requests.get(current_url)
        
        if current_response.status_code != 200:
            app.logger.error(f"Current weather API error: {current_response.status_code} - {current_response.text}")
            return jsonify({'error': 'Weather service is currently unavailable'}), 500
            
        current_data = current_response.json()
        
        # Process the current weather data with better defaults
        current_weather = {
            'location_name': current_data.get('name', 'Unknown Location'),
            'temperature': round(current_data.get('main', {}).get('temp', 20)),
            'feels_like': round(current_data.get('main', {}).get('feels_like', 20)),
            'humidity': current_data.get('main', {}).get('humidity', 50),
            'condition': current_data.get('weather', [{}])[0].get('main', 'Clear'),
            'description': current_data.get('weather', [{}])[0].get('description', 'clear sky'),
            'icon': current_data.get('weather', [{}])[0].get('icon', '01d'),
            'wind_speed': round(current_data.get('wind', {}).get('speed', 2), 1),
            'precipitation': current_data.get('rain', {}).get('1h', 0) if 'rain' in current_data else 0
        }

        # Try to get forecast using 5-day forecast endpoint first (more widely available)
        forecast = []
        try:
            forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            forecast_response = requests.get(forecast_url)
            
            if forecast_response.status_code == 200:
                forecast_data = forecast_response.json()
                
                # Process 5-day/3-hour forecast into daily format
                # Group by day and calculate daily averages
                daily_forecasts = {}
                
                for item in forecast_data.get('list', []):
                    dt = datetime.fromtimestamp(item.get('dt', 0))
                    day = dt.strftime('%Y-%m-%d')
                    
                    if day not in daily_forecasts:
                        daily_forecasts[day] = {
                            'temps': [],
                            'conditions': [],
                            'icons': [],
                            'precipitation': 0,
                            'humidity': []
                        }
                    
                    daily_forecasts[day]['temps'].append(item.get('main', {}).get('temp', 20))
                    daily_forecasts[day]['conditions'].append(item.get('weather', [{}])[0].get('main', 'Clear'))
                    daily_forecasts[day]['icons'].append(item.get('weather', [{}])[0].get('icon', '01d'))
                    daily_forecasts[day]['precipitation'] += item.get('rain', {}).get('3h', 0) if 'rain' in item else 0
                    daily_forecasts[day]['humidity'].append(item.get('main', {}).get('humidity', 50))
                
                # Convert to the format expected by the frontend
                for day, data in daily_forecasts.items():
                    # Get most common condition and icon
                    conditions = data['conditions']
                    most_common_condition = max(set(conditions), key=conditions.count)
                    
                    icons = data['icons']
                    # Filter day icons only for consistency
                    day_icons = [icon for icon in icons if 'd' in icon]
                    most_common_icon = max(set(day_icons if day_icons else icons), key=icons.count)
                    
                    # Calculate average temperature
                    avg_temp = sum(data['temps']) / len(data['temps']) if data['temps'] else 20
                    
                    dt = datetime.strptime(day, '%Y-%m-%d')
                    day_name = dt.strftime('%a')
                    
                    forecast.append({
                        'day': day_name,
                        'temperature': round(avg_temp),
                        'min_temp': round(min(data['temps']) if data['temps'] else 15),
                        'max_temp': round(max(data['temps']) if data['temps'] else 25),
                        'condition': most_common_condition,
                        'description': most_common_condition.lower(),
                        'icon': most_common_icon,
                        'precipitation': round(data['precipitation'], 1),
                        'humidity': round(sum(data['humidity']) / len(data['humidity']) if data['humidity'] else 50)
                    })
            
        except Exception as forecast_error:
            app.logger.error(f"Error processing forecast: {str(forecast_error)}")
            # Continue with empty forecast rather than failing
            forecast = []
        
        # Generate farm advisories
        advisories = generate_farm_advisories(current_weather, forecast)
        
        # Prepare response
        response = {
            'current': current_weather,
            'forecast': forecast[:7],  # Limit to 7 days
            'advisories': advisories,
            'status': 'success'
        }
        
        return jsonify(response)
        
    except Exception as e:
        app.logger.error(f"Weather API error: {str(e)}")
        return jsonify({
            'error': 'Weather service is currently unavailable. Please try again later.',
            'status': 'error'
        }), 500
    
@app.route('/api/geocode')
def geocode_location():
    try:
        # Get the location query from the request
        query = request.args.get('q')
        if not query:
            app.logger.error("Geocoding error: No location specified")
            return jsonify({'error': 'No location specified'}), 400
        
        # Verify API key is properly set
        api_key = os.environ.get('OPENWEATHERMAP_API_KEY')
        if not api_key:
            app.logger.error("Geocoding error: API key not configured")
            return jsonify({'error': 'Weather service is currently unavailable'}), 500
        
        # Log the request we're about to make
        geocode_url = f"http://api.openweathermap.org/geo/1.0/direct?q={query}&limit=5&appid={api_key}"
        app.logger.info(f"Making geocoding request for: {query}")
        
        # Call OpenWeatherMap's geocoding API with a timeout
        response = requests.get(geocode_url, timeout=10)
        
        # Log the response status
        app.logger.info(f"Geocoding API response status: {response.status_code}")
        
        if response.status_code != 200:
            app.logger.error(f"Geocoding API error: {response.status_code} - {response.text}")
            return jsonify({
                'error': 'Failed to geocode location',
                'status_code': response.status_code,
                'message': response.text
            }), 500
        
        # Try to parse the JSON response
        try:
            location_data = response.json()
        except ValueError as json_error:
            app.logger.error(f"Failed to parse geocoding response: {str(json_error)}")
            return jsonify({'error': 'Invalid response from geocoding service'}), 500
        
        # Check if we got any results
        if not location_data:
            app.logger.info(f"No locations found for query: {query}")
            return jsonify([])  # Return empty array, not an error
            
        # Simplify the response to just what we need
        simplified_data = []
        for location in location_data:
            simplified_data.append({
                'name': location.get('name', 'Unknown'),
                'lat': location.get('lat'),
                'lon': location.get('lon'),
                'country': location.get('country', ''),
                'state': location.get('state', '')
            })
        
        return jsonify(simplified_data)
        
    except requests.exceptions.RequestException as req_error:
        # Handle network or timeout errors
        app.logger.error(f"Geocoding request error: {str(req_error)}")
        return jsonify({
            'error': 'Unable to connect to geocoding service',
            'details': str(req_error)
        }), 500
    except Exception as e:
        # Catch all other errors
        app.logger.error(f"Unexpected geocoding error: {str(e)}")
        return jsonify({
            'error': 'Weather service is currently unavailable',
            'details': str(e)
        }), 500
    
def generate_farm_advisories(current, forecast):
    """Generate farming recommendations and alerts based on weather conditions"""
    alerts = []
    recommendations = []
    
    # Check for extreme temperatures
    if current['temperature'] > 35:
        alerts.append({
            'title': 'Heat Warning',
            'message': 'Extreme heat conditions may stress crops and livestock. Ensure adequate shade and hydration.'
        })
        recommendations.append('Water crops during early morning or evening to minimize evaporation')
        recommendations.append('Check irrigation systems for optimal function')
    
    # Check for precipitation
    total_precipitation = sum(day.get('precipitation', 0) for day in forecast)
    if total_precipitation > 50:
        alerts.append({
            'title': 'Heavy Rain Expected',
            'message': f'Approximately {round(total_precipitation)}mm of rain expected in the next 7 days. Check drainage systems.'
        })
        recommendations.append('Inspect and clear drainage ditches')
        recommendations.append('Consider delaying fertilizer application')
    elif total_precipitation < 5:
        alerts.append({
            'title': 'Dry Conditions',
            'message': 'Limited rainfall expected. Monitor soil moisture levels.'
        })
        recommendations.append('Plan irrigation schedule for coming week')
        recommendations.append('Consider applying mulch to retain soil moisture')
    
    # Wind advisories
    if current['wind_speed'] > 10:
        alerts.append({
            'title': 'Strong Winds',
            'message': f'Wind speeds of {current["wind_speed"]}m/s may affect spraying operations and young plants.'
        })
        recommendations.append('Delay pesticide spraying until wind conditions improve')
    
    # Default recommendations if none were generated
    if not recommendations:
        recommendations = [
            'Regular monitoring of crop health is recommended',
            'Check soil moisture levels before irrigation',
            'Monitor for pest activity in current conditions'
        ]
    
    return {
        'alerts': alerts,
        'recommendations': recommendations
    }

@app.errorhandler(404)
def page_not_found(e):
    # Simplified error handler that doesn't require a template
    return "Page not found (404)", 404

@app.errorhandler(500)
def internal_server_error(e):
    # Simplified error handler that doesn't require a template
    return "Internal server error (500)", 500

@app.route('/final_report/')
def final_report():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('farm_advisor.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM reports             
    WHERE user_id = ?
    """, (session['user_id'],))
    
    reports = cursor.fetchall()  # Fetch all reports
    conn.close()
    
    if not reports:
        flash('No reports found!', 'warning')
        return redirect(url_for('dashboard'))  # Redirect to a different page if no reports exist

    return render_template('final_report.html', reports=reports)  # Pass reports (list), not report (single)

@app.route('/delete_report/<report_id>', methods=['POST'])
def delete_report(report_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('farm_advisor.db')
    cursor = conn.cursor()
    
    # First verify the report belongs to the current user
    cursor.execute("SELECT user_id FROM reports WHERE report_id = ?", (report_id,))
    report = cursor.fetchone()
    
    if not report or report[0] != session['user_id']:
        conn.close()
        flash('Report not found or you do not have permission to delete it!', 'danger')
        return redirect(url_for('final_report'))
    
    # Delete the report
    cursor.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
    conn.commit()
    conn.close()
    
    flash('Report successfully deleted!', 'success')
    return redirect(url_for('final_report'))


# Create a simple favicon route to avoid 404 errors
@app.route('/favicon.ico')
def favicon():
    return '', 204  # Return empty response with 204 status code (No Content)

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    if not OPENWEATHERMAP_API_KEY:
        print("Error: OPENWEATHERMAP_API_KEY not set!")
        exit(1)
    app.run(debug=True)
