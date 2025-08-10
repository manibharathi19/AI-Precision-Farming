# Migration from Groq API to Gemini API

This repository has been migrated from using Groq API to Google's Gemini API for AI-powered crop recommendations and leaf analysis.

## Changes Made

### 1. Dependencies Updated
- Removed: `groq==0.5.0`
- Added: `google-generativeai==0.8.3`

### 2. Functions Renamed
- `get_groq_prediction()` → `get_gemini_prediction()`
- `analyze_leaf_with_groq()` → `analyze_leaf_with_gemini()`

### 3. API Configuration
- Replaced Groq client configuration with Gemini configuration
- Updated model from `llama3-70b-8192` to `gemini-1.5-flash`

### 4. Environment Variables
- Removed: `GROQ_API_KEY`
- Added: `GEMINI_API_KEY`

## Setup Instructions

1. **Get a Gemini API Key:**
   - Visit: https://aistudio.google.com/app/apikey
   - Create a new API key

2. **Configure Environment Variables:**
   ```bash
   cp .env.example .env
   # Edit .env and add your GEMINI_API_KEY
   ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Key Benefits of Gemini API

- **Multimodal capabilities**: Native support for image analysis
- **Better performance**: Improved response times and accuracy
- **Cost-effective**: Competitive pricing model
- **Robust JSON parsing**: Better handling of structured responses

## Migration Impact

- All existing functionality remains the same from a user perspective
- Improved image analysis capabilities for leaf health assessment
- More reliable JSON response parsing
- Better error handling and validation

The migration maintains backward compatibility in terms of functionality while providing improved AI capabilities.