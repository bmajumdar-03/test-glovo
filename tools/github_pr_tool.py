# tools/github_pr_tool.py

import os
import time
import subprocess
import webbrowser
from enum import Enum
from dotenv import load_dotenv
from github import Github, GithubException, Auth
import google.generativeai as genai

load_dotenv("/usr/local/google/home/bmajumdar/Glovo_githubPR/.env")

class PRState(Enum):
    INIT = "INIT"
    FETCH_SECRET = "FETCH_SECRET"
    CHECK_BRANCH = "CHECK_BRANCH"
    HANDLE_CONFLICT = "HANDLE_CONFLICT"
    COMMIT_CODE = "COMMIT_CODE"
    OPEN_PR = "OPEN_PR"
    APPLY_TAGS = "APPLY_TAGS"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"

class GitHubPRStateMachine:
    def __init__(self, commit_message: str, target_directory: str = None, auto_detect: bool = True):
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.secret_id = os.getenv("SECRET_ID")
        self.secret_version = os.getenv("SECRET_VERSION", "latest")
        self.repo_name = os.getenv("GITHUB_REPO")
        
        raw_prefix = os.getenv("GITHUB_BRANCH_PREFIX", "")
        self.branch_prefix = raw_prefix.strip() if raw_prefix.strip() else "sql-migration"
        
        raw_labels = os.getenv("GITHUB_PR_LABELS", "caretta-automated")
        self.labels = [label.strip() for label in raw_labels.split(",") if label.strip()]

        self.base_branch = "main"
        
        timestamp = int(time.time())
        self.target_branch = f"{self.branch_prefix}-{timestamp}"
        
        self.commit_message = commit_message
        self.target_directory = target_directory
        self.auto_detect = auto_detect
        
        self.files_to_commit = {}  # Map of repo path -> text content
        self.state = PRState.INIT
        self.token = None
        self.repo = None
        self.pr = None  
        self.error_msg = ""

    def _access_secret_manager(self) -> str:
        """Retrieves sensitive GitHub token securely from GCP Secret Manager, falling back to local ENV."""
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{self.project_id}/secrets/{self.secret_id}/versions/{self.secret_version}"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8").strip()
        except Exception:
            fallback_token = os.getenv("GITHUB_TOKEN")
            if fallback_token:
                return fallback_token.strip()
            raise RuntimeError("GCP Secret Manager failed and no GITHUB_TOKEN fallback was found.")

    def _get_git_status_files(self) -> list:
        """Queries local Git status with explicit untracked file expansion to find all files."""
        try:
            # Adding "-uall" forces Git to list all individual files inside untracked directories
            result = subprocess.run(
                ["git", "status", "--porcelain", "-uall"],
                capture_output=True,
                text=True,
                check=True
            )
            changed_files = []
            for line in result.stdout.splitlines():
                if len(line) > 3:
                    file_path = line[3:].strip()
                    
                    # Strip surrounding quotes if Git escapes paths containing special characters or spaces
                    if file_path.startswith('"') and file_path.endswith('"'):
                        file_path = file_path[1:-1]
                        
                    # Now that nested files are expanded, os.path.isfile() will successfully evaluate to True
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        changed_files.append(file_path)
            return changed_files
        except Exception as e:
            print(f"⚠️ Failed to execute local git status check: {e}")
            return []


    def _collect_files(self):
        """Collects files and their contents dynamically using Git auto-detection or a targeted directory."""
        collected_paths = []

        if self.auto_detect:
            print(" > Scanning workspace for unstaged/untracked files using Git tracking...")
            collected_paths = self._get_git_status_files()
            if collected_paths:
                print(f" > Git detected {len(collected_paths)} changed file(s).")
            else:
                print(" > No changes detected via local Git tracking.")

        # Fallback to targeted directory scan if no changes were found via Git or if auto_detect is disabled
        if not collected_paths and self.target_directory and os.path.exists(self.target_directory):
            print(f" > Falling back to scanning directory: {self.target_directory}")
            ignore_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv'}
            ignore_files = {'.DS_Store'}
            for root, dirs, files in os.walk(self.target_directory):
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                for file in files:
                    if file in ignore_files:
                        continue
                    collected_paths.append(os.path.join(root, file))

        for path in collected_paths:
            repo_path = os.path.relpath(path, start=os.getcwd())
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.files_to_commit[repo_path] = f.read()
            except UnicodeDecodeError:
                # Silently skip binary files
                continue
            except Exception as e:
                print(f"⚠️ Could not read {path}: {e}")

    def run(self):
        print("Initializing Caretta Repository Operations State Machine...")
        self._collect_files()

        if not self.files_to_commit:
            self.error_msg = "No files with changes detected in the workspace."
            self.state = PRState.ERROR
        
        while self.state not in [PRState.SUCCESS, PRState.ERROR]:
            print(f"Current State: [{self.state.name}]")
            
            if self.state == PRState.INIT:
                if not self.repo_name:
                    self.error_msg = "Missing required environment configuration 'GITHUB_REPO'"
                    self.state = PRState.ERROR
                else:
                    self.state = PRState.FETCH_SECRET

            elif self.state == PRState.FETCH_SECRET:
                try:
                    self.token = self._access_secret_manager()
                    auth = Auth.Token(self.token)
                    g = Github(auth=auth)
                    self.repo = g.get_repo(self.repo_name)
                    self.state = PRState.CHECK_BRANCH
                except Exception as e:
                    self.error_msg = str(e)
                    self.state = PRState.ERROR

            elif self.state == PRState.CHECK_BRANCH:
                try:
                    base_ref = self.repo.get_git_ref(f"heads/{self.base_branch}")
                    self.repo.create_git_ref(ref=f"refs/heads/{self.target_branch}", sha=base_ref.object.sha)
                    print(f" > Created branch target: {self.target_branch}")
                    self.state = PRState.COMMIT_CODE
                except GithubException as e:
                    if e.status == 422:  
                        print(f" > Branch '{self.target_branch}' collision detected.")
                        self.state = PRState.HANDLE_CONFLICT
                    else:
                        self.error_msg = f"Branch creation error: {str(e)}"
                        self.state = PRState.ERROR

            elif self.state == PRState.HANDLE_CONFLICT:
                time.sleep(1) 
                timestamp = int(time.time())
                self.target_branch = f"{self.branch_prefix}-{timestamp}"
                print(f" > Diverting to unique branch signature: {self.target_branch}")
                self.state = PRState.CHECK_BRANCH

            elif self.state == PRState.COMMIT_CODE:
                try:
                    print(f" > Committing {len(self.files_to_commit)} file(s) to branch: {self.target_branch}")
                    for repo_path, content in self.files_to_commit.items():
                        try:
                            try:
                                contents = self.repo.get_contents(repo_path, ref=self.target_branch)
                                self.repo.update_file(
                                    path=repo_path,
                                    message=self.commit_message,
                                    content=content,
                                    sha=contents.sha,
                                    branch=self.target_branch
                                )
                                print(f"   - Updated: {repo_path}")
                            except GithubException as e:
                                if e.status == 404:  
                                    self.repo.create_file(
                                        path=repo_path,
                                        message=self.commit_message,
                                        content=content,
                                        branch=self.target_branch
                                    )
                                    print(f"   - Created: {repo_path}")
                                else:
                                    raise e
                        except Exception as file_err:
                            print(f" ⚠️ Failed to commit {repo_path}: {str(file_err)}")
                    
                    self.state = PRState.OPEN_PR
                except Exception as e:
                    self.error_msg = f"Code commitment sequence failed: {str(e)}"
                    self.state = PRState.ERROR

            elif self.state == PRState.OPEN_PR:
                try:
                    self.pr = self.repo.create_pull(
                        title=f"[Caretta] {self.commit_message}",
                        body="This PR contains the dynamic set of generated and modified files.",
                        head=self.target_branch,
                        base=self.base_branch
                    )
                    print(f" > Opened Pull Request successfully: {self.pr.html_url}")
                    try:
                        print(" > Launching browser to PR interface...")
                        webbrowser.open(self.pr.html_url)
                    except Exception as browser_err:
                        print(f" ⚠️ Non-fatal: Could not open browser automatically: {str(browser_err)}")
                    self.state = PRState.APPLY_TAGS
                except GithubException as e:
                    self.error_msg = f"Pull Request formulation failure: {str(e)}"
                    self.state = PRState.ERROR

            elif self.state == PRState.APPLY_TAGS:
                try:
                    if self.labels and self.pr:
                        print(f" > Applying labels to PR #{self.pr.number}: {self.labels}")
                        self.pr.add_to_labels(*self.labels)
                    self.state = PRState.SUCCESS
                except GithubException as e:
                    print(f" ⚠️ Non-fatal warning: Failed to apply PR labels: {str(e)}")
                    self.state = PRState.SUCCESS

        if self.state == PRState.SUCCESS:
            print(f"\n✅ Success. Branch: {self.target_branch}")
        else:
            print(f"\n❌ Failed. Details: {self.error_msg}")

def execute_automated_pr(commit_message: str, target_directory: str = None, auto_detect: bool = True) -> str:
    """
    Identifies all workspace changes dynamically using local Git tracking or scans 
    a fallback directory, then commits those files and opens a Pull Request.

    Args:
        commit_message: The git commit message.
        target_directory: Fallback directory to scan if auto_detect is turned off or finds no files.
        auto_detect: When true, uses local Git tracking (`git status`) to find all modified/untracked files.
    """
    machine = GitHubPRStateMachine(
        commit_message=commit_message, 
        target_directory=target_directory, 
        auto_detect=auto_detect
    )
    machine.run()
    
    if machine.state == PRState.SUCCESS:
        return f"Successfully opened PR on branch {machine.target_branch} with current workspace modifications."
    else:
        return f"Failed to execute PR workflow. Error: {machine.error_msg}"