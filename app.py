from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
import uuid
from datetime import datetime
import numpy as np
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import requests
from geopy.geocoders import Nominatim


conn = sqlite3.connect('farm_advisor.db')
cursor = conn.cursor()
cursor.execute("PRAGMA journal_mode=WAL;")  # Enables Write-Ahead Logging
conn.commit()
conn.close()

load_dotenv()
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENWEATHERMAP_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")
GROQ_API_KEY="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"

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

app = Flask(__name__)
app.secret_key = "farmadvisorapp2025"

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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Function to connect to database
def get_db_connection():
    conn = sqlite3.connect('farm_advisor.db')
    conn.row_factory = sqlite3.Row  # Return dictionary-like rows
    return conn

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
            
            # Simplified leaf analysis logic
            # This should be replaced with actual image processing/ML model
            
            # For demonstration, we'll just randomly assign a leaf color and health status
            leaf_colors = ['#8CCB5E', '#FFCC00', '#A67C52', '#654321']
            color_names = ['Healthy Green', 'Yellowing', 'Brown Spots', 'Wilting Brown']
            health_statuses = ['Healthy', 'Nitrogen Deficiency', 'Potassium Deficiency', 'Disease Present']
            deficiency_details = [
                'No significant deficiencies detected',
                'Nitrogen deficiency detected - leaves are yellowing uniformly',
                'Potassium deficiency detected - leaf edges are browning',
                'Fungal infection detected - brown spots throughout leaf'
            ]
            
            # Random selection for demo
            index = np.random.randint(0, 4)
            leaf_color = leaf_colors[index]
            leaf_color_name = color_names[index]
            health_status = health_statuses[index]
            deficiencies = deficiency_details[index]
            
            # Store leaf analysis in session
            session['leaf_analysis'] = {
                'leaf_color': leaf_color,
                'leaf_color_name': leaf_color_name,
                'health_status': health_status,
                'deficiencies': deficiencies
            }
            
            # Fertilizer recommendation based on leaf analysis
            if index == 0:  # Healthy
                primary_fertilizer_name = "Balanced NPK Fertilizer"
                primary_fertilizer_npk = "20-20-20"
                primary_fertilizer_rate = "5 kg per acre"
                primary_fertilizer_description = "A balanced fertilizer to maintain overall plant health and growth."
                
                alt_fertilizer_name = "Slow-Release Fertilizer"
                alt_fertilizer_npk = "15-15-15"
                alt_fertilizer_description = "Provides nutrients over a longer period with less frequent application."
                
                organic_fertilizer_name = "Compost"
                organic_fertilizer_description = "Rich in organic matter to improve soil structure and fertility."
                
            elif index == 1:  # Nitrogen Deficiency
                primary_fertilizer_name = "High Nitrogen Fertilizer"
                primary_fertilizer_npk = "46-0-0"
                primary_fertilizer_rate = "7 kg per acre"
                primary_fertilizer_description = "Urea fertilizer to quickly address nitrogen deficiency."
                
                alt_fertilizer_name = "Ammonium Sulfate"
                alt_fertilizer_npk = "21-0-0"
                alt_fertilizer_description = "Provides nitrogen and sulfur, good for acidic soils."
                
                organic_fertilizer_name = "Blood Meal"
                organic_fertilizer_description = "Organic nitrogen source that releases slowly into the soil."
                
            elif index == 2:  # Potassium Deficiency
                primary_fertilizer_name = "Potash Fertilizer"
                primary_fertilizer_npk = "0-0-60"
                primary_fertilizer_rate = "6 kg per acre"
                primary_fertilizer_description = "High potassium fertilizer to address deficiency and improve crop quality."
                
                alt_fertilizer_name = "NPK with high K"
                alt_fertilizer_npk = "10-10-40"
                alt_fertilizer_description = "Balanced fertilizer with emphasis on potassium."
                
                organic_fertilizer_name = "Wood Ash"
                organic_fertilizer_description = "Natural source of potassium and other micronutrients."
                
            else:  # Disease
                primary_fertilizer_name = "Fungicide + Fertilizer Mix"
                primary_fertilizer_npk = "10-10-10 + Copper"
                primary_fertilizer_rate = "4 kg per acre"
                primary_fertilizer_description = "Combined treatment for disease control and plant nutrition."
                
                alt_fertilizer_name = "Fungicide Spray"
                alt_fertilizer_npk = "N/A"
                alt_fertilizer_description = "Targeted treatment for fungal diseases."
                
                organic_fertilizer_name = "Neem Cake"
                organic_fertilizer_description = "Natural fungicide with mild fertilizer properties."
            
            # Store fertilizer recommendation in session
            session['fertilizer_recommendation'] = {
                'primary_fertilizer_name': primary_fertilizer_name,
                'primary_fertilizer_npk': primary_fertilizer_npk,
                'primary_fertilizer_rate': primary_fertilizer_rate,
                'primary_fertilizer_description': primary_fertilizer_description,
                'alt_fertilizer_name': alt_fertilizer_name,
                'alt_fertilizer_npk': alt_fertilizer_npk,
                'alt_fertilizer_description': alt_fertilizer_description,
                'organic_fertilizer_name': organic_fertilizer_name,
                'organic_fertilizer_description': organic_fertilizer_description
            }
            
            # Update database
            conn = sqlite3.connect('farm_advisor.db')
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE reports 
            SET leaf_analysis = ?, fertilizer_recommendation = ?
            WHERE report_id = ?
            ''', (
                leaf_color_name + ": " + health_status,
                primary_fertilizer_name,
                session['report_id']
            ))
            conn.commit()
            conn.close()
            
            return render_template('fertilizer_recommendation.html',
                                  leaf_color=leaf_color,
                                  leaf_color_name=leaf_color_name,
                                  health_status=health_status,
                                  deficiencies=deficiencies,
                                  primary_fertilizer_name=primary_fertilizer_name,
                                  primary_fertilizer_npk=primary_fertilizer_npk,
                                  primary_fertilizer_rate=primary_fertilizer_rate,
                                  primary_fertilizer_description=primary_fertilizer_description,
                                  alt_fertilizer_name=alt_fertilizer_name,
                                  alt_fertilizer_npk=alt_fertilizer_npk,
                                  alt_fertilizer_description=alt_fertilizer_description,
                                  organic_fertilizer_name=organic_fertilizer_name,
                                  organic_fertilizer_description=organic_fertilizer_description)
    
    return redirect(url_for('leaf_analysis'))

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


  
# This would typically fetch real weather data from an API demonstration, we'll use static data
@app.route('/weather_data')
def weather_data():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    weather_info = {
        'current': {
            'temperature': 28,
            'humidity': 65,
            'condition': 'Partly Cloudy',
            'wind_speed': 12,
            'precipitation': 0
        },
        'forecast': [
            {'day': 'Tomorrow', 'temperature': 30, 'condition': 'Sunny'},
            {'day': 'Day 2', 'temperature': 29, 'condition': 'Cloudy'},
            {'day': 'Day 3', 'temperature': 27, 'condition': 'Rain'},
            {'day': 'Day 4', 'temperature': 26, 'condition': 'Rain'},
            {'day': 'Day 5', 'temperature': 28, 'condition': 'Partly Cloudy'}
        ]
    }

    return render_template('weather.html', weather=weather_info, now=datetime.now)

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

# Create a simple favicon route to avoid 404 errors
@app.route('/favicon.ico')
def favicon():
    return '', 204  # Return empty response with 204 status code (No Content)

if __name__ == '__main__':
    app.run(debug=True)