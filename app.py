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
from PIL import Image
from flask_cors import CORS
from flask_caching import Cache
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import lru_cache
# from googletrans import Translator
from deep_translator import GoogleTranslator
import json
import os
from translation import register_translation_handlers
from translation import test_translation_service


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
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']  # Store username in session
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')

    return render_template('login.html')


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

        # Store data in session
        soil_data = {
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

        # Pass both crop_recommendation AND soil_data to the template
        return render_template('results_page.html', 
                              crop_recommendation=crop_recommendation,
                              soil_data=soil_data)  # Add this line

    return redirect(url_for('input_form'))

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
        crop_recommendation = get_groq_prediction(combined_data)
        # print(crop_recommendation)
        session['crop_recommendation'] = crop_recommendation
        
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
                    crop_recommendation,
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
                    crop_recommendation,
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
        
        # Show results with fetched data
        return render_template('location_results.html', 
                              crop_recommendation=crop_recommendation, 
                              soil_data=combined_data)
    
    return redirect(url_for('dashboard'))

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
            flash('No file part', 'danger')
            return redirect(url_for('leaf_analysis'))
        
        file = request.files['leaf_image']
        
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(url_for('leaf_analysis'))
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Process the image with Groq API
            analysis_result = analyze_leaf_with_groq(file_path)
            
            # Extract results from the Groq analysis
            leaf_color = analysis_result['leaf_color']
            leaf_color_name = analysis_result['leaf_color_name']
            health_status = analysis_result['health_status']
            deficiencies = analysis_result['deficiencies']
            
            # Get fertilizer recommendations based on analysis
            fertilizer_recommendation = get_fertilizer_recommendation(health_status)
            
            # Store leaf analysis in session
            session['leaf_analysis'] = {
                'leaf_color': leaf_color,
                'leaf_color_name': leaf_color_name,
                'health_status': health_status,
                'deficiencies': deficiencies
            }
            
            # Store fertilizer recommendation in session
            session['fertilizer_recommendation'] = fertilizer_recommendation
            
            # Update database
            conn = sqlite3.connect('farm_advisor.db')
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE reports 
            SET leaf_analysis = ?, fertilizer_recommendation = ?
            WHERE report_id = ?
            ''', (
                leaf_color_name + ": " + health_status,
                fertilizer_recommendation['primary_fertilizer_name'],
                session.get('report_id', 0)
            ))
            conn.commit()
            conn.close()
            
            return render_template('fertilizer_recommendation.html',
                                  leaf_color="#00FF00",
                                  leaf_color_name=leaf_color_name,
                                  health_status=health_status,
                                  deficiencies=deficiencies,
                                  **fertilizer_recommendation)
    
    return redirect(url_for('leaf_analysis'))

def analyze_leaf_with_groq(image_path):
    """
    Analyze leaf image using Groq API for leaf color and health assessment
    """
    # Read and encode the image
    with open(image_path, "rb") as image_file:
        image_data = base64.b64encode(image_file.read()).decode('utf-8')
    
    # Extract dominant color from image
    img = cv2.imread(image_path)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    
    # Resize image for faster processing
    resized_img = cv2.resize(img, (100, 100))
    pixels = resized_img.reshape(-1, 3)
    
    # Calculate average color (simplified approach)
    avg_color = np.mean(pixels, axis=0)
    hex_color = '#{:02x}{:02x}{:02x}'.format(int(avg_color[0]), int(avg_color[1]), int(avg_color[2]))
    
    # Prompt for Groq API
    prompt = f"""
    Analyze this leaf image for agricultural purposes. The dominant color detected is {hex_color}.
    
    Please provide the following information:
    1. A refined leaf color name (e.g., "Healthy Green", "Yellowing", "Brown Spots", "Wilting Brown")
    2. The most likely plant health status based on the color (e.g., "Healthy", "Nitrogen Deficiency", "Potassium Deficiency", "Disease Present")
    3. A detailed description of any detected deficiencies or diseases
    
    Format your response as a JSON object with the following keys:
    - leaf_color (the hex code)
    - leaf_color_name (descriptive name)
    - health_status (diagnosis)
    - deficiencies (explanation)
    """
    
    # Call Groq API
    try:
        chat_completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are an agricultural expert specializing in leaf analysis."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        # Parse the response
        analysis_json = chat_completion.choices[0].message.content
        import json
        analysis_result = json.loads(analysis_json)
        
        # Ensure all required fields are present
        if not all(k in analysis_result for k in ['leaf_color', 'leaf_color_name', 'health_status', 'deficiencies']):
            raise ValueError("Incomplete response from API")
            
        return analysis_result
        
    except Exception as e:
        print(f"Error calling Groq API: {e}")
        # Fallback to default values in case of API failure
        return {
            'leaf_color': hex_color,
            'leaf_color_name': 'Unknown',
            'health_status': 'Analysis Failed',
            'deficiencies': f'Unable to analyze leaf image. Error: {str(e)}'
        }

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
