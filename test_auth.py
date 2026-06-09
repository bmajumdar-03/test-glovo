import google.auth
import os

print(f"GOOGLE_CLOUD_PROJECT: {os.environ.get('GOOGLE_CLOUD_PROJECT')}")
print(f"GCP_PROJECT: {os.environ.get('GCP_PROJECT')}")

try:
    credentials, project = google.auth.default()
    print(f"google.auth.default() returned project: {project}")
except Exception as e:
    print(f"Error: {e}")
