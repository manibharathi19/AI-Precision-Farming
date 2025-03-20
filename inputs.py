import requests
import os
from dotenv import load_dotenv
from geopy.geocoders import Nominatim

# Load API key from .env file
load_dotenv()
API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")

# Validate API key
if not API_KEY:
    print("Error: OpenWeatherMap API key not found. Check your .env file.")
    exit()

# Function to get latitude and longitude for a given location
def get_coordinates(location):
    geolocator = Nominatim(user_agent="geoapi", timeout=10)
    location_data = geolocator.geocode(location)
    if location_data:
        return {
            "Latitude": round(location_data.latitude, 2),  # Rounding to 2 decimal places
            "Longitude": round(location_data.longitude, 2),
            "Location": location
        }
    else:
        return None

# Function to get weather data
def get_weather(location):
    coordinates = get_coordinates(location)
    if not coordinates:
        print("Unable to fetch coordinates.")
        return None

    lat, lon = coordinates["Latitude"], coordinates["Longitude"]
    url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}&units=metric"

    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        return {
            **coordinates,
            "Temperature (°C)": round(data.get("main", {}).get("temp", 0), 2),
            "Humidity (%)": data.get("main", {}).get("humidity", "N/A"),
            "Rainfall (mm)": data.get("rain", {}).get("1h", "No Rain")
        }
    else:
        print(f"Error fetching weather data: {response.status_code} - {response.text}")
        return None

# Function to get soil data
def get_soil_data(lat, lon):
    url = f"https://rest.isric.org/soilgrids/v2.0/properties/query?lon={lon}&lat={lat}"
    
    properties = ["phh2o", "sand", "clay", "silt", "ocd", "nitrogen"]
    response = requests.get(url)

    if response.status_code == 200:
        soil_data = response.json()
        soil_info = {"Latitude": lat, "Longitude": lon}
        
        for layer in soil_data.get("properties", {}).get("layers", []):  
            prop_name = layer.get("name", "")
            if prop_name in properties:
                try:
                    value = layer["depths"][0]["values"]["mean"]

                    # Check for None before applying operations
                    if value is None:
                        soil_info[prop_name.upper()] = "Data Not Available"
                    else:
                        # Adjust pH scale if applicable
                        if prop_name == "phh2o":
                            value /= 10  
                        soil_info[prop_name.upper()] = round(value, 2)  # Round values to 2 decimal places
                except KeyError:
                    soil_info[prop_name.upper()] = "Data Not Available"
        
        return soil_info
    else:
        print("Error fetching soil data:", response.status_code)
        return None

# Main execution
if __name__ == "__main__":
    location = input("Enter city or PIN code: ")
    
    # Fetch weather data
    weather_data = get_weather(location)
    
    if weather_data:
        print("\nWeather Data:")
        for key, value in weather_data.items():
            print(f"{key}: {value}")

        # Fetch soil data using lat & lon from weather data
        lat, lon = weather_data["Latitude"], weather_data["Longitude"]
        soil_data = get_soil_data(lat, lon)

        if soil_data:
            print("\nSoil Data:")
            for key, value in soil_data.items():
                print(f"{key}: {value}")
