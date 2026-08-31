from google import genai
from google.genai import types
from dotenv import load_dotenv
import os

load_dotenv()

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)


def get_weather(city: str):
    """Get current weather for a city.

    Args:
        city: The name of the city.
    """
    print(f"\n🔧 TOOL CALLED: get_weather(city='{city}')")

    return f"Sunny in {city}, 28°C"


response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents="What's the weather in Hyderabad?",
    config=types.GenerateContentConfig(
        tools=[get_weather]
    )
)

print("\n🤖 GEMINI RESPONSE:")
print(response.text)