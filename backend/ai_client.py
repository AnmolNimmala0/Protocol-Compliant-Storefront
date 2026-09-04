import json
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from groq import Groq


load_dotenv()


# =========================================================
# CLIENTS
# =========================================================

gemini = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

groq = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


# =========================================================
# CONFIG
# =========================================================

GEMINI_MODEL = "gemini-3.5-flash-lite"
GROQ_MODEL = "openai/gpt-oss-20b"

MAX_GEMINI_RETRIES = 3
MAX_GROQ_RETRIES = 2


# =========================================================
# SCHEMA HELPERS
# =========================================================

def schema_to_prompt(response_schema):
    """Convert a Pydantic schema into instructions for Groq."""

    if response_schema is None:
        return ""

    schema = response_schema.model_json_schema()

    return f"""

You MUST return valid JSON matching this JSON Schema:

{json.dumps(schema, indent=2)}

Return ONLY the JSON object.
Do not use markdown.
Do not include explanations outside the JSON.
"""


# =========================================================
# GEMINI
# =========================================================

def generate_gemini(contents, response_schema=None):
    """Call Gemini with retries for temporary failures."""

    for attempt in range(MAX_GEMINI_RETRIES):
        try:
            config_kwargs = {
                "response_mime_type": "application/json",
            }

            if response_schema is not None:
                config_kwargs["response_schema"] = response_schema

            response = gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    **config_kwargs
                ),
            )

            if not response.text:
                raise RuntimeError("Gemini returned an empty response.")

            print(
                f"\n🧠 Gemini succeeded "
                f"(attempt {attempt + 1})"
            )

            return response.text

        except Exception as e:
            print(
                f"\n⚠️ Gemini attempt "
                f"{attempt + 1}/{MAX_GEMINI_RETRIES} failed:"
            )
            print(str(e))

            if attempt < MAX_GEMINI_RETRIES - 1:
                delay = 2 ** attempt
                print(f"⏳ Retrying Gemini in {delay}s...")
                time.sleep(delay)

    return None


# =========================================================
# GROQ FALLBACK
# =========================================================

def generate_groq(contents, response_schema=None):
    """Call Groq as the fallback provider and enforce JSON output."""

    prompt = contents + schema_to_prompt(response_schema)

    for attempt in range(MAX_GROQ_RETRIES):
        try:
            print(
                f"\n🚀 Falling back to Groq "
                f"({GROQ_MODEL})"
            )

            response = groq.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )

            text = response.choices[0].message.content

            if not text:
                raise RuntimeError("Groq returned an empty response.")

            text = text.strip()

            if text.startswith("```"):
                text = text.replace("```json", "", 1)
                text = text.replace("```", "", 1)
                text = text.strip()

            parsed = json.loads(text)

            if response_schema is not None:
                response_schema.model_validate(parsed)

            print("✅ Groq fallback succeeded")

            return text

        except Exception as e:
            print(
                f"⚠️ Groq attempt "
                f"{attempt + 1}/{MAX_GROQ_RETRIES} failed: {e}"
            )

            if attempt < MAX_GROQ_RETRIES - 1:
                time.sleep(1)

    raise RuntimeError(
        "Both Gemini and Groq failed to produce a valid AI response."
    )


# =========================================================
# UNIFIED AI ENTRY POINT
# =========================================================

def generate(contents, response_schema=None):
    """
    Unified AI entry point used by the application.

    Gemini is the primary provider. Temporary Gemini failures
    are retried before Groq is used as a fallback.
    """

    result = generate_gemini(
        contents=contents,
        response_schema=response_schema,
    )

    if result is not None:
        return result

    print("\n🔄 Gemini unavailable after retries.")

    return generate_groq(
        contents=contents,
        response_schema=response_schema,
    )
