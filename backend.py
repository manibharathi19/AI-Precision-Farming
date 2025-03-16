import os
from dotenv import load_dotenv
import requests
from fpdf import FPDF
import time
import cx_Oracle
from llc import analyze_leaf_color
import tkinter as tk
from tkinter import filedialog

# Load environment variables from .env file
load_dotenv()

# Oracle DB Connection Details
DB_USERNAME = "SCOTT"  
DB_PASSWORD = "TIGER"  
DB_DSN = "localhost/orcl123"  # Update with your Oracle service name

# Open file dialog to select image
root = tk.Tk()
root.withdraw()
file_path = filedialog.askopenfilename(title="Select a Leaf Image", filetypes=[("Image Files", "*.png;*.jpg;*.jpeg")])

if file_path:
    lcc_result = analyze_leaf_color(file_path)
else:
    lcc_result = "No leaf image selected."
    print("No leaf image selected.")

# Function to connect to Oracle DB
def connect_db():
    try:
        connection = cx_Oracle.connect(DB_USERNAME, DB_PASSWORD, DB_DSN)
        return connection
    except cx_Oracle.DatabaseError as e:
        print("❌ Database connection error:", e)
        return None

def get_coordinates(location):
    """
    Fetches latitude, longitude, and full address using OpenStreetMap (Nominatim API).
    The location can be a city name or a PIN code.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={location}&addressdetails=1"

    for attempt in range(3):  # Retry mechanism
        response = requests.get(url, headers=headers)

        if response.status_code == 200 and response.json():
            data = response.json()[0]
            lat, lon = float(data["lat"]), float(data["lon"])
            address = data.get("address", {})

            return {
                "Latitude": lat,
                "Longitude": lon,
                "Country": address.get("country", "N/A"),
                "State": address.get("state", "N/A"),
                "District": address.get("state_district", "N/A"),
                "Village": address.get("county", "N/A"),
                "PIN Code": location
            }

        print(f"Attempt {attempt+1} failed. Retrying in 2 seconds...")
        time.sleep(2)

    print("Error: Unable to fetch coordinates after multiple attempts.")
    return None


def get_weather(location):
    """
    Fetches real-time weather data using OpenWeatherMap API.
    The location can be a city name or a PIN code.
    """
    coordinates = get_coordinates(location)
    if not coordinates:
        print("Unable to fetch coordinates automatically.")
        return None

    lat, lon = coordinates["Latitude"], coordinates["Longitude"]

    api_key = os.getenv("OPENWEATHERMAP_API_KEY")
    if not api_key:
        print("Error: OPENWEATHERMAP_API_KEY is missing in the .env file.")
        return None

    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        return {
            **coordinates,  # Includes State, District, Village, Latitude, Longitude
            "Temperature": data.get("main", {}).get("temp", "N/A"),
            "Humidity": data.get("main", {}).get("humidity", "N/A"),
            "Rainfall": data.get("rain", {}).get("1h", "N/A")
        }
    else:
        print(f"Error fetching weather data: {response.status_code} - {response.text}")
        return None


# Function to get AI-based crop recommendation
def get_groq_prediction(input_data):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}", "Content-Type": "application/json"}

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert in soil health and crop recommendations. "
                    "Given soil parameters, suggest the most suitable crop based on soil nutrients, pH, and climate. "
                    "Also, suggest necessary soil amendments (like Lime, Gypsum, etc.) to optimize soil conditions. "
                    "If applicable, provide an estimated yield prediction based on typical crop performance in similar conditions. "
                    "Ensure responses follow this format:\n"
                    "- Crop: [Crop Name]\n"
                    "- Soil Amendments: [List of amendments]\n"
                    "- Estimated Yield: [Yield range in kg/ha] (if applicable)"
                )
            },
            {
                "role": "user",
                "content": f"Here is the soil and climate data: {input_data}. Suggest the best crop for cultivation, necessary soil amendments, and estimated yield."
            }
        ],
        "temperature": 0.0  # Ensures deterministic output
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        prediction = response.json().get("choices", [{}])[0].get("message", {}).get("content", "No prediction")
        return f"Prediction: {prediction}"
    else:
        print("Error:", response.status_code, response.text)
        return "Error in prediction"

# Function to get AI-based fertilizer recommendation
def get_groq_fertilizer_prediction(input_data):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}", "Content-Type": "application/json"}

    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert in soil health and crop recommendations. "
                    "Given soil parameters, weather conditions, and crop type, suggest the most suitable fertilizer. "
                    "Ensure responses follow this format:\n"
                    "- Fertilizer: [Fertilizer Name]\n"
                    "- Application Rate: [Rate in kg/ha]\n"
                )
            },
            {
                "role": "user",
                "content": f"Here is the Leaf color chart Score and result: {lcc_result} , Here is the soil and weather data: {input_data}. Suggest the best fertilizer and application rate."
            }
        ],
        "temperature": 0.0  # Ensures deterministic output
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        prediction = response.json().get("choices", [{}])[0].get("message", {}).get("content", "No prediction")
        return f"Prediction: {prediction}"
    else:
        print("Error:", response.status_code, response.text)
        return "Error in prediction"
    
# Store data in Oracle SQL
def store_farmer_data(user_input, crop_suggestion, fertilizer_suggestion, lcc_result):
    connection = connect_db()
    if not connection:
        return

    try:
        cursor = connection.cursor()

        def safe_float(value):
            """Convert value to float, replace 'N/A' or empty with 0.0"""
            try:
                return float(value)
            except ValueError:
                return 0.0  # Default value for missing data

        sql = """INSERT INTO farmers (name, farmer_id, location, latitude, longitude, country, state, district, village, 
                 pin_code, land_area, soil_type, crop_history, pH, nitrogen, phosphorus, potassium, temperature, humidity, 
                 rainfall, water_availability, preferred_crops, crop_suggestion, fertilizer_suggestion, lcc_result) 
                 VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11, :12, :13, :14, :15, :16, :17, :18, :19, :20, :21, :22, :23, :24, :25)"""

        data = (
            user_input["Farmer Name"], user_input["farmer_id"], user_input["location"], user_input["Latitude"],
            user_input["Longitude"], user_input["Country"], user_input["State"], user_input["District"],
            user_input["Village"], user_input["PIN Code"], 
            safe_float(user_input["Land Area"]),  
            user_input["Soil Type"], user_input["Crop History"], 
            safe_float(user_input["pH"]),         
            safe_float(user_input["Nitrogen"]),    
            safe_float(user_input["Phosphorus"]),  
            safe_float(user_input["Potassium"]),   
            safe_float(user_input["Temperature"]), 
            safe_float(user_input["Humidity"]),    
            safe_float(user_input["Rainfall"]),    
            user_input["Water Availability"], user_input["Preferred Crops"], crop_suggestion, fertilizer_suggestion, lcc_result
        )

        cursor.execute(sql, data)
        connection.commit()
        print("✅ Data stored successfully!")

    except cx_Oracle.DatabaseError as e:
        print("❌ Database error:", e)
        connection.rollback()

    finally:
        if connection:
            connection.close()
            print("🔒 Connection closed.")

# Function to remove unsupported Unicode characters (like emojis)
def remove_unicode(text):
    """Removes emojis and unsupported characters from text."""
    return text.encode("latin1", "ignore").decode("latin1")

def generate_pdf_report(user_input, crop_suggestion, fertilizer_suggestion, lcc_result):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Page 1: Farmer Details
    pdf.add_page()
    pdf.set_font("Arial", style="B", size=16)
    pdf.cell(0, 10, remove_unicode("Agricultural Health Report"), ln=True, align="C")
    pdf.cell(0, 10, "---------------------------------", ln=True, align="C")

    pdf.set_font("Arial", size=12)
    pdf.set_fill_color(200, 220, 255)
    
    # Farmer Details
    pdf.cell(200, 10, remove_unicode("Farmer Details"), ln=True, align="C", fill=True)
    
    col_width = 95  # Set column width
    row_height = 10  # Set row height

    pdf.cell(col_width, row_height, remove_unicode(f"Farmer's Name: {user_input['Farmer Name']}"), border=1)
    pdf.cell(col_width, row_height, remove_unicode(f"Farmer ID: {user_input['farmer_id']}"), border=1, ln=True)

    pdf.cell(col_width, row_height, remove_unicode(f"Country: {user_input['Country']}"), border=1)
    pdf.cell(col_width, row_height, remove_unicode(f"State: {user_input['State']}"), border=1, ln=True)

    pdf.cell(col_width, row_height, remove_unicode(f"District: {user_input['District']}"), border=1)
    pdf.cell(col_width, row_height, remove_unicode(f"Village: {user_input['Village']}"), border=1, ln=True)

    pdf.cell(col_width, row_height, remove_unicode(f"PIN Code: {user_input['PIN Code']}"), border=1)
    pdf.cell(col_width, row_height, remove_unicode(f"GPS: {user_input['Latitude']}, {user_input['Longitude']}"), border=1, ln=True)

    # Soil Parameters
    pdf.cell(200, 10, remove_unicode("Soil Parameters"), ln=True, align="C", fill=True)
    
    pdf.cell(50, row_height, remove_unicode(f"pH: {user_input['pH']}"), border=1)
    pdf.cell(50, row_height, remove_unicode(f"Nitrogen: {user_input['Nitrogen']}"), border=1)
    pdf.cell(50, row_height, remove_unicode(f"Phosphorus: {user_input['Phosphorus']}"), border=1)
    pdf.cell(50, row_height, remove_unicode(f"Potassium: {user_input['Potassium']}"), border=1, ln=True)

    # Weather Parameters
    pdf.cell(200, 10, remove_unicode("Weather Parameters"), ln=True, align="C", fill=True)
    
    pdf.cell(66, row_height, remove_unicode(f"Temperature: {user_input['Temperature']}°C"), border=1)
    pdf.cell(66, row_height, remove_unicode(f"Humidity: {user_input['Humidity']}%"), border=1)
    pdf.cell(66, row_height, remove_unicode(f"Rainfall: {user_input['Rainfall']} mm"), border=1, ln=True)

    # Page 2: Crop Recommendation
    pdf.add_page()
    pdf.cell(200, 10, remove_unicode("Crop Recommendation"), ln=True, align="C", fill=True)
    pdf.multi_cell(0, 10, remove_unicode(crop_suggestion), border=1)

    # Page 3: Fertilizer Recommendation
    pdf.add_page()
    pdf.cell(200, 10, remove_unicode("Fertilizer Recommendation"), ln=True, align="C", fill=True)
    pdf.multi_cell(0, 10, remove_unicode(fertilizer_suggestion), border=1)

    # Page 4: LCC Result
    pdf.add_page()
    pdf.cell(200, 10, remove_unicode("Leaf Color Chart (LCC) Result"), ln=True, align="C", fill=True)
    pdf.multi_cell(0, 10, remove_unicode(f"LCC Analysis: {lcc_result}"), border=1)

    # Save the PDF
    pdf.output("Agricultural_Health_Report.pdf")
    print("📄 PDF Report Generated: Agricultural_Health_Report.pdf")

def get_valid_float(prompt):
    while True:
        try:
            value = float(input(prompt))  # Convert input to FLOAT
            return value
        except ValueError:
            print("Invalid input! Please enter a numeric value.")

def get_user_input():
    use_sample_data = input("Do you want to use predefined sample data? (yes/no): ").strip().lower()
    
    if use_sample_data == "yes":
        return {
            "Farmer Name": "Bhuvanesh",
            "location": "606601",  
            "farmer_id": "1234-5678-8901",
            "Land Area": 10.0,     # Ensure FLOAT
            "Soil Type": "Loamy",
            "Crop History": "Wheat",
            "pH": 6.5,              # Ensure FLOAT
            "Nitrogen": 50.0,       # Ensure FLOAT
            "Phosphorus": 30.0,     # Ensure FLOAT
            "Potassium": 50.0,      # Ensure FLOAT
            "Water Availability": "Plentiful",
            "Preferred Crops": "Anything you can suggest."
        }
    
    return {
        "Farmer Name": input("Enter Farmer's Name: ").strip(),
        "farmer_id" : input("Enter Farmer ID / Aadhaar Number (Optional): "),
        "location" : input("Enter Village Name or PIN Code: "),
        "Land Area": get_valid_float("Enter Land Area (in acres): "),
        "Soil Type": input("Enter Soil Type (Sandy, Loamy, Clayey, Silty, etc.): ").strip(),
        "Crop History": input("Enter Last Crop Grown: ").strip(),
        "pH": get_valid_float("Enter Soil pH: "),
        "Nitrogen": get_valid_float("Enter Nitrogen Level: "),
        "Phosphorus": get_valid_float("Enter Phosphorus Level: "),
        "Potassium": get_valid_float("Enter Potassium Level: "),
        "Water Availability": input("Water Availability (Limited/Plentiful): ").strip(),
        "Preferred Crops": input("Enter Preferred Crops: ").strip()
    }

def main():
    user_input = get_user_input()
    location = user_input["location"]  # PIN Code or Village Name
    weather_data = get_weather(location)

    if weather_data:
        user_input.update(weather_data)  # Includes State, District, Village, GPS, Weather Data
    else:
        print("Using default weather values due to missing coordinates.")
    
    # Get AI recommendations
    crop_suggestion = get_groq_prediction(user_input)
    fertilizer_suggestion = get_groq_fertilizer_prediction(user_input)
    
    # Store data in the Oracle database
    store_farmer_data(user_input, crop_suggestion, fertilizer_suggestion, lcc_result)

    # Generate the PDF report
    generate_pdf_report(user_input, crop_suggestion, fertilizer_suggestion, lcc_result)

    print("✅ Data inserted into the database and PDF generated successfully!")

if __name__ == "__main__":
    main()