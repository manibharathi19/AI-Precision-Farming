import os
from flask import Flask, render_template, request, jsonify, send_file
from agricultural_recommendation import get_groq_prediction, get_groq_fertilizer_prediction, generate_pdf_report
from llc import analyze_leaf_color

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_recommendations', methods=['POST'])
def get_recommendations():
    # Check if the request contains a file
    if 'leaf_image' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    # Save the uploaded image
    leaf_image = request.files['leaf_image']
    image_path = os.path.join(UPLOAD_FOLDER, leaf_image.filename)
    leaf_image.save(image_path)

    # Extract other form data
    farmer_data = {
        "farmerName": request.form.get('farmerName'),
        "farmerId": request.form.get('farmerId'),
        "location": request.form.get('location'),
        "landArea": request.form.get('landArea'),
        "preferredCrops": request.form.get('preferredCrops'),
        "waterAvailability": request.form.get('waterAvailability'),
        "soilType": request.form.get('soilType'),
        "cropHistory": request.form.get('cropHistory'),
        "pH": request.form.get('pH'),
        "nitrogen": request.form.get('nitrogen'),
        "phosphorus": request.form.get('phosphorus'),
        "potassium": request.form.get('potassium'),
        "leaf_image_path": image_path
    }

    # Get AI-based crop recommendation
    crop_suggestion = get_groq_prediction(farmer_data)

    # Get AI-based fertilizer recommendation
    fertilizer_suggestion = get_groq_fertilizer_prediction(farmer_data)

    # Analyze leaf color
    lcc_result = analyze_leaf_color(image_path)

    # Generate PDF report
    pdf_path = generate_pdf_report(farmer_data, crop_suggestion, fertilizer_suggestion, lcc_result)

    return jsonify({
        'crop_suggestion': crop_suggestion,
        'fertilizer_suggestion': fertilizer_suggestion,
        'lcc_result': lcc_result,
        'pdf_path': pdf_path
    })

@app.route('/download_report', methods=['GET'])
def download_report():
    pdf_path = request.args.get('pdf_path')
    return send_file(pdf_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)