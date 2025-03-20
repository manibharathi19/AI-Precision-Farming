import requests
import os
from dotenv import load_dotenv
from geopy.geocoders import Nominatim

# Load API key from .env file
load_dotenv()
API_KEY = os.getenv("OPENWEATHERMAP_API_KEY")

# Function to get latitude and longitude for a given location
def get_coordinates(location):
    geolocator = Nominatim(user_agent="geoapi")
    location_data = geolocator.geocode(location)
    if location_data:
        return {
            "Latitude": location_data.latitude,
            "Longitude": location_data.longitude,
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
            "Temperature (°C)": data.get("main", {}).get("temp", "N/A"),
            "Humidity (%)": data.get("main", {}).get("humidity", "N/A"),
            "Rainfall (mm)": data.get("rain", {}).get("1h", "No Rain")
        }
    else:
        print(f"Error fetching weather data: {response.status_code} - {response.text}")
        return None

# Example usage
if __name__ == "__main__":
    location = input("Enter city or PIN code: ")
    weather_data = get_weather(location)
    
    if weather_data:
        print("\nWeather Data:")
        for key, value in weather_data.items():
            print(f"{key}: {value}")
