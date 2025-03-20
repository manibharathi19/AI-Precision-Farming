import requests

# Define latitude and longitude
lat, lon = 11.1271, 78.6569  

# List of soil properties to fetch
properties = ["phh2o", "sand", "clay", "silt", "ocd"]

# Construct API request URL
url = f"https://rest.isric.org/soilgrids/v2.0/properties/query?lon={lon}&lat={lat}&depth=0-5cm&value=mean"

# Send request to SoilGrids API
response = requests.get(url)

# Check if request was successful
if response.status_code == 200:
    soil_data = response.json()
    
    # Extract and print soil properties
    print(f"Location: Lat {lat}, Lon {lon}")
    
    # Loop through available layers in the response
    for layer in soil_data.get("properties", {}).get("layers", []):  
        prop_name = layer.get("name", "")
        if prop_name in properties:
            try:
                value = layer["depths"][0]["values"]["mean"]
                if prop_name == "phh2o":  
                    value /= 10  # pH values need division by 10
                print(f"{prop_name.upper()}: {value}")
            except KeyError:
                print(f"{prop_name.upper()}: Data not available")
else:
    print("Error fetching soil data:", response.status_code)
