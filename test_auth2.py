import os
from google.genai import Client

print(f"ENV GOOGLE_CLOUD_PROJECT: {os.environ.get('GOOGLE_CLOUD_PROJECT')}")

client = Client(vertexai=True)
try:
    print(f"Client project: {client.project}")
except AttributeError:
    print("Client has no project attribute")

try:
    # Attempt to make a minimal call to see the exact error
    client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Hello",
    )
except Exception as e:
    print(f"Error calling generate_content: {e}")
