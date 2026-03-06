import os
import instructor
from google import genai
from pydantic import BaseModel

class UserInfo(BaseModel):
    name: str
    age: int

# We'll mock the api key for syntax check, but since we don't have a real one we'll see if it fails at the constructor or run.
try:
    client = instructor.from_genai(genai.Client(api_key="fake-key"))
    resp = client.chat.completions.create(
        model="gemini-2.5-flash",
        response_model=UserInfo,
        messages=[
            {"role": "system", "content": "Extract user info."},
            {"role": "user", "content": "I am Bob and I am 30."}
        ]
    )
    print(resp)
except Exception as e:
    print(f"Error: {e}")
