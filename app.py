from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
import uuid
from datetime import datetime
import numpy as np
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash

conn = sqlite3.connect('farm_advisor.db')
cursor = conn.cursor()
cursor.execute("PRAGMA journal_mode=WAL;")  # Enables Write-Ahead Logging
conn.commit()
conn.close()

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

        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, password, email, farmer_id, location) VALUES (?, ?, ?, ?, ?)',
                         (username, password, email, farmer_id, location))
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
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password)).fetchone()
        conn.close()

        if user:
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
    print("Session Data:", session)  # Debugging output

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
        
        # Store data in session for later use
        session['soil_data'] = {
            'nitrogen': nitrogen,
            'phosphorus': phosphorus,
            'potassium': potassium,
            'ph': ph,
            'rainfall': rainfall,
            'temperature': temperature,
            'humidity': humidity
        }
        
        # Simple crop recommendation logic
        # This is a simplified version and should be replaced with actual ML model
        if nitrogen > 100 and phosphorus > 100 and potassium > 100:
            top_crop = "Rice"
            top_crop_confidence = 88.5
            top_crop_description = "Rice thrives in nitrogen-rich soils with good water retention."
            alternative_crops = [
                {"name": "Wheat", "confidence": 75.2},
                {"name": "Maize", "confidence": 68.7}
            ]
        elif nitrogen > 80 and phosphorus > 40 and potassium > 40:
            top_crop = "Cotton"
            top_crop_confidence = 82.3
            top_crop_description = "Cotton performs well in your soil conditions with moderate fertilizer needs."
            alternative_crops = [
                {"name": "Sugarcane", "confidence": 70.8},
                {"name": "Jute", "confidence": 65.4}
            ]
        elif phosphorus > 80 and potassium > 80:
            top_crop = "Groundnut"
            top_crop_confidence = 79.6
            top_crop_description = "Groundnut (Peanut) is well-suited to phosphorus-rich soils."
            alternative_crops = [
                {"name": "Soybean", "confidence": 73.1},
                {"name": "Black gram", "confidence": 67.5}
            ]
        else:
            top_crop = "Maize"
            top_crop_confidence = 76.2
            top_crop_description = "Maize is adaptable to various soil conditions and suitable for your farm."
            alternative_crops = [
                {"name": "Millet", "confidence": 69.8},
                {"name": "Sorghum", "confidence": 65.3}
            ]
        
        # Store crop recommendation in session
        session['crop_recommendation'] = {
            'top_crop': top_crop,
            'top_crop_confidence': top_crop_confidence,
            'top_crop_description': top_crop_description,
            'alternative_crops': alternative_crops
        }
        
        # Save to database
        conn = sqlite3.connect('farm_advisor.db')
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO reports 
        (user_id, report_id, crop_recommendation, soil_n, soil_p, soil_k, soil_ph, rainfall, temperature, humidity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            session['user_id'],
            session['report_id'],
            top_crop,
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
        
        return render_template('results_page.html', 
                              top_crop=top_crop,
                              top_crop_confidence=top_crop_confidence,
                              top_crop_description=top_crop_description,
                              alternative_crops=alternative_crops)
    
    return redirect(url_for('input_form'))

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
        name = request.form['name']
        email = request.form['email']
        
        conn = sqlite3.connect('farm_advisor.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET name = ?, email = ? WHERE id = ?", 
                      (name, email, session['user_id']))
        conn.commit()
        conn.close()
        
        session['name'] = name
        flash('Profile updated successfully!', 'success')
        
    return redirect(url_for('profile'))

@app.route('/weather_data')
def weather_data():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # This would typically fetch real weather data from an API
    # For demonstration, we'll use static data
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
    
    return render_template('weather.html', weather=weather_info)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

@app.route('/final_report')
def final_report(report_id):
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
    
    return render_template('final_report.html', report=report)

if __name__ == '__main__':
    app.run(debug=True)