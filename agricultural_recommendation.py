import os
import requests
from fpdf import FPDF

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
                "content": f"Here is the Leaf color chart Score and result: {input_data.get('lcc_result', 'N/A')}, Here is the soil and weather data: {input_data}. Suggest the best fertilizer and application rate."
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

# Function to generate PDF report
def generate_pdf_report(user_input, crop_suggestion, fertilizer_suggestion, lcc_result):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    # Add content to PDF
    pdf.cell(200, 10, txt="Agricultural Health Report", ln=True, align="C")
    pdf.cell(200, 10, txt=f"Crop Suggestion: {crop_suggestion}", ln=True)
    pdf.cell(200, 10, txt=f"Fertilizer Suggestion: {fertilizer_suggestion}", ln=True)
    pdf.cell(200, 10, txt=f"LCC Result: {lcc_result}", ln=True)
    
    pdf_path = "Agricultural_Health_Report.pdf"
    pdf.output(pdf_path)
    return pdf_path