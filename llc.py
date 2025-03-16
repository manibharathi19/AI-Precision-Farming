import cv2
import numpy as np

def analyze_leaf_color(image_path):
    """
    Analyze the leaf image and determine nitrogen levels based on Leaf Color Chart (LCC).
    """
    image = cv2.imread(image_path)
    if image is None:
        return "Error: Image not found!"

    # Resize image to reduce processing time
    image = cv2.resize(image, (500, 500))

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    LCC_GREEN_LOW = np.array([35, 50, 50])
    LCC_GREEN_HIGH = np.array([85, 255, 255])

    mask = cv2.inRange(hsv, LCC_GREEN_LOW, LCC_GREEN_HIGH)
    percentage = (cv2.countNonZero(mask) / mask.size) * 100
    
    # Convert percentage to LCC score (assumed scale from 1 to 5)
    lcc_score = round((percentage / 100) * 5, 1)

    if percentage < 30:
        return f"Leaf is pale! Nitrogen Deficient. Apply 25 kg/ha Urea. (LCC Score: {lcc_score})"
    elif 30 <= percentage < 70:
        return f"Leaf is healthy. Nitrogen is sufficient. No extra fertilizer needed. (LCC Score: {lcc_score})"
    else:
        return f"Leaf is too dark green! Risk of excessive nitrogen. Reduce fertilizer usage. (LCC Score: {lcc_score})"