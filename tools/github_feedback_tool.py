# tools/github_feedback_tool.py

import os
import json
from dotenv import load_dotenv
from github import Github, Auth

# Dynamically import depending on environment flags
# if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true":
#     import vertexai
#     from vertexai.generative_models import GenerativeModel
# else:
#     import google.generativeai as genai

# Remove the conditional Vertex AI import block at the top and keep:
import google.generativeai as genai

load_dotenv("/usr/local/google/home/bmajumdar/Documents/GH-PR/github-PR/.env")

class FeedbackExtractor:
    def __init__(self, repo_name: str, pr_number: int):
        self.project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID")
        self.location = os.getenv("GCP_LOCATION", "us-central1")
        self.secret_id = os.getenv("SECRET_ID")
        self.secret_version = os.getenv("SECRET_VERSION", "latest")
        self.repo_name = repo_name
        self.pr_number = pr_number
        
        # 1. Resolve GitHub Token (Secret Manager vs. Fallback ENV)
        self.token = self._resolve_token()
        auth = Auth.Token(self.token)
        self.g = Github(auth=auth)
        self.repo = self.g.get_repo(self.repo_name)
        self.pr = self.repo.get_pull(self.pr_number)
        
        # 2. Safe, Dynamic Model Initialization
        self.model = self._initialize_model()

    # def _resolve_token(self) -> str:
    #     """Helper to safely fetch token from GCP Secret Manager or local environment."""
    #     if self.project_id and self.secret_id:
    #         try:
    #             from google.cloud import secretmanager
    #             client = secretmanager.SecretManagerServiceClient()
    #             name = f"projects/{self.project_id}/secrets/{self.secret_id}/versions/{self.secret_version}"
    #             response = client.access_secret_version(request={"name": name})
    #             return response.payload.data.decode("UTF-8").strip()
    #         except Exception:
    #             pass
    #     return os.getenv("GITHUB_TOKEN", "").strip()

    def _resolve_token(self) -> str:
        """Fetch token directly from local environment configuration."""
        return os.getenv("GITHUB_TOKEN", "").strip()

    # def _initialize_model(self):
    #     """Dynamically loads and configures either Vertex AI or standard Gemini depending on variables."""
    #     use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
        
    #     if use_vertex:
    #         try:
    #             import vertexai
    #             from vertexai.generative_models import GenerativeModel
    #             vertexai.init(project=self.project_id, location=self.location)
    #             print(" > Configured Vertex AI Client successfully.")
    #             return GenerativeModel("gemini-1.5-flash")
    #         except ImportError:
    #             print(" ⚠️ vertexai SDK is missing from your environment. Attempting Google AI fallback...")

    #     # Fallback / Default: Standard google-generativeai API Key pathway
    #     try:
    #         import google.generativeai as genai
    #         api_key = os.getenv("GEMINI_API_KEY")
    #         genai.configure(api_key=api_key)
    #         print(" > Configured Google AI Developer Client successfully.")
    #         return genai.GenerativeModel("gemini-1.5-flash")
    #     except ImportError:
    #         # Fallback to local Vertex SDK if standard Google SDK is not installed
    #         try:
    #             import vertexai
    #             from vertexai.generative_models import GenerativeModel
    #             vertexai.init(project=self.project_id, location=self.location)
    #             print(" > Standard SDK missing, fell back to Vertex AI successfully.")
    #             return GenerativeModel("gemini-1.5-flash")
    #         except Exception:
    #             raise ImportError(
    #                 "Missing both 'google-generativeai' and 'google-cloud-aiplatform' dependencies. "
    #                 "Please install at least one of these to activate LLM services."
    #             )


    def _initialize_model(self):
        """Configures standard Gemini developer client using GEMINI_API_KEY."""
        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY is not set in the environment.")
            
            genai.configure(api_key=api_key)
            print(" > Configured Google AI Developer Client successfully.")
            return genai.GenerativeModel("gemini-1.5-flash")
        except Exception as e:
            raise ImportError(
                f"Failed to initialize standard Google AI Developer Client: {str(e)}"
            )

    def _get_comments(self) -> list:
        extracted = []
        
        # Get line-item review comments
        review_comments = self.pr.get_review_comments()
        for comment in review_comments:
            extracted.append({
                "type": "inline",
                "path": comment.path,
                "body": comment.body,
                "diff_hunk": comment.diff_hunk,
                "comment_id": comment.id
            })
            
        # Get top-level conversation comments
        issue_comments = self.pr.get_issue_comments()
        for comment in issue_comments:
            extracted.append({
                "type": "general",
                "path": "General PR Scope",
                "body": comment.body,
                "diff_hunk": None,
                "comment_id": comment.id
            })
        return extracted

    def parse_feedback_with_llm(self, comment_data: dict) -> dict:
        prompt = f"""
        You are a software architect analyzing developer reviews on code changes.
        Analyze this comment.

        If the comment is POSITIVE, APPROVING, or conversational with no action needed, return:
        {{
            "is_actionable_error": false
        }}

        If the comment is NEGATIVE, CRITICAL, or requests a code fix, return this schema:
        {{
            "is_actionable_error": true,
            "identified_error": "Description of what was rejected or failed",
            "affected_file": "{comment_data['path']}",
            "remediation_plan": "Step-by-step instructions to fix the issue"
        }}

        Review Comment: "{comment_data['body']}"
        Target File: {comment_data['path']}
        Code context: {comment_data['diff_hunk']}

        Return raw JSON only. No markdown formatting.
        """
        try:
            # Handle Vertex AI vs Developer SDK generation signature differences
            response = self.model.generate_content(prompt)
            cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned_text)
        except Exception as e:
            return {
                "is_actionable_error": False,
                "error": str(e)
            }

    def process(self) -> list:
        raw_comments = self._get_comments()
        structured_feedback = []
        for comment in raw_comments:
            if "[Caretta]" in comment["body"] or "automated" in comment["body"]:
                continue
            parsed = self.parse_feedback_with_llm(comment)
            if parsed.get("is_actionable_error") is True:
                parsed["comment_id"] = comment["comment_id"]
                parsed["pr_number"] = self.pr_number
                structured_feedback.append(parsed)
        return structured_feedback

def extract_pr_feedback(pr_number: int) -> str:
    repo_name = os.getenv("GITHUB_REPO")
    if not repo_name:
        return "Error: GITHUB_REPO not defined in environment."
    try:
        extractor = FeedbackExtractor(repo_name, pr_number)
        feedback_list = extractor.process()
        return json.dumps(feedback_list, indent=2)
    except Exception as e:
        return f"Failed to retrieve or process PR feedback: {str(e)}"
