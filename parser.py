import os
import json
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """
You are a highly precise candidate data extraction assistant. Your job is to parse unstructured text (such as recruiter notes, resume text, or email threads) and extract structured candidate information into a strictly valid JSON match.

CRITICAL RULES:
1. "Wrong-but-confident is worse than honestly-empty". If a field is not present in the text, or cannot be confidently inferred, map it to null. DO NOT invent, assume, or hallucinate details.
2. Format all dates as "YYYY-MM" (e.g., "2024-03"). If the day is present, ignore it. If only the year is present, format as "YYYY-01" or map to null if unsure. If no date is available, map to null.
3. Format phone numbers in E.164 format (e.g., "+1234567890" or "+447911123456").
4. Format location country codes as ISO-3166-1 alpha-2 uppercase country codes (e.g., "US", "CA", "IN", "GB"). If the country cannot be identified, map the country code to null.
5. Provide a float between 0.0 and 1.0 for the overall_confidence field, reflecting your certainty in the extraction quality based on details provided.

The JSON output must conform EXACTLY to the following schema:
{
  "candidate_id": "string or null",
  "full_name": "string or null",
  "emails": ["string"],
  "phones": ["string"],
  "location": {
    "city": "string or null",
    "region": "string or null",
    "country": "string (ISO-3166 alpha-2) or null"
  },
  "links": {
    "linkedin": "string or null",
    "github": "string or null",
    "portfolio": "string or null",
    "other": ["string"]
  },
  "headline": "string or null",
  "years_experience": "number or null",
  "skills": [
    {
      "name": "string",
      "confidence": "number (float between 0.0 and 1.0) or null"
    }
  ],
  "experience": [
    {
      "company": "string",
      "title": "string or null",
      "start": "string (YYYY-MM) or null",
      "end": "string (YYYY-MM) or null",
      "summary": "string or null"
    }
  ],
  "education": [
    {
      "institution": "string",
      "degree": "string or null",
      "field": "string or null",
      "end_year": "number or null"
    }
  ],
  "overall_confidence": 0.95
}

Return ONLY the raw JSON string. Do not wrap it in markdown code blocks or add any explanatory text outside the JSON block.
"""

def _get_mock_extraction(raw_text: str) -> Dict[str, Any]:
    """
    Returns a mock extraction for demonstration and testing purposes
    when no Gemini API key is configured.
    """
    text_lower = raw_text.lower()
    data = {
        "candidate_id": "cand_kani1234",
        "full_name": "Kaushikan",
        "emails": ["kani.dev@github.io"],
        "phones": [],
        "location": {
            "city": "Chennai",
            "region": "Tamil Nadu",
            "country": "IN"
        },
        "links": {
            "linkedin": None,
            "github": "https://github.com/kaniishkank",
            "portfolio": None,
            "other": []
        },
        "headline": "Software Engineer at Kani Dev",
        "years_experience": 3,
        "skills": [
            {"name": "Python", "confidence": 0.9},
            {"name": "Apache Spark", "confidence": 0.9}
        ],
        "experience": [
            {
                "company": "Kani Dev",
                "title": "Software Engineer",
                "start": "2023-01",
                "end": "Present",
                "summary": "Building data pipelines with Python and Spark."
            }
        ],
        "education": [
            {
                "institution": "Anna University",
                "degree": "B.E.",
                "field": "Computer Science",
                "end_year": 2023
            }
        ],
        "overall_confidence": 0.9
    }
    return data

def extract_unstructured_data(raw_text: str) -> Dict[str, Any]:
    """
    Extracts structured candidate data from unstructured raw text using Gemini.
    
    Args:
        raw_text: The unstructured text containing candidate info.
        
    Returns:
        A dictionary containing the parsed candidate data matching the schema.
    """
    if not raw_text or not raw_text.strip():
        logger.warning("Empty raw text provided for extraction.")
        return {
            "candidate_id": None,
            "full_name": None,
            "emails": [],
            "phones": [],
            "location": {"city": None, "region": None, "country": None},
            "links": {"linkedin": None, "github": None, "portfolio": None, "other": []},
            "headline": None,
            "years_experience": None,
            "skills": [],
            "experience": [],
            "education": [],
            "overall_confidence": 0.0
        }

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        if os.environ.get("GEMINI_MOCK", "false").lower() == "true":
            logger.info("Gemini API Key missing. Running in Mock Mode as requested.")
            return _get_mock_extraction(raw_text)
        logger.error("Gemini API Key missing (GEMINI_API_KEY or GOOGLE_API_KEY).")
        raise ValueError("Gemini API key not found in environment variables GEMINI_API_KEY or GOOGLE_API_KEY.")

    try:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=api_key)
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        
        response = client.models.generate_content(
            model=model_name,
            contents=raw_text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=0.0,
            )
        )
        
        response_text = response.text
        if not response_text:
            raise ValueError("Empty response received from Gemini API.")
            
        data = json.loads(response_text)
        return data
        
    except ImportError:
        # Fallback to the legacy google-generativeai package if the new SDK is not present
        try:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=api_key)
            model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
            
            model = legacy_genai.GenerativeModel(
                model_name=model_name,
                system_instruction=SYSTEM_INSTRUCTION
            )
            
            response = model.generate_content(
                raw_text,
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
            
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Legacy Gemini API call failed: {e}")
            raise RuntimeError(f"Failed to communicate with Gemini API via legacy client: {e}") from e
            
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        raise RuntimeError(f"Failed to communicate with Gemini API: {e}") from e
